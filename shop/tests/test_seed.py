import os
import tempfile
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models.signals import post_save
from django.test import TestCase

from rewards.models import LoyaltyAccount
from shop.models import UserProfile


class SeedCommandTests(TestCase):
    """``manage.py seed``: snapshot into an empty database, superuser from the environment."""

    def snapshot(self):
        user = User.objects.create_user(username="amy", email="amy@example.com", password="amy-pw-123")
        UserProfile.objects.create(user=user, fullname="Amy")  # its receiver adds the loyalty account
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            path = handle.name
        self.addCleanup(os.unlink, path)
        call_command("dumpdata", "auth.user", "shop.userprofile", "rewards.loyaltyaccount",
                     output=path, stdout=StringIO())
        barcode = LoyaltyAccount.objects.get().barcode_number
        User.objects.all().delete()
        return path, barcode

    def seed(self, fixture=None, **env):
        args = ["--fixture", fixture] if fixture else []
        # Start from an environment without the seed variables (the Docker image sets them).
        base = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_SUPERUSER_")}
        with mock.patch.dict(os.environ, {**base, **env}, clear=True):
            call_command("seed", *args, stdout=StringIO())

    def test_loads_snapshot_without_receivers_and_creates_superuser(self):
        fixture, barcode = self.snapshot()
        receivers = list(post_save.receivers)
        self.seed(fixture, DJANGO_SUPERUSER_USERNAME="root", DJANGO_SUPERUSER_PASSWORD="root-pw-123")

        self.assertEqual(list(post_save.receivers), receivers)
        self.assertEqual(LoyaltyAccount.objects.get().barcode_number, barcode)
        self.assertTrue(User.objects.get(username="amy").check_password("amy-pw-123"))
        root = User.objects.get(username="root")
        self.assertTrue(root.is_superuser and root.is_staff and root.check_password("root-pw-123"))

    def test_rerun_skips_the_snapshot_and_keeps_the_password(self):
        fixture, _ = self.snapshot()
        self.seed(fixture, DJANGO_SUPERUSER_PASSWORD="root-pw-123")
        User.objects.filter(username="amy").update(first_name="Changed")
        self.seed(fixture, DJANGO_SUPERUSER_PASSWORD="other-pw")

        self.assertEqual(User.objects.get(username="amy").first_name, "Changed")
        self.assertTrue(User.objects.get(username="admin").check_password("root-pw-123"))

    def test_promotes_an_existing_user(self):
        fixture, _ = self.snapshot()
        self.seed(fixture, DJANGO_SUPERUSER_USERNAME="amy")
        amy = User.objects.get(username="amy")
        self.assertTrue(amy.is_superuser and amy.is_staff and amy.check_password("amy-pw-123"))

    def test_missing_fixture_and_password(self):
        self.seed("/nonexistent/seed.json")
        self.assertFalse(User.objects.exists())
        with self.assertRaises(CommandError):
            self.seed(DJANGO_SUPERUSER_USERNAME="root")
