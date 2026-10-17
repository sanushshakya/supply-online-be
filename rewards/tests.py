from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from rewards.models import LoyaltyAccount, LoyaltyConfig, LoyaltyTransaction
from rewards.services import award_points_for_instore, reverse_instore_award
from shop.models import UserProfile

T = LoyaltyTransaction.TransactionType


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
