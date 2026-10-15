"""rewards/management/commands/backfill_loyalty_accounts.py"""
from django.core.management.base import BaseCommand
from django.apps import apps


class Command(BaseCommand):
    help = "Backfill LoyaltyAccount records for existing UserProfile customers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        UserProfile = apps.get_model("shop", "UserProfile")
        LoyaltyAccount = apps.get_model("rewards", "LoyaltyAccount")

        profiles_without_account = UserProfile.objects.filter(
            loyalty_account__isnull=True
        ).select_related("user")

        total = profiles_without_account.count()

        if total == 0:
            self.stdout.write(self.style.SUCCESS("✅  All profiles already have a loyalty account."))
            return

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(f"{prefix}Found {total} profile(s) without a loyalty account.")

        created = 0
        for profile in profiles_without_account:
            if dry_run:
                self.stdout.write(
                    f"  → Would create: {profile.fullname} ({profile.user.email})"
                )
            else:
                account, new = LoyaltyAccount.objects.get_or_create(user_profile=profile)
                if new:
                    created += 1
                    self.stdout.write(
                        f"  ✔  {profile.fullname} ({profile.user.email})  "
                        f"barcode: {account.barcode_number}"
                    )

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"\n✅  Created {created} loyalty account(s)."))