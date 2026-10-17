import json
import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from rewards.models import LoyaltyAccount, LoyaltyConfig, LoyaltyTransaction
from rewards.services import award_points_for_instore, reverse_instore_award
from shop.integration.models import IntegrationEvent
from shop.integration.signing import sign
from shop.models import UserProfile

T = LoyaltyTransaction.TransactionType
LOOKUP = "/rewards/api/integration/lookup/"
EVENTS = "/rewards/api/integration/events/"


class InstoreAwardTests(TestCase):
    def setUp(self):
        config = LoyaltyConfig.get_config()
        config.is_active = True
        config.points_per_pound = Decimal("1")
        config.save()
        user = User.objects.create_user(username="cust", password="x")
        self.profile = UserProfile.objects.create(user=user, fullname="Amira Khan")
        self.account, _ = LoyaltyAccount.objects.get_or_create(user_profile=self.profile)
        self.barcode = self.account.barcode_number

    def balance(self):
        self.account.refresh_from_db()
        return self.account.points_balance

    def test_award_idempotent_on_order_reference(self):
        first = award_points_for_instore(self.barcode, Decimal("12.50"), "iq-sale-1")
        second = award_points_for_instore(self.barcode, Decimal("12.50"), "iq-sale-1")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(LoyaltyTransaction.objects.filter(transaction_type=T.EARN_INSTORE).count(), 1)
        self.assertEqual(self.balance(), 12)

    def test_award_without_reference_is_not_deduplicated(self):
        award_points_for_instore(self.barcode, Decimal("5"), None)
        award_points_for_instore(self.barcode, Decimal("5"), "")
        self.assertEqual(self.balance(), 10)
        self.assertFalse(LoyaltyTransaction.objects.exclude(order_reference=None).exists())

    def test_unknown_barcode_raises(self):
        with self.assertRaises(ValueError):
            award_points_for_instore("0000000000000", Decimal("5"), "iq-sale-x")

    def test_reverse_deducts_once(self):
        award_points_for_instore(self.barcode, Decimal("20"), "iq-sale-2")
        first = reverse_instore_award("iq-sale-2")
        second = reverse_instore_award("iq-sale-2")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.transaction_type, T.REVERSE_INSTORE)
        self.assertEqual(first.points, -20)
        self.assertEqual(self.balance(), 0)
        self.assertEqual(self.account.total_points_earned, 0)

    def test_reverse_may_take_balance_negative(self):
        award_points_for_instore(self.barcode, Decimal("20"), "iq-sale-3")
        LoyaltyAccount.objects.filter(pk=self.account.pk).update(points_balance=5)  # 15 already spent
        reverse_instore_award("iq-sale-3")
        self.assertEqual(self.balance(), -15)

    def test_reverse_unknown_reference_returns_none(self):
        self.assertIsNone(reverse_instore_award("iq-sale-missing"))
        self.assertIsNone(reverse_instore_award(""))
        self.assertFalse(LoyaltyTransaction.objects.filter(transaction_type=T.REVERSE_INSTORE).exists())

    def test_existing_instore_view_still_awards(self):
        staff = User.objects.create_user(username="staff", password="x", is_staff=True)
        client = APIClient()
        client.force_authenticate(staff)
        payload = {"barcode_number": self.barcode, "order_amount": "7.00", "order_reference": "till-9"}
        response = client.post("/rewards/api/instore/award/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["points_awarded"], 7)
        again = client.post("/rewards/api/instore/award/", payload, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(self.balance(), 7)

    def test_database_refuses_a_second_award_for_a_reference(self):
        from django.db import IntegrityError, transaction

        award_points_for_instore(self.barcode, Decimal("3"), "iq-sale-4")
        with self.assertRaises(IntegrityError), transaction.atomic():
            LoyaltyTransaction.objects.create(
                loyalty_account=self.account, transaction_type=T.EARN_INSTORE,
                points=3, order_reference="iq-sale-4", balance_after=6,
            )


SECRET = "test-iq-secret"


@override_settings(IQ_WEBHOOK_SECRET=SECRET)
class IntegrationEndpointTests(TestCase):
    def setUp(self):
        config = LoyaltyConfig.get_config()
        config.is_active = True
        config.points_per_pound = Decimal("1")
        config.save()
        user = User.objects.create_user(username="cust", password="x", email="amira@example.com")
        self.profile = UserProfile.objects.create(user=user, fullname="Amira Khan", mobile_number="07000000000")
        self.account, _ = LoyaltyAccount.objects.get_or_create(user_profile=self.profile)
        self.barcode = self.account.barcode_number

    def post(self, path, payload, secret=SECRET):
        body = json.dumps(payload).encode()
        return self.client.generic(
            "POST", path, body, content_type="application/json",
            HTTP_X_INTEGRATION_SIGNATURE=sign(secret, body),
        )

    def event(self, event_type, data, event_id=None):
        return {
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": event_type,
            "occurred_at": "2026-10-17T10:00:00Z",
            "data": data,
        }

    def balance(self):
        self.account.refresh_from_db()
        return self.account.points_balance

    def test_lookup_returns_minimal_fields(self):
        response = self.post(LOOKUP, {"barcode": self.barcode})
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(set(body), {"first_name", "points_balance", "tier", "points_gbp_value"})
        self.assertEqual(body["first_name"], "Amira")
        self.assertEqual(body["points_balance"], 0)
        self.assertEqual(body["tier"], "Bronze")
        self.assertNotIn(b"Khan", response.content)
        self.assertNotIn(b"amira@example.com", response.content)

    def test_lookup_unknown_404(self):
        unknown = self.post(LOOKUP, {"barcode": "0000000000000"})
        LoyaltyAccount.objects.filter(pk=self.account.pk).update(is_active=False)
        inactive = self.post(LOOKUP, {"barcode": self.barcode})
        for response in (unknown, inactive):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "not_found"})

    def test_lookup_bad_signature_401(self):
        bad = self.post(LOOKUP, {"barcode": self.barcode}, secret="wrong")
        missing = self.client.post(LOOKUP, {"barcode": self.barcode}, content_type="application/json")
        with override_settings(IQ_WEBHOOK_SECRET=""):
            unconfigured = self.post(LOOKUP, {"barcode": self.barcode}, secret="")
        events = self.post(EVENTS, self.event("loyalty.award", {}), secret="wrong")
        for response in (bad, missing, unconfigured, events):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.content, bad.content)

    def test_award_event_applied_then_duplicate(self):
        payload = self.event("loyalty.award", {"barcode": self.barcode, "amount": "12.50", "order_reference": "iq-sale-1"})
        first = self.post(EVENTS, payload)
        second = self.post(EVENTS, payload)
        self.assertEqual(first.json(), {"status": "applied"})
        self.assertEqual(second.json(), {"status": "duplicate"})
        self.assertEqual(self.balance(), 12)
        marker = IntegrationEvent.objects.get(event_id=payload["event_id"])
        self.assertEqual((marker.direction, marker.status, marker.event_type), ("in", "delivered", "loyalty.award"))

    def test_award_same_reference_new_event_does_not_double(self):
        data = {"barcode": self.barcode, "amount": "12.50", "order_reference": "iq-sale-1"}
        self.post(EVENTS, self.event("loyalty.award", data))
        again = self.post(EVENTS, self.event("loyalty.award", data))
        self.assertEqual(again.json(), {"status": "applied"})
        self.assertEqual(self.balance(), 12)

    def test_award_unknown_barcode_200_unknown_account(self):
        response = self.post(EVENTS, self.event("loyalty.award", {"barcode": "0000000000000", "amount": "5", "order_reference": "iq-sale-2"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "unknown_account"})
        self.assertFalse(LoyaltyTransaction.objects.exists())

    def test_reverse_event(self):
        award_points_for_instore(self.barcode, Decimal("20"), "iq-sale-3")
        first = self.post(EVENTS, self.event("loyalty.reverse", {"order_reference": "iq-sale-3"}))
        nothing = self.post(EVENTS, self.event("loyalty.reverse", {"order_reference": "iq-sale-none"}))
        self.assertEqual(first.json(), {"status": "applied"})
        self.assertEqual(nothing.json(), {"status": "nothing_to_reverse"})
        self.assertEqual(self.balance(), 0)

    def test_bad_data_and_unknown_type_are_ignored(self):
        responses = [
            self.post(EVENTS, self.event("loyalty.award", {"barcode": self.barcode, "amount": "lots", "order_reference": "iq-sale-4"})),
            self.post(EVENTS, self.event("loyalty.award", {"barcode": self.barcode, "amount": "-5", "order_reference": "iq-sale-5"})),
            self.post(EVENTS, self.event("loyalty.award", "junk")),
            self.post(EVENTS, self.event("order.refunded", {})),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json(), {"status": "ignored"})
        self.assertFalse(LoyaltyTransaction.objects.exists())

    def test_paused_programme_is_ignored(self):
        LoyaltyConfig.objects.filter(pk=1).update(is_active=False)
        response = self.post(EVENTS, self.event("loyalty.award", {"barcode": self.barcode, "amount": "5", "order_reference": "iq-sale-6"}))
        self.assertEqual(response.json(), {"status": "ignored"})
        self.assertEqual(self.balance(), 0)

    def test_invalid_envelope_400(self):
        response = self.post(EVENTS, {"event_type": "loyalty.award"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(IntegrationEvent.objects.exists())
