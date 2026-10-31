"""A stable service must not be mistaken for a successful new release after rollback."""
import copy
import unittest
from unittest.mock import patch

from scripts import deploy_ecs


class DeploymentGuardTests(unittest.TestCase):
    def exercise(self, rolled_back=False):
        updates = []
        registrations = []
        reads = 0
        old = {'family': 'northstar', 'taskDefinitionArn': 'old-task', 'revision': 1,
               'executionRoleArn': 'approved-execution-role', 'networkMode': 'awsvpc',
               'requiresCompatibilities': ['FARGATE'], 'cpu': '256', 'memory': '512',
               'containerDefinitions': [
                   {'name': 'app', 'image': 'old-app',
                    'secrets': [{'name': 'NORTHSTAR_DB_PASSWORD', 'valueFrom': 'approved-secret-arn'}]},
                   {'name': 'web', 'image': 'old-web'}]}

        def aws(*arguments):
            nonlocal reads
            service = arguments[0:2]
            if service == ('ecs', 'describe-services'):
                reads += 1
                arn = 'old-task' if reads == 1 or rolled_back else 'new-task'
                return {'services': [{'taskDefinition': arn, 'desiredCount': 1, 'runningCount': 1}]}
            if service == ('ecs', 'describe-task-definition'):
                return {'taskDefinition': copy.deepcopy(old)}
            if service == ('ecs', 'register-task-definition'):
                import json
                registrations.append(json.loads(arguments[-1]))
                return {'taskDefinition': {'taskDefinitionArn': 'new-task'}}
            if service == ('ecs', 'update-service'):
                updates.append(arguments[-1])
                return {}
            raise AssertionError(arguments)

        argv = ['deploy', '--cluster', 'cluster', '--service', 'service',
                '--app-image', 'tested-app', '--web-image', 'tested-web',
                '--url', 'https://demo.example', '--revision', 'source-commit']
        with patch.object(deploy_ecs, 'aws', side_effect=aws), \
             patch.object(deploy_ecs.subprocess, 'run'), \
             patch.object(deploy_ecs, 'run', return_value=[{'status': 'passed'}]) as live, \
             patch('sys.argv', argv):
            if rolled_back:
                with self.assertRaisesRegex(RuntimeError, 'different task revision'):
                    deploy_ecs.main()
                live.assert_not_called()
            else:
                deploy_ecs.main()
                live.assert_called_once_with('https://demo.example', 'source-commit', full=False)
        return registrations, updates

    def test_deploy_uses_tested_images_and_preserves_secret_references(self):
        registered, updates = self.exercise()
        self.assertEqual(updates, ['new-task'])
        containers = {item['name']: item for item in registered[0]['containerDefinitions']}
        self.assertEqual(containers['app']['image'], 'tested-app')
        self.assertEqual(containers['web']['image'], 'tested-web')
        self.assertEqual(containers['app']['secrets'][0]['valueFrom'], 'approved-secret-arn')
        self.assertNotIn('taskDefinitionArn', registered[0])
        self.assertNotIn('revision', registered[0])

    def test_stable_service_on_old_task_is_reported_as_failure(self):
        _, updates = self.exercise(rolled_back=True)
        self.assertEqual(updates, ['new-task', 'old-task'])


if __name__ == '__main__':
    unittest.main()
