"""rewards/apps.py"""
from django.apps import AppConfig


class RewardsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rewards"
    verbose_name = "Loyalty Programme"

    def ready(self):
        from .signals import connect_signals
        connect_signals()