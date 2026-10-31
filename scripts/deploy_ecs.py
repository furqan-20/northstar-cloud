"""Update an existing ECS service with the exact images that passed CI.

Initial AWS resources are provisioned separately. This script does not create
networks, databases, IAM roles or billable infrastructure.
"""
import argparse
import copy
import json
import subprocess
import sys
import time
from urllib.error import URLError

from scripts.smoke import run


def aws(*arguments):
    completed = subprocess.run(['aws', *arguments, '--output', 'json'],
                               check=True, capture_output=True, text=True)
    return json.loads(completed.stdout) if completed.stdout.strip() else {}


def main():
    parser = argparse.ArgumentParser()
    for name in ('cluster', 'service', 'app-image', 'web-image', 'url', 'revision'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    services = aws('ecs', 'describe-services', '--cluster', args.cluster, '--services', args.service)
    if services.get('failures') or not services.get('services'):
        raise RuntimeError('The initial ECS service must be created before this deployment step.')
    service = services['services'][0]
    previous_arn = service['taskDefinition']
    original = aws('ecs', 'describe-task-definition', '--task-definition', previous_arn)['taskDefinition']
    fields = ('family', 'taskRoleArn', 'executionRoleArn', 'networkMode', 'containerDefinitions',
              'volumes', 'placementConstraints', 'requiresCompatibilities', 'cpu', 'memory',
              'pidMode', 'ipcMode', 'proxyConfiguration', 'inferenceAccelerators',
              'ephemeralStorage', 'runtimePlatform', 'enableFaultInjection')
    definition = {key: copy.deepcopy(original[key]) for key in fields if key in original}
    containers = {container['name']: container for container in definition['containerDefinitions']}
    if not {'app', 'web'} <= containers.keys():
        raise RuntimeError('The task definition must contain containers named app and web.')
    containers['app']['image'] = args.app_image
    containers['web']['image'] = args.web_image
    registered = aws('ecs', 'register-task-definition', '--cli-input-json', json.dumps(definition))
    new_arn = registered['taskDefinition']['taskDefinitionArn']
    print('Deploying task definition:', new_arn, flush=True)
    aws('ecs', 'update-service', '--cluster', args.cluster, '--service', args.service,
        '--task-definition', new_arn)
    try:
        subprocess.run(['aws', 'ecs', 'wait', 'services-stable', '--cluster', args.cluster,
                        '--services', args.service], check=True)
        current = aws('ecs', 'describe-services', '--cluster', args.cluster,
                      '--services', args.service)['services'][0]
        if current['taskDefinition'] != new_arn:
            raise RuntimeError('ECS returned to a different task revision; this deployment did not succeed.')
        if not current['desiredCount'] or current['runningCount'] < current['desiredCount']:
            raise RuntimeError('The service has not reached its required running task count.')
        last_error = None
        for attempt in range(12):
            try:
                checks = run(args.url, args.revision, full=False)
                print(json.dumps({'revision': args.revision, 'task_definition': new_arn,
                                  'read_only_live_checks': checks}, indent=2), flush=True)
                break
            except (AssertionError, URLError, TimeoutError) as exc:
                last_error = exc
                if attempt == 11:
                    raise RuntimeError('Live application checks failed.') from last_error
                time.sleep(5)
    except Exception:
        print('Deployment verification failed; restoring the previous task definition.', file=sys.stderr)
        aws('ecs', 'update-service', '--cluster', args.cluster, '--service', args.service,
            '--task-definition', previous_arn)
        raise


if __name__ == '__main__':
    main()
