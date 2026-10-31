"""Guard against deploying unmatched builds or changing unrelated IAM roles."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock

from infra.provision import grant_ci, image_revision, select_images


class InfrastructureGuards(unittest.TestCase):
    def setUp(self):
        self.old = "a" * 40 + "-100-1"
        self.new = "b" * 40 + "-101-1"
        self.now = datetime.now(timezone.utc)

    def image(self, tag, age):
        return {"imageTags": [tag], "imagePushedAt": self.now - timedelta(minutes=age),
                "imageDigest": "sha256:" + tag[:40] + "0" * 24}

    def test_incomplete_new_publish_keeps_the_newest_matching_pair(self):
        ecr = Mock()
        pages = {
            "northstar-app": [{"imageDetails": [self.image(self.old, 5), self.image(self.new, 0)]}],
            "northstar-web": [{"imageDetails": [self.image(self.old, 4)]}],
        }
        ecr.get_paginator.return_value.paginate.side_effect = lambda **kw: pages[kw["repositoryName"]]
        result = select_images(ecr)
        self.assertEqual(result["tag"], self.old)
        self.assertIn("@sha256:", result["app_image"])
        self.assertIn("@sha256:", result["web_image"])

    def test_explicit_tag_must_exist_in_both_repositories(self):
        ecr = Mock()
        ecr.get_paginator.return_value.paginate.side_effect = [
            [{"imageDetails": [self.image(self.old, 2), self.image(self.new, 0)]}],
            [{"imageDetails": [self.image(self.old, 1)]}],
        ]
        with self.assertRaisesRegex(RuntimeError, "not present in both"):
            select_images(ecr, self.new)

    def test_initial_digest_resolves_to_its_own_source_revision(self):
        ecr = Mock()
        ecr.describe_images.return_value = {"imageDetails": [self.image(self.old, 5)]}
        revision = image_revision(ecr, "registry/northstar-app@sha256:" + "c" * 64)
        self.assertEqual(revision, "a" * 40)
        self.assertEqual(ecr.describe_images.call_args.kwargs["imageIds"], [{"imageDigest": "sha256:" + "c" * 64}])

    def test_a_role_owned_by_another_project_is_not_modified(self):
        iam = Mock()
        iam.get_role.return_value = {"Role": {"Tags": [{"Key": "Project", "Value": "OtherProject"}]}}
        with self.assertRaisesRegex(RuntimeError, "not tagged for this project"):
            grant_ci(iam, {})
        iam.put_role_policy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
