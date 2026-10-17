"""rewards/integration_views.py — endpoints the IQ till calls, authenticated by signature only."""
from __future__ import annotations

import json
import uuid
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from shop.integration.models import IntegrationEvent
from shop.integration.signing import verify_request

from .models import LoyaltyAccount
from .services import award_points_for_instore, reverse_instore_award

UNAUTHORISED = {"code": "invalid_signature", "detail": "Invalid or missing signature."}


class SignedIntegrationView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if not verify_request(request):
            return Response(UNAUTHORISED, status=401)
        try:
            body = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            body = None
        if not isinstance(body, dict):
            return Response({"detail": "invalid_body"}, status=400)
        return self.handle(body)


class LoyaltyLookupView(SignedIntegrationView):
    """POST /rewards/api/integration/lookup/  {"barcode": "..."} → first name and balance only."""

    def handle(self, body):
        barcode = body.get("barcode")
        account = None
        if isinstance(barcode, str) and barcode:
            account = (
                LoyaltyAccount.objects.select_related("user_profile")
                .filter(barcode_number=barcode, is_active=True)
                .first()
            )
        if account is None:
            return Response({"detail": "not_found"}, status=404)
        names = (account.user_profile.fullname or "").split()
        return Response({
            "first_name": names[0] if names else "",
            "points_balance": account.points_balance,
            "tier": account.tier,
            "points_gbp_value": str(account.points_gbp_value.quantize(Decimal("0.01"))),
        })


class LoyaltyEventView(SignedIntegrationView):
    """POST /rewards/api/integration/events/  — loyalty.award / loyalty.reverse envelopes.

    Idempotent on ``event_id`` (an inbound IntegrationEvent is the marker). Every
    signed, well-formed envelope gets 200 so IQ never retries a business "no".
    """

    def handle(self, body):
        try:
            event_id = uuid.UUID(str(body["event_id"]))
            event_type = body["event_type"]
        except (KeyError, ValueError):
            return Response({"detail": "invalid_event"}, status=400)
        if not isinstance(event_type, str) or not event_type:
            return Response({"detail": "invalid_event"}, status=400)

        try:
            with transaction.atomic():
                IntegrationEvent.objects.create(
                    event_id=event_id,
                    event_type=event_type[:40],
                    direction="in",
                    status="delivered",
                    payload=body,
                )
                result = self.apply(event_type, body.get("data"))
        except IntegrityError:
            result = "duplicate"
        return Response({"status": result})

    def apply(self, event_type, data):
        if not isinstance(data, dict):
            return "ignored"
        if event_type == "loyalty.award":
            return _award(data)
        if event_type == "loyalty.reverse":
            reference = data.get("order_reference")
            if not isinstance(reference, str) or not reference:
                return "ignored"
            return "applied" if reverse_instore_award(reference) else "nothing_to_reverse"
        return "ignored"


def _award(data):
    barcode, reference = data.get("barcode"), data.get("order_reference")
    if not (isinstance(barcode, str) and barcode and isinstance(reference, str) and reference):
        return "ignored"
    try:
        amount = Decimal(str(data.get("amount")))
    except InvalidOperation:
        return "ignored"
    if not amount.is_finite() or amount <= 0:
        return "ignored"
    if not LoyaltyAccount.objects.filter(barcode_number=barcode, is_active=True).exists():
        return "unknown_account"
    try:
        award_points_for_instore(barcode, amount, reference)
    except ValueError:  # programme paused, or the amount earns no points
        return "ignored"
    return "applied"
