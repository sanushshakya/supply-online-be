import logging
import uuid
from datetime import datetime, timezone

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone as dj_timezone

logger = logging.getLogger(__name__)


class IntegrationEvent(models.Model):
    """Transactional outbox row (direction "out") or inbox marker ("in")."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("delivered", "Delivered"),
        ("failed", "Failed"),
    ]
    DIRECTION_CHOICES = [("out", "Outbound"), ("in", "Inbound")]

    event_id = models.UUIDField(default=uuid.uuid4, unique=True)
    event_type = models.CharField(max_length=40)
    direction = models.CharField(
        max_length=3, choices=DIRECTION_CHOICES, default="out"
    )
    payload = models.JSONField()
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default="pending"
    )
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=dj_timezone.now)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["status", "next_attempt_at"])]

    def __str__(self):
        return f"{self.event_type} {self.event_id} ({self.status})"


def emit(event_type, data):
    """Create an outbound event; call inside the caller's transaction.

    Does nothing (returns None) when IQ_WEBHOOK_URL is not configured, so every
    caller is a no-op for deployments that are not connected to IQ. Dispatch to
    Celery happens on commit, so a rollback drops both the row and the send.
    """
    if not settings.IQ_WEBHOOK_URL:
        return None
    event_id = uuid.uuid4()
    payload = {
        "event_id": str(event_id),
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    event = IntegrationEvent.objects.create(
        event_id=event_id,
        event_type=event_type,
        direction="out",
        payload=payload,
    )

    def dispatch():
        from shop.tasks import deliver_integration_event  # lazy: avoid import cycle

        try:
            deliver_integration_event.delay(event.pk)
        except Exception as exc:  # noqa: BLE001 - broker down: the 30 s sweep picks it up
            logger.warning(
                "Could not queue integration event %s: %s", event.pk, type(exc).__name__
            )

    transaction.on_commit(dispatch)
    return event
