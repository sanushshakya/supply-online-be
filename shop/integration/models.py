import uuid
from datetime import datetime, timezone

from django.db import models
from django.utils import timezone as dj_timezone


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
    """Create an outbound event; call inside the caller's transaction."""
    event_id = uuid.uuid4()
    payload = {
        "event_id": str(event_id),
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    return IntegrationEvent.objects.create(
        event_id=event_id,
        event_type=event_type,
        direction="out",
        payload=payload,
    )
