"""rewards/integration_views.py — loyalty endpoints and event handlers for the IQ till (signature-only auth)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from rest_framework.response import Response

from shop.integration.views import IntegrationEventView, SignedIntegrationView

from .models import LoyaltyAccount
from .services import award_points_for_instore, reverse_instore_award


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


# The original loyalty events route; /integration/events/ handles the same envelopes (and stock.changed).
LoyaltyEventView = IntegrationEventView


def handle_award(data):
    return {"status": _award(data)}


def handle_reverse(data):
    reference = data.get("order_reference")
    if not isinstance(reference, str) or not reference:
        return {"status": "ignored"}
    return {"status": "applied" if reverse_instore_award(reference) else "nothing_to_reverse"}


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
