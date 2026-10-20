import os
from contextlib import contextmanager

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import signals

MODEL_SIGNALS = (signals.pre_save, signals.post_save, signals.pre_delete, signals.post_delete, signals.m2m_changed)


@contextmanager
def model_signals_muted():
    """
    Load a snapshot as-is. Receivers would otherwise add rows the snapshot already holds (e.g. a
    ``LoyaltyAccount`` for each saved ``UserProfile``) and clash with them.
    """
    saved = [(signal, signal.receivers, signal.sender_receivers_cache.copy()) for signal in MODEL_SIGNALS]
    for signal in MODEL_SIGNALS:
        signal.receivers = []
        signal.sender_receivers_cache.clear()
    try:
        yield
    finally:
        for signal, receivers, cache in saved:
            signal.receivers = receivers
            signal.sender_receivers_cache.clear()
            signal.sender_receivers_cache.update(cache)


class Command(BaseCommand):
    """
    Seed a fresh database (used by the workspace docker compose on every start; safe to rerun).

    1. ``--fixture``: a ``dumpdata`` JSON file, loaded only while the database has no users, so a restart
       never loads it twice or overwrites later changes.
    2. A superuser (``DJANGO_SUPERUSER_USERNAME``, default ``admin``; ``DJANGO_SUPERUSER_EMAIL``;
       ``DJANGO_SUPERUSER_PASSWORD``), created if missing. An existing user is promoted; its password is kept.
    """

    help = "Load a data snapshot into an empty database and make sure a superuser exists"

    def add_arguments(self, parser):
        parser.add_argument("--fixture", help="dumpdata JSON to load into an empty database (skipped if missing)")

    def handle(self, *args, **options):
        fixture = options["fixture"]
        if fixture and not os.path.exists(fixture):
            self.stdout.write(f"No fixture at {fixture}; nothing to load.")
        elif fixture and User.objects.exists():
            self.stdout.write("Database already has users; fixture not loaded.")
        elif fixture:
            with transaction.atomic(), model_signals_muted():
                call_command("loaddata", fixture, stdout=self.stdout)

        username = os.environ.get("DJANGO_SUPERUSER_USERNAME") or "admin"
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        if password or os.environ.get("DJANGO_SUPERUSER_USERNAME"):
            self._superuser(username, email, password)

    def _superuser(self, username, email, password):
        user = User.objects.filter(username=username).first()
        if user is None:
            if not password:
                raise CommandError("Set DJANGO_SUPERUSER_PASSWORD to create the superuser.")
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(f"Created superuser {username}.")
        elif not (user.is_staff and user.is_superuser and user.is_active):
            user.is_staff = user.is_superuser = user.is_active = True
            user.save(update_fields=["is_staff", "is_superuser", "is_active"])
            self.stdout.write(f"Made {username} a superuser.")
