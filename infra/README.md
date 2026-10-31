# NorthStar AWS hosting

This setup runs in **AWS CloudShell**, account `397620884269`, region
`eu-north-1`. Docker Desktop is not required. GitHub Actions builds and tests the
images; CloudShell provisions AWS services and starts the initial deployment.

The existing `northstar-network` stack must be complete. Its source is retained
in `network-template.json`. Its VPC is
`vpc-084c18c9f25155f2f`. The account and VPC checks intentionally stop this
assignment's script from modifying a different environment. Edit the constants
when deliberately reusing the source in a new account.

## Resources and connectivity

| Component | Configuration and purpose |
| --- | --- |
| Existing VPC | `10.42.0.0/16`; two public, two private application and two isolated database subnets across two AZs |
| NAT | One public NAT gateway and one Elastic IP in public subnet A; only the application route table gains an internet route |
| S3 gateway endpoint | Application route table; ECR image-layer downloads use the S3 endpoint rather than NAT |
| Application Load Balancer | Public subnets A/B; IP target group on port 8080; `/healthz` checks database readiness |
| CloudFront | AWS-provided HTTPS address, HTTP-to-HTTPS redirect, no caching, all session cookies/query strings forwarded |
| Container compute | Two ECS Fargate tasks, each 0.25 vCPU/0.5 GiB; each task contains Nginx and Gunicorn/Python; private application subnets, no public task IPs |
| Autoscaling | CPU target 65%; minimum two, maximum three tasks; rolling deployments can temporarily create extra tasks |
| Database | RDS PostgreSQL 17, `db.t4g.micro`, Single-AZ, 20 GiB encrypted gp3, one day of automated backups, no public access |
| Secrets Manager | Generated owner database, limited application database, initial administrator, and origin-header credentials |
| CloudWatch Logs | Separate application, web and initialization log groups, seven-day retention |
| IAM | Separate initialization/container execution roles; GitHub uses its existing OIDC role and receives only service/task deployment permissions |

CloudFormation exports from `northstar-network` are imported by the new
`northstar-services` stack. Delete the services stack first when eventually
removing the project. This script does **not** delete stacks or old resources.

## Review and run

First commit these files and the Nginx/workflow adjustments to `main`. Wait for
the existing workflow to publish both new images successfully. Keep
`ECS_CLUSTER`, `ECS_SERVICE` and `APPLICATION_URL` unset until initial hosting is
ready. The publishing-only summary at this stage is expected.

Download the script into the existing CloudShell setup folder:

```bash
curl --fail --location https://raw.githubusercontent.com/furqan-20/northstar-cloud/main/infra/provision.py -o ~/northstar-setup/provision.py
python3 ~/northstar-setup/provision.py --plan
```

`--plan` reads AWS state and saves the proposed template to
`~/northstar-setup/services-template.json`; it does not create or change AWS
resources. It validates the template with AWS before reporting `PLAN_ONLY`.

After reviewing the plan:

```bash
python3 ~/northstar-setup/provision.py --deploy
```

`--deploy` creates **billable services**. It uses the newest matching CI tag
present in both ECR repositories and pins initial images to their digests. To
choose a particular successful run, add `--image-tag FULL_SHARED_CI_TAG`.

The script creates the service with zero running tasks, starts a temporary
private initialization task, creates the schema/catalogue/administrator and
limited database role, then enables two application tasks and autoscaling.
It checks two healthy ALB targets and verifies the HTTPS health endpoint,
expected source revision, home page and database-backed catalogue before
printing `HOSTING_READY`. Provisioning commonly takes 15–25 minutes; cloud
service timing and account quotas can make it longer.

Leave CloudShell open while it runs. If disconnected, re-run `--deploy` after
reconnecting. It waits for an existing operation, reuses the existing stack,
and preserves an already enabled service's image revision and task count.
Initialization is idempotent. A stack failure is reported and left for review;
the script does not silently delete the database or rebuild a failed stack.

Generated templates, non-secret stack outputs, the initialization task ARN,
deployment policy, and actual initial deployment check results are saved under
`~/northstar-setup/`. Secret **values** are neither printed nor saved there.

## Finish automatic deployment

The script prints these three **repository variables**, with their actual values:

| GitHub Actions variable | Source |
| --- | --- |
| `ECS_CLUSTER` | ECS cluster name |
| `ECS_SERVICE` | ECS service name |
| `APPLICATION_URL` | CloudFront HTTPS URL |

Add them in repository **Settings → Secrets and variables → Actions → Variables**.
Keep the existing `AWS_ROLE_ARN` and `AWS_REGION`. The script adds the
`NorthStarECSDeploy` inline policy to the existing project-tagged GitHub role;
it does not replace its OIDC trust or ECR push policy.

Push a small source/documentation change to `main`. The workflow must build,
test, publish, deploy the new task definition, and check the live URL. Only that
successful **AWS deployment** run is the final CI/CD report evidence. A green
publishing-only run is not deployment evidence.

The initial administrator email is `admin@northstar.example`. Its generated
password remains in the Secrets Manager secret whose ARN is printed at the end.
Retrieve it in the AWS console only when needed; do not copy it into GitHub,
the report, screenshots or chat. The demonstration is not a payment service.

## Cost plan through 20 November 2026

These are planning assumptions, **not a quote, hard spending cap, or guarantee
that credits will last**. An illustrative 480-hour / roughly 20-day deployment
has the following estimated usage before credits:

| Item | Planning rate or allowance | Approximate 480-hour cost (USD) |
| --- | --- | ---: |
| Two Linux x86 Fargate tasks | Each 0.25 × $0.0445/vCPU-hour + 0.5 × $0.0049/GB-hour | 13.03 |
| RDS `db.t4g.micro` PostgreSQL | $0.016/hour | 7.68 |
| RDS storage, 20 GiB gp3 | $0.12/GiB-month; illustrative 730-hour month | 1.58 |
| ALB | $0.02394/hour | 11.49 |
| ALB usage allowance | One average LCU × $0.0076/hour | 3.65 |
| Three public IPv4 addresses | At least two ALB addresses and one NAT address; $0.005/address-hour | 7.20 |
| NAT gateway hourly allowance | **$0.060/hour planning allowance**, not a verified Stockholm NAT price | 28.80 |
| Other usage allowance | NAT processing, ECR, Secrets Manager, CloudFront, logs, CPU credits, cross-AZ/other transfer | 12.00 |
| **Illustrative total** | | **85.43** |

Reserve approximately **$75–$95** for low traffic through the evaluation. The
script recalculates hours to 20 November, 23:59 Pakistan time. The latest stated
credit balance was **$123.73**, but actual remaining credit and continuing usage
must be checked in Billing. Budget alerts do not stop resources. Existing
unrelated resources and previous charges are excluded from this estimate.
Three tasks sustained for the entire period would add roughly $6.52 in Fargate
compute, with other usage depending on traffic. More requests, ALB capacity,
NAT processing, storage, logs, deployments or retained resources can increase
costs. After the evaluation, remove the resources that day to end ongoing usage.

Rates were checked on 31 October 2026 against AWS's public regional price
catalogs for [Amazon ECS](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECS/current/eu-north-1/index.json),
[Amazon RDS](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/eu-north-1/index.json),
[Elastic Load Balancing](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSELB/current/eu-north-1/index.json),
and [Amazon VPC](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonVPC/current/eu-north-1/index.json).
See also [NAT/IP pricing](https://aws.amazon.com/vpc/pricing/),
[CloudFront pricing](https://aws.amazon.com/cloudfront/pricing/), and
[Secrets Manager pricing](https://aws.amazon.com/secrets-manager/pricing/).
The NAT hourly number above is deliberately an allowance. CloudFront uses
standard distribution billing; the script does not subscribe to a flat-rate plan,
purchase a domain, or upgrade the AWS account.

## Security and known NFR limitations

- The ALB security group accepts origin traffic only from AWS's CloudFront
  origin-facing managed prefix list. A random secret origin header is also
  required by its listener rule; other requests receive 403. Do not expose the
  listener-rule header value in an evidence screenshot.
- Only the ALB may reach task port 8080; there is no inbound rule for app port
  8000. Only the task security group may reach database port 5432. The database
  route table retains no internet default route. Default network ACLs are used.
- Browser-to-CloudFront uses HTTPS, and application-to-RDS uses certificate and
  hostname verification. **CloudFront-to-ALB and ALB-to-task use HTTP.** A custom
  verified domain/certificate and an HTTPS origin would improve this. The
  default CloudFront certificate also uses AWS's default TLS security policy;
  this setup does not enforce a custom minimum TLS version.
- Web/app containers share an ECS task, ENI, security group and scaling unit.
  This uses the assignment's permitted co-hosting exception. The database
  password is injected only into the app container, but the shared task is a
  single network/security boundary.
- Application database credentials have data/sequence permissions, without
  database/schema creation rights. Owner credentials are used only by the
  initialization task. No AWS task role is supplied to the application.
- Sessions, carts, orders and authentication data use shared PostgreSQL state;
  app tasks can be replaced or scaled. Password hashes and CSRF checks remain
  in the application. The origin policy forwards CloudFront's viewer-address
  header so application rate limiting receives the viewer's IP.
- Two tasks and health-based replacement improve application-tier resilience.
  Actual cross-AZ placement is printed after deployment. **Single-AZ RDS and
  one NAT gateway remain failure points**. Autoscaling is configured, not
  demonstrated under load until a real scaling test is performed.
- PostgreSQL write advisory locking preserves the original application's
  transaction behavior, but serializes some writes and limits peak throughput.
  Small shared CPU/memory sizes and the small database are for assessment traffic.
- The image build is reproducible at the source/dependency version level and
  releases use unique immutable ECR tags. Base-image tags are not digest-pinned;
  rebuilding later may pull a newer base. Startup secrets are not automatically
  rotated or refreshed in running tasks. A future schema change needs a separate
  reviewed migration; ordinary GitHub deployments run with auto-initialization
  disabled.
- Logs retain seven days; CI result artifacts retain thirty days. No WAF or
  application tracing is enabled. RDS backups retain one day and no restore
  drill has yet been performed. CloudWatch logging is the chosen enhancement.
- The stack intentionally allows eventual database deletion for the short
  assessment. Deleting it destroys its data and removes automated backups; take
  a deliberate export/snapshot first if the data must be retained. The script
  does not initiate teardown. A replacement operation retains a snapshot.

These limitations belong in the final report's dedicated NFR section. Resource
creation, failover, autoscaling and restore testing must not be reported as
successful merely because the configuration exists.

## Evidence

No screenshot is needed for the plan, initial source upload or publishing-only
CI run. Capture the completed AWS configuration and final successful automated
deployment once, using the report's minimal evidence checklist. Never capture
passwords, access keys or the secret origin header.
