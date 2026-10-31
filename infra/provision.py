#!/usr/bin/env python3
"""Provision NorthStar from AWS CloudShell, without local Docker or AWS keys.

--plan performs read-only AWS checks and writes a reviewable CloudFormation
template. --deploy creates the services, initializes the database once, starts
the application, verifies HTTPS, and grants the existing GitHub role narrowly
scoped deployment permissions. Re-running does not reset a running service.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
import textwrap
import time
import urllib.error
import urllib.request

ACCOUNT = "397620884269"
REGION = "eu-north-1"
NETWORK = "northstar-network"
STACK = "northstar-services"
PROJECT = "NorthStarCEA"
EXPECTED_VPC = "vpc-084c18c9f25155f2f"
GITHUB_ROLE = "northstar-github-actions"
FAMILY = "northstar-app"
ADMIN_EMAIL = "admin@northstar.example"
REPOSITORIES = ("northstar-app", "northstar-web")


def ref(name):
    return {"Ref": name}


def att(name, attribute):
    return {"Fn::GetAtt": [name, attribute]}


def sub(value):
    return {"Fn::Sub": value}


def network(name):
    return {"Fn::ImportValue": NETWORK + "-" + name}


def tags(name):
    return [{"Key": "Project", "Value": PROJECT}, {"Key": "Name", "Value": name}]


def secret_value(secret, key):
    # ECS receives the value at task start; the template and output contain ARNs.
    return {"Fn::Join": ["", [ref(secret), ":" + key + "::"]]}


def dynamic_secret(secret, key):
    return sub("{{resolve:secretsmanager:${" + secret + "}:SecretString:" + key + "}}")


def initialization_code():
    """Runs only inside the private, short-lived initialization container."""
    return textwrap.dedent('''\
        import os
        import database
        from psycopg import sql

        database.initialize()
        db = database.connect()
        try:
            conn = db.connection
            conn.execute("SELECT pg_advisory_xact_lock(78123642)")
            username = os.environ["APP_DB_USER"]
            password = os.environ["APP_DB_PASSWORD"]
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (username,)).fetchone()
            if not exists:
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION").format(
                    sql.Identifier(username), sql.Literal(password)))
            else:
                conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(username), sql.Literal(password)))
            conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(os.environ["NORTHSTAR_DB_NAME"]), sql.Identifier(username)))
            conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            for statement in (
                "GRANT USAGE ON SCHEMA public TO {}",
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}",
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}",
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}",
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}",
            ):
                conn.execute(sql.SQL(statement).format(sql.Identifier(username)))
            conn.commit()
            print("INITIALIZATION_COMPLETE: schema, catalogue, administrator and limited application database user.", flush=True)
        finally:
            db.close()
        ''')


def build_template():
    resources = {}

    def add(name, kind, properties, depends=None, condition=None, **extra):
        item = {"Type": kind, "Properties": properties, **extra}
        if depends:
            item["DependsOn"] = depends
        if condition:
            item["Condition"] = condition
        resources[name] = item

    add("NatAddress", "AWS::EC2::EIP", {"Domain": "vpc", "Tags": tags("northstar-nat-ip")})
    add("NatGateway", "AWS::EC2::NatGateway", {
        "AllocationId": att("NatAddress", "AllocationId"),
        "SubnetId": network("PublicSubnetA"), "ConnectivityType": "public",
        "Tags": tags("northstar-nat-a"),
    })
    add("AppDefaultRoute", "AWS::EC2::Route", {
        "RouteTableId": network("AppRouteTableId"),
        "DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": ref("NatGateway"),
    })
    # A gateway endpoint has no hourly charge and keeps ECR's S3 image layers
    # off the NAT path. ECR API, Secrets Manager and logs still use the NAT.
    add("S3Endpoint", "AWS::EC2::VPCEndpoint", {
        "VpcId": network("VpcId"), "VpcEndpointType": "Gateway",
        "ServiceName": sub("com.amazonaws.${AWS::Region}.s3"),
        "RouteTableIds": [network("AppRouteTableId")],
        "Tags": tags("northstar-s3-endpoint"),
    })
    # Explicit loopback-only egress suppresses EC2's implicit allow-all rule.
    for name, label in (("AlbSecurityGroup", "alb"), ("TaskSecurityGroup", "tasks"),
                        ("DatabaseSecurityGroup", "database")):
        add(name, "AWS::EC2::SecurityGroup", {
            "GroupDescription": "NorthStar " + label + " boundary",
            "VpcId": network("VpcId"), "Tags": tags("northstar-" + label + "-sg"),
            "SecurityGroupEgress": [{"IpProtocol": "-1", "CidrIp": "127.0.0.1/32"}],
        })
    add("CloudFrontToAlb", "AWS::EC2::SecurityGroupIngress", {
        "GroupId": ref("AlbSecurityGroup"), "IpProtocol": "tcp", "FromPort": 80,
        "ToPort": 80, "SourcePrefixListId": ref("CloudFrontPrefixList"),
        "Description": "HTTP origin access from CloudFront origin-facing addresses only",
    })
    add("AlbToTasksEgress", "AWS::EC2::SecurityGroupEgress", {
        "GroupId": ref("AlbSecurityGroup"), "IpProtocol": "tcp", "FromPort": 8080,
        "ToPort": 8080, "DestinationSecurityGroupId": ref("TaskSecurityGroup"),
    })
    add("AlbToTasksIngress", "AWS::EC2::SecurityGroupIngress", {
        "GroupId": ref("TaskSecurityGroup"), "IpProtocol": "tcp", "FromPort": 8080,
        "ToPort": 8080, "SourceSecurityGroupId": ref("AlbSecurityGroup"),
    })
    add("TaskHttpsEgress", "AWS::EC2::SecurityGroupEgress", {
        "GroupId": ref("TaskSecurityGroup"), "IpProtocol": "tcp", "FromPort": 443,
        "ToPort": 443, "CidrIp": "0.0.0.0/0", "Description": "AWS API and image access via NAT or S3 endpoint",
    })
    add("TasksToDatabaseEgress", "AWS::EC2::SecurityGroupEgress", {
        "GroupId": ref("TaskSecurityGroup"), "IpProtocol": "tcp", "FromPort": 5432,
        "ToPort": 5432, "DestinationSecurityGroupId": ref("DatabaseSecurityGroup"),
    })
    add("TasksToDatabaseIngress", "AWS::EC2::SecurityGroupIngress", {
        "GroupId": ref("DatabaseSecurityGroup"), "IpProtocol": "tcp", "FromPort": 5432,
        "ToPort": 5432, "SourceSecurityGroupId": ref("TaskSecurityGroup"),
    })
    for name, username in (("DatabaseOwnerSecret", "northstar_owner"),
                           ("ApplicationDatabaseSecret", "northstar_app"),
                           ("AdministratorSecret", ADMIN_EMAIL), ("OriginSecret", "origin")):
        add(name, "AWS::SecretsManager::Secret", {
            "Description": "NorthStar generated " + name,
            "GenerateSecretString": {"SecretStringTemplate": json.dumps({"username": username}),
                                     "GenerateStringKey": "password", "PasswordLength": 32,
                                     "ExcludePunctuation": True},
            "Tags": tags("northstar-" + name),
        })
    add("DatabaseSubnets", "AWS::RDS::DBSubnetGroup", {
        "DBSubnetGroupDescription": "NorthStar isolated database subnets in two AZs",
        "SubnetIds": [network("DbSubnetA"), network("DbSubnetB")],
        "Tags": tags("northstar-database-subnets"),
    })
    add("DatabaseParameters", "AWS::RDS::DBParameterGroup", {
        "Description": "NorthStar PostgreSQL 17: require encrypted database connections",
        "Family": "postgres17", "Parameters": {"rds.force_ssl": "1"},
        "Tags": tags("northstar-postgres-parameters"),
    })
    add("Database", "AWS::RDS::DBInstance", {
        "DBInstanceIdentifier": "northstar-db", "DBName": "northstar",
        "Engine": "postgres", "EngineVersion": ref("PostgresVersion"),
        "EngineLifecycleSupport": "open-source-rds-extended-support-disabled",
        "DBInstanceClass": "db.t4g.micro", "AllocatedStorage": "20", "StorageType": "gp3",
        "StorageEncrypted": True, "MultiAZ": False, "PubliclyAccessible": False,
        "MasterUsername": dynamic_secret("DatabaseOwnerSecret", "username"),
        "MasterUserPassword": dynamic_secret("DatabaseOwnerSecret", "password"),
        "DBSubnetGroupName": ref("DatabaseSubnets"),
        "DBParameterGroupName": ref("DatabaseParameters"),
        "VPCSecurityGroups": [ref("DatabaseSecurityGroup")],
        "Port": "5432", "BackupRetentionPeriod": 1, "DeleteAutomatedBackups": True,
        "AutoMinorVersionUpgrade": True, "DeletionProtection": False,
        "CopyTagsToSnapshot": True, "Tags": tags("northstar-db"),
    }, DeletionPolicy="Delete", UpdateReplacePolicy="Snapshot")
    for name, suffix in (("AppLogs", "app"), ("WebLogs", "web"), ("InitializationLogs", "initialize")):
        add(name, "AWS::Logs::LogGroup", {
            "LogGroupName": "/northstar/" + suffix, "RetentionInDays": 7,
            "Tags": tags("northstar-" + suffix + "-logs"),
        })

    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
             "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole",
             "Condition": {"StringEquals": {"aws:SourceAccount": ref("AWS::AccountId")},
                           "ArnLike": {"aws:SourceArn": sub("arn:${AWS::Partition}:ecs:${AWS::Region}:${AWS::AccountId}:*")}}}]}
    repositories = [sub("arn:${AWS::Partition}:ecr:${AWS::Region}:${AWS::AccountId}:repository/" + r)
                    for r in REPOSITORIES]
    for name, secrets, log_groups in (
        ("TaskExecutionRole", [ref("ApplicationDatabaseSecret")], ["AppLogs", "WebLogs"]),
        ("InitializationExecutionRole", [ref("DatabaseOwnerSecret"), ref("ApplicationDatabaseSecret"),
                                         ref("AdministratorSecret")], ["InitializationLogs"]),
    ):
        statements = [
            {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
            {"Effect": "Allow", "Action": ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer",
                                            "ecr:BatchGetImage"], "Resource": repositories},
            {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
             "Resource": [att(group, "Arn") for group in log_groups]},
            {"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": secrets},
        ]
        add(name, "AWS::IAM::Role", {
            "AssumeRolePolicyDocument": trust, "Tags": tags("northstar-" + name),
            "Policies": [{"PolicyName": "NorthStarContainerStart",
                          "PolicyDocument": {"Version": "2012-10-17", "Statement": statements}}],
        })
    add("Cluster", "AWS::ECS::Cluster", {
        "ClusterName": "northstar-cluster", "ClusterSettings": [{"Name": "containerInsights", "Value": "disabled"}],
        "Tags": tags("northstar-cluster"),
    })

    def logging(group, prefix):
        return {"LogDriver": "awslogs", "Options": {
            "awslogs-group": ref(group), "awslogs-region": ref("AWS::Region"),
            "awslogs-stream-prefix": prefix, "mode": "non-blocking", "max-buffer-size": "1m",
        }}

    def env(values):
        return [{"Name": k, "Value": v} for k, v in values.items()]

    common_env = {"NORTHSTAR_DB_HOST": att("Database", "Endpoint.Address"),
                  "NORTHSTAR_DB_NAME": "northstar", "NORTHSTAR_DB_PORT": "5432",
                  "NORTHSTAR_DB_SSLMODE": "verify-full", "NORTHSTAR_AUTO_INIT": "0",
                  "NORTHSTAR_SEED_DEMO": "0"}

    def task_properties(role, containers, family):
        return {"Family": family, "Cpu": "256", "Memory": "512", "NetworkMode": "awsvpc",
                "RequiresCompatibilities": ["FARGATE"], "ExecutionRoleArn": att(role, "Arn"),
                "RuntimePlatform": {"CpuArchitecture": "X86_64", "OperatingSystemFamily": "LINUX"},
                "ContainerDefinitions": containers, "Tags": tags(family)}

    app_secrets = [{"Name": "NORTHSTAR_DB_" + key.upper(),
                    "ValueFrom": secret_value("ApplicationDatabaseSecret", source)}
                   for key, source in (("user", "username"), ("password", "password"))]
    app = {"Name": "app", "Image": ref("AppImage"), "Essential": True,
           "MemoryReservation": 256, "PortMappings": [{"ContainerPort": 8000, "Protocol": "tcp"}],
           "Environment": env({**common_env, "NORTHSTAR_TRUST_PROXY": "1", "NORTHSTAR_SECURE_COOKIE": "1"}),
           "Secrets": app_secrets, "LogConfiguration": logging("AppLogs", "app"),
           "HealthCheck": {"Command": ["CMD", "python", "-c",
               "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"],
               "Interval": 30, "Timeout": 5, "Retries": 3, "StartPeriod": 60}}
    web = {"Name": "web", "Image": ref("WebImage"), "Essential": True, "MemoryReservation": 64,
           "PortMappings": [{"ContainerPort": 8080, "Protocol": "tcp"}],
           "DependsOn": [{"ContainerName": "app", "Condition": "HEALTHY"}],
           "Environment": env({"APP_UPSTREAM": "127.0.0.1:8000", "TRUSTED_PROXY_CIDR": "10.42.0.0/16",
                               "CLIENT_IP_HEADER": "CloudFront-Viewer-Address"}),
           "LogConfiguration": logging("WebLogs", "web"),
           "HealthCheck": {"Command": ["CMD-SHELL", "wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1"],
                           "Interval": 30, "Timeout": 5, "Retries": 3, "StartPeriod": 90}}
    add("ApplicationTask", "AWS::ECS::TaskDefinition", task_properties("TaskExecutionRole", [app, web], FAMILY))
    initialization = {"Name": "initialize", "Image": ref("AppImage"), "Essential": True,
        "Command": ["python", "-c", initialization_code()],
        "Environment": env({**common_env, "NORTHSTAR_ADMIN_EMAIL": ADMIN_EMAIL}),
        "Secrets": [
            {"Name": "NORTHSTAR_DB_USER", "ValueFrom": secret_value("DatabaseOwnerSecret", "username")},
            {"Name": "NORTHSTAR_DB_PASSWORD", "ValueFrom": secret_value("DatabaseOwnerSecret", "password")},
            {"Name": "APP_DB_USER", "ValueFrom": secret_value("ApplicationDatabaseSecret", "username")},
            {"Name": "APP_DB_PASSWORD", "ValueFrom": secret_value("ApplicationDatabaseSecret", "password")},
            {"Name": "NORTHSTAR_ADMIN_PASSWORD", "ValueFrom": secret_value("AdministratorSecret", "password")},
        ], "LogConfiguration": logging("InitializationLogs", "init")}
    add("InitializationTask", "AWS::ECS::TaskDefinition",
        task_properties("InitializationExecutionRole", [initialization], "northstar-initialize"))
    add("LoadBalancer", "AWS::ElasticLoadBalancingV2::LoadBalancer", {
        "Name": "northstar-alb", "Type": "application", "Scheme": "internet-facing", "IpAddressType": "ipv4",
        "Subnets": [network("PublicSubnetA"), network("PublicSubnetB")],
        "SecurityGroups": [ref("AlbSecurityGroup")], "Tags": tags("northstar-alb"),
        "LoadBalancerAttributes": [{"Key": "routing.http.drop_invalid_header_fields.enabled", "Value": "true"}],
    })
    add("TargetGroup", "AWS::ElasticLoadBalancingV2::TargetGroup", {
        "Name": "northstar-targets", "VpcId": network("VpcId"), "TargetType": "ip",
        "Port": 8080, "Protocol": "HTTP", "HealthCheckPath": "/healthz", "HealthCheckProtocol": "HTTP",
        "HealthCheckIntervalSeconds": 30, "HealthCheckTimeoutSeconds": 5,
        "HealthyThresholdCount": 2, "UnhealthyThresholdCount": 3, "Matcher": {"HttpCode": "200"},
        "TargetGroupAttributes": [{"Key": "deregistration_delay.timeout_seconds", "Value": "30"}],
        "Tags": tags("northstar-targets"),
    })
    add("Listener", "AWS::ElasticLoadBalancingV2::Listener", {
        "LoadBalancerArn": ref("LoadBalancer"), "Port": 80, "Protocol": "HTTP",
        "DefaultActions": [{"Type": "fixed-response", "FixedResponseConfig": {
            "StatusCode": "403", "ContentType": "text/plain", "MessageBody": "Use the NorthStar HTTPS application URL."}}],
    })
    add("OriginRule", "AWS::ElasticLoadBalancingV2::ListenerRule", {
        "ListenerArn": ref("Listener"), "Priority": 1,
        "Conditions": [{"Field": "http-header", "HttpHeaderConfig": {"HttpHeaderName": "X-NorthStar-Origin",
                        "Values": [dynamic_secret("OriginSecret", "password")]}}],
        "Actions": [{"Type": "forward", "TargetGroupArn": ref("TargetGroup")}],
    })
    add("CachePolicy", "AWS::CloudFront::CachePolicy", {"CachePolicyConfig": {
        "Name": sub("${AWS::StackName}-no-cache"), "DefaultTTL": 0, "MinTTL": 0, "MaxTTL": 0,
        "ParametersInCacheKeyAndForwardedToOrigin": {
            "CookiesConfig": {"CookieBehavior": "none"}, "HeadersConfig": {"HeaderBehavior": "none"},
            "QueryStringsConfig": {"QueryStringBehavior": "none"},
            "EnableAcceptEncodingGzip": False, "EnableAcceptEncodingBrotli": False},
    }})
    add("OriginRequestPolicy", "AWS::CloudFront::OriginRequestPolicy", {"OriginRequestPolicyConfig": {
        "Name": sub("${AWS::StackName}-session-and-viewer"), "CookiesConfig": {"CookieBehavior": "all"},
        "QueryStringsConfig": {"QueryStringBehavior": "all"},
        "HeadersConfig": {"HeaderBehavior": "allViewerAndWhitelistCloudFront",
                          "Headers": ["CloudFront-Viewer-Address"]},
    }})
    add("Distribution", "AWS::CloudFront::Distribution", {
        "DistributionConfig": {
            "Enabled": True, "Comment": "NorthStar HTTPS coursework application",
            "PriceClass": "PriceClass_100", "HttpVersion": "http2", "IPV6Enabled": True,
            "Origins": [{"Id": "northstar-alb", "DomainName": att("LoadBalancer", "DNSName"),
                "CustomOriginConfig": {"OriginProtocolPolicy": "http-only", "HTTPPort": 80},
                "OriginCustomHeaders": [{"HeaderName": "X-NorthStar-Origin",
                                        "HeaderValue": dynamic_secret("OriginSecret", "password")}]}],
            "DefaultCacheBehavior": {"TargetOriginId": "northstar-alb", "ViewerProtocolPolicy": "redirect-to-https",
                "AllowedMethods": ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"],
                "CachedMethods": ["GET", "HEAD"], "Compress": True,
                "CachePolicyId": ref("CachePolicy"), "OriginRequestPolicyId": ref("OriginRequestPolicy")},
            "CustomErrorResponses": [{"ErrorCode": code, "ErrorCachingMinTTL": 0}
                                     for code in (403, 404, 500, 502, 503, 504)],
            "ViewerCertificate": {"CloudFrontDefaultCertificate": True},
        }, "Tags": tags("northstar-https"),
    }, depends="OriginRule")
    add("Service", "AWS::ECS::Service", {
        "ServiceName": "northstar-service", "Cluster": ref("Cluster"), "LaunchType": "FARGATE",
        "PlatformVersion": "1.4.0", "TaskDefinition": ref("ApplicationTask"),
        "DesiredCount": {"Fn::If": ["ApplicationEnabled", 2, 0]},
        "AvailabilityZoneRebalancing": "ENABLED", "EnableECSManagedTags": True, "PropagateTags": "SERVICE",
        "DeploymentConfiguration": {"MinimumHealthyPercent": 100, "MaximumPercent": 200,
                                    "DeploymentCircuitBreaker": {"Enable": True, "Rollback": True}},
        "HealthCheckGracePeriodSeconds": 150,
        "NetworkConfiguration": {"AwsvpcConfiguration": {"AssignPublicIp": "DISABLED",
            "Subnets": [network("AppSubnetA"), network("AppSubnetB")], "SecurityGroups": [ref("TaskSecurityGroup")]}},
        "LoadBalancers": [{"TargetGroupArn": ref("TargetGroup"), "ContainerName": "web", "ContainerPort": 8080}],
        "Tags": tags("northstar-service"),
    }, depends=["OriginRule", "AppDefaultRoute", "S3Endpoint", "AlbToTasksEgress", "AlbToTasksIngress",
                "TaskHttpsEgress", "TasksToDatabaseEgress", "TasksToDatabaseIngress"])
    add("ScalingTarget", "AWS::ApplicationAutoScaling::ScalableTarget", {
        "MaxCapacity": 3, "MinCapacity": 2, "ResourceId": sub("service/${Cluster}/${Service.Name}"),
        "ScalableDimension": "ecs:service:DesiredCount", "ServiceNamespace": "ecs",
    }, condition="ApplicationEnabled")
    add("CpuScaling", "AWS::ApplicationAutoScaling::ScalingPolicy", {
        "PolicyName": "northstar-cpu-target", "PolicyType": "TargetTrackingScaling",
        "ScalingTargetId": ref("ScalingTarget"), "TargetTrackingScalingPolicyConfiguration": {
            "TargetValue": 65.0, "ScaleInCooldown": 180, "ScaleOutCooldown": 60,
            "PredefinedMetricSpecification": {"PredefinedMetricType": "ECSServiceAverageCPUUtilization"}},
    }, condition="ApplicationEnabled")
    outputs = {
        "ECSCluster": ref("Cluster"), "ECSService": att("Service", "Name"),
        "ServiceArn": ref("Service"), "ApplicationUrl": sub("https://${Distribution.DomainName}"),
        "DistributionId": ref("Distribution"), "TaskSecurityGroup": ref("TaskSecurityGroup"),
        "DatabaseIdentifier": ref("Database"), "DatabaseEndpoint": att("Database", "Endpoint.Address"),
        "InitializationTaskDefinition": ref("InitializationTask"),
        "TaskExecutionRoleArn": att("TaskExecutionRole", "Arn"),
        "AdministratorSecretArn": ref("AdministratorSecret"), "LoadBalancerArn": ref("LoadBalancer"),
        "TargetGroupArn": ref("TargetGroup"),
    }
    return {"AWSTemplateFormatVersion": "2010-09-09", "Description": "NorthStar private container and database hosting",
        "Parameters": {
            "AppImage": {"Type": "String"}, "WebImage": {"Type": "String"},
            "PostgresVersion": {"Type": "String", "AllowedPattern": "17\\.[0-9]+"},
            "CloudFrontPrefixList": {"Type": "String", "AllowedPattern": "pl-[a-f0-9]+"},
            "EnableApplication": {"Type": "String", "Default": "false", "AllowedValues": ["true", "false"]},
        }, "Conditions": {"ApplicationEnabled": {"Fn::Equals": [ref("EnableApplication"), "true"]}},
        "Resources": resources, "Outputs": {k: {"Value": v} for k, v in outputs.items()}}


def stack_or_none(cfn, name):
    from botocore.exceptions import ClientError
    try:
        return cfn.describe_stacks(StackName=name)["Stacks"][0]
    except ClientError as exc:
        error = exc.response["Error"]
        if error["Code"] == "ValidationError" and "does not exist" in error["Message"]:
            return None
        raise


def outputs(stack):
    return {v["OutputKey"]: v["OutputValue"] for v in stack.get("Outputs", [])}


def owned(stack):
    if {t["Key"]: t["Value"] for t in stack.get("Tags", [])}.get("Project") != PROJECT:
        raise RuntimeError("Stop: the stack name belongs to a different project.")


def wait_stack(cfn, stack_name, operation):
    deadline = time.monotonic() + 3600
    last = None
    while time.monotonic() < deadline:
        stack = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
        state = stack["StackStatus"]
        if state != last:
            print(datetime.now(timezone.utc).strftime("%H:%M:%S UTC"), stack_name, state, flush=True)
            last = state
        if state == operation + "_COMPLETE":
            return stack
        if not state.endswith("_IN_PROGRESS"):
            events = cfn.describe_stack_events(StackName=stack_name)["StackEvents"]
            for event in events[:30]:
                if event["ResourceStatus"].endswith("FAILED"):
                    print(event["LogicalResourceId"], event.get("ResourceStatusReason", ""), flush=True)
            raise RuntimeError("CloudFormation stopped at " + state + ". Do not delete the stack; share the failure text.")
        time.sleep(15)
    raise RuntimeError("Timed out waiting. The stack may still be running; check CloudFormation before retrying.")


def select_images(ecr, requested=None):
    registries = []
    for repository in REPOSITORIES:
        images = {}
        for page in ecr.get_paginator("describe_images").paginate(repositoryName=repository):
            for image in page["imageDetails"]:
                for tag in image.get("imageTags", []):
                    if re.fullmatch(r"[0-9a-f]{40}-[0-9]+-[0-9]+", tag):
                        images[tag] = (image["imagePushedAt"], image["imageDigest"])
        registries.append(images)
    common = registries[0].keys() & registries[1].keys()
    if requested and requested not in common:
        raise RuntimeError("The requested CI image tag is not present in both ECR repositories.")
    if not common:
        raise RuntimeError("Both tested ECR images must be published successfully before provisioning.")
    tag = requested or max(common, key=lambda v: min(r[v][0] for r in registries))
    registry = ACCOUNT + ".dkr.ecr." + REGION + ".amazonaws.com/"
    # Pin initial task images to digests as well as retaining the shared CI tag.
    return {"tag": tag, "revision": tag.split("-")[0],
            "app_image": registry + REPOSITORIES[0] + "@" + registries[0][tag][1],
            "web_image": registry + REPOSITORIES[1] + "@" + registries[1][tag][1]}


def postgres_version(rds):
    versions = [v["EngineVersion"] for page in rds.get_paginator("describe_db_engine_versions").paginate(Engine="postgres")
                for v in page["DBEngineVersions"] if re.fullmatch(r"17\.[0-9]+", v["EngineVersion"])]
    for version in sorted(versions, key=lambda v: tuple(map(int, v.split("."))), reverse=True):
        for page in rds.get_paginator("describe_orderable_db_instance_options").paginate(
                Engine="postgres", EngineVersion=version, DBInstanceClass="db.t4g.micro", Vpc=True):
            if any(v.get("StorageType") == "gp3" and v.get("SupportsStorageEncryption")
                   for v in page["OrderableDBInstanceOptions"]):
                return version
    raise RuntimeError("No supported PostgreSQL 17/gp3 db.t4g.micro option found in Stockholm.")


def image_revision(ecr, image):
    """Resolve the original tested revision even when initial images use digests."""
    repository = image.rsplit("/", 1)[-1]
    if "@" in repository:
        name, digest = repository.split("@", 1)
        details = ecr.describe_images(repositoryName=name, imageIds=[{"imageDigest": digest}])["imageDetails"]
        revisions = {tag.split("-")[0] for item in details for tag in item.get("imageTags", [])
                     if re.fullmatch(r"[0-9a-f]{40}-[0-9]+-[0-9]+", tag)}
        if len(revisions) != 1:
            raise RuntimeError("The initial image's tested source revision cannot be identified uniquely.")
        return revisions.pop()
    tag = repository.split(":", 1)[-1]
    if not re.fullmatch(r"[0-9a-f]{40}-[0-9]+-[0-9]+", tag):
        raise RuntimeError("The initial image does not have a recognized tested source tag.")
    return tag.split("-")[0]


def show_costs():
    # Planning allowances, not a quote or a spending limit. See infra/README.md.
    deadline = datetime.fromisoformat("2026-11-20T23:59:59+05:00")
    hours = max(0, math.ceil((deadline - datetime.now(timezone.utc)).total_seconds() / 3600))
    hours = hours or 480
    hourly = 2 * (0.25 * 0.0445 + 0.5 * 0.0049) + 0.016 + 0.02394 + 3 * 0.005
    baseline = hours * hourly + 20 * 0.12 * hours / 730
    allowance = hours * (0.060 + 0.0076) + 12  # NAT hourly allowance, one average LCU, other usage.
    print("COST PLAN (USD, credits excluded; approximate, low traffic):", flush=True)
    print(f"  Through 20 November 2026, 23:59 Pakistan time: about {hours} hours.")
    print(f"  Two tasks + small RDS + storage + ALB + three public IPv4 addresses: ${baseline:.2f}.")
    print(f"  With NAT, one average ALB LCU and a $12 allowance for other usage: about ${baseline + allowance:.2f}.")
    print("  Plan around $75-$95 for roughly 20 days; this is not a bill cap or a credit guarantee.")
    print("  More traffic, scaling, logs, transfer, or keeping resources longer increases usage.")
    print("  Existing unrelated resources and earlier charges are not included. Keep the Free Plan.")


def initialize(ecs, logs, folder, config, stack_outputs, net):
    marker = folder / "initialization-task.json"
    task_arn = None
    if marker.exists():
        previous = json.loads(marker.read_text())
        if previous.get("stack_id") == config["stack_id"]:
            task_arn = previous["task_arn"]
    if task_arn:
        result = ecs.describe_tasks(cluster=stack_outputs["ECSCluster"], tasks=[task_arn])
        if not result.get("tasks"):
            task_arn = None  # ECS removes old stopped tasks; initialization is idempotent.
    if not task_arn:
        result = ecs.run_task(cluster=stack_outputs["ECSCluster"], launchType="FARGATE", platformVersion="1.4.0",
            taskDefinition=stack_outputs["InitializationTaskDefinition"], count=1,
            startedBy="northstar-setup", networkConfiguration={"awsvpcConfiguration": {
                "subnets": [net["AppSubnetA"], net["AppSubnetB"]],
                "securityGroups": [stack_outputs["TaskSecurityGroup"]], "assignPublicIp": "DISABLED"}})
        if result.get("failures") or not result.get("tasks"):
            raise RuntimeError("Initialization task could not start: " + json.dumps(result.get("failures", [])))
        task_arn = result["tasks"][0]["taskArn"]
        marker.write_text(json.dumps({"task_arn": task_arn, "stack_id": config["stack_id"]}, indent=2))
    print("Initializing database in a temporary private container...", flush=True)
    last = None
    for _ in range(120):
        task = ecs.describe_tasks(cluster=stack_outputs["ECSCluster"], tasks=[task_arn])["tasks"][0]
        if task["lastStatus"] != last:
            print("Initialization:", task["lastStatus"], flush=True)
            last = task["lastStatus"]
        if last == "STOPPED":
            container = next((c for c in task.get("containers", []) if c["name"] == "initialize"), {})
            if container.get("exitCode") == 0:
                print("INITIALIZATION_COMPLETE", flush=True)
                return
            stream = "init/initialize/" + task_arn.rsplit("/", 1)[-1]
            try:
                events = logs.get_log_events(logGroupName="/northstar/initialize", logStreamName=stream,
                                             limit=15)["events"]
                for event in events:
                    print(event["message"])
            except logs.exceptions.ResourceNotFoundException:
                pass
            marker.unlink(missing_ok=True)  # A later explicit rerun may retry a failed initialization.
            raise RuntimeError("Initialization failed: " + task.get("stoppedReason", "see CloudWatch logs"))
        time.sleep(10)
    raise RuntimeError("Initialization is taking longer than expected. Re-run --deploy to resume checking the same task.")


def verify_application(ecs, elb, result, expected_revision):
    cluster, service_name = result["ECSCluster"], result["ECSService"]
    print("Waiting for two healthy application tasks...", flush=True)
    for attempt in range(120):
        service = ecs.describe_services(cluster=cluster, services=[service_name])["services"][0]
        targets = elb.describe_target_health(TargetGroupArn=result["TargetGroupArn"])["TargetHealthDescriptions"]
        healthy = sum(t["TargetHealth"]["State"] == "healthy" for t in targets)
        if attempt % 6 == 0:
            print(f"Running tasks: {service['runningCount']}; healthy load-balancer targets: {healthy}", flush=True)
        if service["runningCount"] >= 2 and healthy >= 2:
            break
        if attempt == 119:
            print(json.dumps(service.get("events", [])[:3], indent=2, default=str))
            raise RuntimeError("Two healthy application targets were not reached. Share the service event text.")
        time.sleep(10)
    url = result["ApplicationUrl"]
    for attempt in range(36):
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=20) as response:
                health = json.load(response)
            if health.get("status") != "ok" or (expected_revision and health.get("revision") != expected_revision):
                raise ValueError("Health response does not match the expected deployment.")
            with urllib.request.urlopen(url + "/", timeout=20) as response:
                if b"NORTHSTAR" not in response.read():
                    raise ValueError("The expected home page was not returned.")
            with urllib.request.urlopen(url + "/api/products?q=HALO", timeout=20) as response:
                products = json.load(response)
            if not any(p["slug"] == "halo-desk-lamp" for p in products.get("products", [])):
                raise ValueError("The database catalogue check failed.")
            tasks = ecs.list_tasks(cluster=cluster, serviceName=service_name)["taskArns"]
            zones = sorted({t.get("availabilityZone", "unknown") for t in
                            ecs.describe_tasks(cluster=cluster, tasks=tasks)["tasks"]})
            print("HTTPS_CHECKS_PASSED: health, revision, website, catalogue.", flush=True)
            print("Running task availability zones:", ", ".join(zones), flush=True)
            return {"checked_at": datetime.now(timezone.utc).isoformat(), "application_url": url,
                    "build_revision": health.get("revision"), "healthy_targets": healthy,
                    "running_tasks": service["runningCount"], "availability_zones": zones}
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            if attempt == 35:
                raise RuntimeError("HTTPS verification failed; inspect CloudFront and target health.") from exc
            time.sleep(10)


def grant_ci(iam, result):
    role = iam.get_role(RoleName=GITHUB_ROLE)["Role"]
    if {t["Key"]: t["Value"] for t in role.get("Tags", [])}.get("Project") != PROJECT:
        raise RuntimeError("The GitHub role is not tagged for this project; leaving IAM unchanged.")
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["ecs:DescribeServices", "ecs:UpdateService"], "Resource": result["ServiceArn"]},
        {"Effect": "Allow", "Action": "ecs:RegisterTaskDefinition",
         "Resource": f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{FAMILY}:*"},
        {"Effect": "Allow", "Action": "ecs:DescribeTaskDefinition", "Resource": "*"},
        {"Effect": "Allow", "Action": "iam:PassRole", "Resource": result["TaskExecutionRoleArn"],
         "Condition": {"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}}},
    ]}
    iam.put_role_policy(RoleName=GITHUB_ROLE, PolicyName="NorthStarECSDeploy", PolicyDocument=json.dumps(policy))
    return policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="Read-only AWS checks; write the proposed template locally")
    mode.add_argument("--deploy", action="store_true", help="Create billable hosting services, initialize and start the application")
    mode.add_argument("--template", action="store_true", help="Print the template without contacting AWS")
    parser.add_argument("--image-tag", help="Use this shared CI tag instead of the newest matching app/web pair")
    args = parser.parse_args()
    template = build_template()
    if args.template:
        print(json.dumps(template, indent=2))
        return
    import boto3
    if boto3.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        raise RuntimeError("Stop: CloudShell is signed into a different AWS account.")
    clients = {s: boto3.client(s, region_name=REGION) for s in ("cloudformation", "ec2", "ecr", "ecs", "rds", "logs", "elbv2", "iam")}
    cfn = clients["cloudformation"]
    net_stack = stack_or_none(cfn, NETWORK)
    if not net_stack or net_stack["StackStatus"] not in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
        raise RuntimeError("The NorthStar network stack must be complete first.")
    owned(net_stack)
    net = outputs(net_stack)
    if net.get("VpcId") != EXPECTED_VPC:
        raise RuntimeError("Stop: the network is not the VPC already created for this project.")
    existing = stack_or_none(cfn, STACK)
    if existing:
        owned(existing)
        if existing["StackStatus"].endswith("_IN_PROGRESS"):
            operation = "CREATE" if existing["StackStatus"] == "CREATE_IN_PROGRESS" else "UPDATE"
            existing = wait_stack(cfn, STACK, operation)
        if existing["StackStatus"] not in ("CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"):
            raise RuntimeError("The services stack is " + existing["StackStatus"] + "; inspect it before attempting changes.")
    images = select_images(clients["ecr"], args.image_tag)
    prefixes = clients["ec2"].describe_managed_prefix_lists(Filters=[{
        "Name": "prefix-list-name", "Values": ["com.amazonaws.global.cloudfront.origin-facing"]}])["PrefixLists"]
    if len(prefixes) != 1:
        raise RuntimeError("The CloudFront origin-facing managed prefix list was not found.")
    # A CloudFront prefix-list rule has weight 55; a new SG's default quota is 60.
    version = postgres_version(clients["rds"])
    folder = Path.home() / "northstar-setup"
    folder.mkdir(exist_ok=True)
    body = json.dumps(template, indent=2)
    if len(body.encode()) > 51200:
        raise RuntimeError("CloudFormation inline template exceeds the API size limit.")
    cfn.validate_template(TemplateBody=body)
    (folder / "services-template.json").write_text(body)
    parameters = {"AppImage": images["app_image"], "WebImage": images["web_image"],
                  "PostgresVersion": version, "CloudFrontPrefixList": prefixes[0]["PrefixListId"],
                  "EnableApplication": "false"}
    print("Region:", REGION, "| VPC:", EXPECTED_VPC, "| PostgreSQL:", version, flush=True)
    print("Matched tested image tag:", images["tag"], flush=True)
    show_costs()
    print("Known limits: Single-AZ database, one NAT gateway, shared web/app task; CloudFront-to-ALB uses HTTP.")
    print("CloudFront viewer access and database connections use TLS. No domain purchase is needed.")
    print("Template saved:", folder / "services-template.json", flush=True)
    if args.plan:
        print("PLAN_ONLY: No AWS resources were created or changed.", flush=True)
        return
    if not existing:
        print("Creating hosting services. This normally takes about 15-25 minutes. Keep CloudShell open.", flush=True)
        cfn.create_stack(StackName=STACK, TemplateBody=body,
            Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
            Capabilities=["CAPABILITY_IAM"], TimeoutInMinutes=60, Tags=[{"Key": "Project", "Value": PROJECT}])
        existing = wait_stack(cfn, STACK, "CREATE")
    # Never replace an existing stack template, database, credentials or images on
    # a retry. GitHub owns subsequent task revisions once the service is enabled.
    current_parameters = {p["ParameterKey"]: p["ParameterValue"] for p in existing["Parameters"]}
    result = outputs(existing)
    config = {"stack_id": existing["StackId"], "region": REGION, "vpc_id": EXPECTED_VPC}
    if current_parameters["EnableApplication"] != "true":
        initialize(clients["ecs"], clients["logs"], folder, config, result, net)
        cfn.update_stack(StackName=STACK, UsePreviousTemplate=True, Capabilities=["CAPABILITY_IAM"],
            Parameters=[{"ParameterKey": k, "ParameterValue": "true"} if k == "EnableApplication"
                        else {"ParameterKey": k, "UsePreviousValue": True} for k in current_parameters])
        existing = wait_stack(cfn, STACK, "UPDATE")
        result = outputs(existing)
        # The initial images may predate the most recent ECR publish on a retry.
        expected_revision = image_revision(clients["ecr"], current_parameters["AppImage"])
    else:
        expected_revision = ""  # A successful GitHub deployment may have advanced it.
    verification = verify_application(clients["ecs"], clients["elbv2"], result, expected_revision)
    policy = grant_ci(clients["iam"], result)
    for filename, value in (("services-outputs.json", result), ("ecs-deploy-policy.json", policy),
                            ("initial-deployment-checks.json", verification)):
        (folder / filename).write_text(json.dumps(value, indent=2))
    print("\nHOSTING_READY", flush=True)
    print("Application:", result["ApplicationUrl"])
    print("Add these three GitHub Actions repository VARIABLES:")
    print("ECS_CLUSTER =", result["ECSCluster"])
    print("ECS_SERVICE =", result["ECSService"])
    print("APPLICATION_URL =", result["ApplicationUrl"])
    print("Administrator email:", ADMIN_EMAIL)
    print("Administrator password remains in Secrets Manager; it was not printed or committed.")
    print("Administrator secret ARN:", result["AdministratorSecretArn"])
    print("The next push to main must demonstrate a successful automated AWS deployment for the report.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped waiting locally. AWS operations may continue; re-run --deploy to resume checking.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print("SETUP_STOPPED:", exc, file=sys.stderr)
        raise SystemExit(1)
