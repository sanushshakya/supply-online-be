"""Signed endpoints Supply Chain IQ calls. The X-Integration-Signature is the only authentication."""
from __future__ import annotations

import json
import uuid

from django.db import IntegrityError, transaction
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from shop.integration.models import IntegrationEvent
from shop.integration.signing import verify_request

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


def _handlers():
    from rewards.integration_views import handle_award, handle_reverse
    from shop.integration.stock import apply_stock_changed

    return {
        "loyalty.award": handle_award,
        "loyalty.reverse": handle_reverse,
        "stock.changed": apply_stock_changed,
    }


class IntegrationEventView(SignedIntegrationView):
    """POST /integration/events/ — every event IQ sends (loyalty.award, loyalty.reverse, stock.changed).

    Idempotent on ``event_id`` (an inbound IntegrationEvent is the marker). Every signed, well-formed
    envelope gets 200 with a ``status`` so IQ never retries a business "no".
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
                handler = _handlers().get(event_type)
                data = body.get("data")
                result = handler(data) if handler and isinstance(data, dict) else {"status": "ignored"}
        except IntegrityError:
            result = {"status": "duplicate"}
        return Response(result)


class StockSnapshotView(SignedIntegrationView):
    """POST /integration/stock/ — every product's stock and price, for IQ's nightly comparison."""

    def handle(self, body):
        from shop.models import Product

        rows = Product.all_objects.values(
            "product_id", "stock_quantity", "iq_managed", "iq_available", "iq_stock_version", "price", "iq_price_managed"
        )
        return Response({"items": [
            {**row, "product_id": str(row["product_id"]), "price": str(row["price"])} for row in rows
        ]})
