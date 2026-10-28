import json
import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from shop.integration.models import IntegrationEvent
from shop.integration.signing import sign
from shop.models import OrderPaymentStatus, Product
from shop.serializers import ProductSerializer
from shop.stock import reserve_order_stock
from shop.tests.test_stock import make_order, make_product

SECRET = "stock-secret"
EVENTS = "/integration/events/"
SNAPSHOT = "/integration/stock/"
MANAGED = "Stock for this product is managed in Supply Chain IQ."
PRICE_MANAGED = "The price of this product is managed in Supply Chain IQ."


@override_settings(IQ_WEBHOOK_SECRET=SECRET)
class StockChangedTests(TestCase):
    def post(self, path, payload, secret=SECRET):
        body = json.dumps(payload).encode()
        return self.client.generic(
            "POST", path, body, content_type="application/json",
            HTTP_X_INTEGRATION_SIGNATURE=sign(secret, body),
        )

    def stock_event(self, *items, event_id=None):
        return {
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": "stock.changed",
            "occurred_at": "2026-10-18T10:00:00Z",
            "data": {"items": [
                {"product_id": str(p.product_id), "online_available": available, "version": version}
                for p, available, version in items
            ]},
        }

    def test_applies_snapshot_and_marks_product_iq_managed(self):
        product = make_product(stock=50)
        response = self.post(EVENTS, self.stock_event((product, 7, 1)))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json(), {"status": "applied", "unknown_products": [], "stale": 0, "price_rejected": []}
        )
        product.refresh_from_db()
        self.assertEqual(
            (product.stock_quantity, product.iq_available, product.iq_stock_version, product.iq_managed),
            (7, 7, 1, True),
        )
        marker = IntegrationEvent.objects.get()
        self.assertEqual((marker.direction, marker.event_type), ("in", "stock.changed"))

    def test_older_or_repeated_versions_are_ignored(self):
        product = make_product()
        self.post(EVENTS, self.stock_event((product, 7, 5)))
        older = self.post(EVENTS, self.stock_event((product, 99, 4)))
        same = self.post(EVENTS, self.stock_event((product, 99, 5)))
        self.assertEqual(older.json()["stale"], 1)
        self.assertEqual(same.json()["stale"], 1)
        product.refresh_from_db()
        self.assertEqual((product.stock_quantity, product.iq_stock_version), (7, 5))

    def test_duplicate_event_is_a_no_op(self):
        product = make_product()
        payload = self.stock_event((product, 3, 1))
        self.post(EVENTS, payload)
        self.assertEqual(self.post(EVENTS, payload).json(), {"status": "duplicate"})

    def test_units_held_for_unpaid_checkouts_are_not_counted_twice(self):
        product = make_product(stock=10)
        held = make_order((product, 3))
        reserve_order_stock(held)  # stock 7; IQ has not heard of this order
        paid = make_order((product, 2))
        paid.stock_reserved = True
        paid.stripe_payment_status = OrderPaymentStatus.PAID.value
        paid.save()
        self.post(EVENTS, self.stock_event((product, 10, 1)))
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 7)  # 10 in IQ − 3 still held for the unpaid checkout
        self.post(EVENTS, self.stock_event((product, 2, 2)))
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 0)  # never below zero

    def test_unknown_and_invalid_items_are_reported_not_retried(self):
        product = make_product()
        unknown = str(uuid.uuid4())
        payload = self.stock_event((product, 4, 1))
        payload["data"]["items"] += [
            {"product_id": unknown, "online_available": 1, "version": 1},
            {"product_id": "nope", "online_available": 1, "version": 1},
            {"product_id": str(product.product_id), "online_available": -1, "version": 9},
            "junk",
        ]
        response = self.post(EVENTS, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"status": "partial", "unknown_products": [unknown], "stale": 0, "price_rejected": []}
        )
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 4)
        bad = self.post(EVENTS, {**self.stock_event(), "data": {"items": "x"}})
        self.assertEqual(bad.json()["status"], "ignored")

    def test_bad_signature_401(self):
        product = make_product(stock=5)
        response = self.post(EVENTS, self.stock_event((product, 1, 1)), secret="wrong")
        self.assertEqual(response.status_code, 401)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 5)

    def test_loyalty_events_still_work_on_both_routes(self):
        for path in (EVENTS, "/rewards/api/integration/events/"):
            response = self.post(path, {
                "event_id": str(uuid.uuid4()), "event_type": "loyalty.reverse",
                "occurred_at": "2026-10-18T10:00:00Z", "data": {"order_reference": "iq-sale-none"},
            })
            self.assertEqual(response.json(), {"status": "nothing_to_reverse"}, path)

    def test_snapshot_lists_every_product(self):
        managed, plain = make_product(stock=2), make_product(stock=9)
        Product.all_objects.filter(pk=managed.pk).update(barcode="5000000000017", alternate_barcodes=["111", "222"])
        Product.all_objects.filter(pk=plain.pk).update(barcode=None, alternate_barcodes=[])
        managed.refresh_from_db()
        self.post(EVENTS, self.stock_event((managed, 2, 3)))
        response = self.post(SNAPSHOT, {})
        self.assertEqual(response.status_code, 200)
        items = {item["product_id"]: item for item in response.json()["items"]}
        self.assertEqual(items[str(managed.product_id)], {
            "product_id": str(managed.product_id), "stock_quantity": 2,
            "iq_managed": True, "iq_available": 2, "iq_stock_version": 3,
            "price": str(managed.price), "iq_price_managed": False,
            "name": managed.name, "barcode": "5000000000017", "alternate_barcodes": ["111", "222"],
        })
        self.assertFalse(items[str(plain.product_id)]["iq_managed"])
        self.assertEqual((items[str(plain.product_id)]["barcode"], items[str(plain.product_id)]["alternate_barcodes"]),
                         (None, []))
        self.assertEqual(self.post(SNAPSHOT, {}, secret="wrong").status_code, 401)


@override_settings(IQ_WEBHOOK_SECRET=SECRET)
class PriceChangedTests(TestCase):
    post = StockChangedTests.post

    def event(self, product, version, **price):
        return {
            "event_id": str(uuid.uuid4()), "event_type": "stock.changed", "occurred_at": "2026-10-18T10:00:00Z",
            "data": {"items": [{"product_id": str(product.product_id), "online_available": 4,
                                "version": version, **price}]},
        }

    def test_price_is_applied_and_marks_the_product(self):
        product = make_product()
        response = self.post(EVENTS, self.event(product, 1, price="2.49"))
        self.assertEqual(response.json()["status"], "applied")
        product.refresh_from_db()
        self.assertEqual((product.price, product.iq_price_managed, product.stock_quantity),
                         (Decimal("2.49"), True, 4))

    def test_no_price_leaves_the_price_alone(self):
        product = make_product()
        before = product.price
        self.post(EVENTS, self.event(product, 1))
        product.refresh_from_db()
        self.assertEqual((product.price, product.iq_price_managed), (before, False))

    def test_stale_snapshot_does_not_move_the_price_back(self):
        product = make_product()
        self.post(EVENTS, self.event(product, 2, price="3.00"))
        self.post(EVENTS, self.event(product, 1, price="9.00"))
        product.refresh_from_db()
        self.assertEqual(product.price, Decimal("3.00"))

    def test_bad_prices_are_refused_but_stock_applies(self):
        for version, bad in enumerate(["1000.00", "0", "-1", "1.999", "abc", "NaN", 5], start=1):
            product = make_product(stock=0)
            before = product.price
            with self.assertLogs("shop.integration.stock", "WARNING"):
                response = self.post(EVENTS, self.event(product, version, price=bad))
            self.assertEqual(response.json()["status"], "partial", bad)
            self.assertEqual(response.json()["price_rejected"], [str(product.product_id)], bad)
            product.refresh_from_db()
            self.assertEqual((product.price, product.iq_price_managed, product.stock_quantity), (before, False, 4))
        top = make_product()
        self.post(EVENTS, self.event(top, 1, price="999.99"))
        top.refresh_from_db()
        self.assertEqual(top.price, Decimal("999.99"))


class PriceEditBlockedTests(TestCase):
    def setUp(self):
        self.product = make_product()
        Product.objects.filter(pk=self.product.pk).update(iq_price_managed=True, price=Decimal("2.00"))
        self.product.refresh_from_db()
        self.staff = User.objects.create_user(username="staff", password="x", is_staff=True, is_superuser=True)

    def test_serializer_refuses_a_price_change(self):
        changed = ProductSerializer(self.product, data={"price": "5.00"}, partial=True)
        self.assertFalse(changed.is_valid())
        self.assertEqual(changed.errors["price"], [PRICE_MANAGED])
        same = ProductSerializer(self.product, data={"price": "2.00", "iq_price_managed": False}, partial=True)
        self.assertTrue(same.is_valid(), same.errors)
        same.save()
        self.product.refresh_from_db()
        self.assertTrue(self.product.iq_price_managed)

    def test_price_by_barcode_refuses(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("update_product_price_by_barcode"), {
            "price_update_product_barcode": self.product.barcode, "price_update_new_price": "5.00",
        })
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal("2.00"))

    def test_admin_shows_price_read_only(self):
        from django.contrib.admin.sites import site

        admin = site._registry[Product]
        request = type("R", (), {"user": self.staff})()
        self.assertIn("price", admin.get_readonly_fields(request, self.product))
        self.assertNotIn("price", admin.get_readonly_fields(request, make_product()))

    @override_settings(WEBSITE_PROFIT_PERCENTAGE=20)
    def test_epos_sync_skips_iq_priced_products(self):
        import pandas as pd
        from django.core.files.uploadedfile import SimpleUploadedFile

        plain = make_product()
        csv = pd.DataFrame({"PLU": [self.product.barcode, plain.barcode], "RetailPrice": [7.0, 7.0]})
        self.client.force_login(self.staff)
        response = self.client.post(reverse("sync_data_with_epos"), {"epos_sync_file": SimpleUploadedFile(
            "f.csv", csv.to_csv(index=False).encode(), content_type="text/csv")})
        self.assertEqual(response.json(), {"success": True, "updated": 1, "skipped_iq_managed": 1})
        self.product.refresh_from_db()
        plain.refresh_from_db()
        self.assertEqual(self.product.price, Decimal("2.00"))
        self.assertNotEqual(plain.price, Decimal("2.00"))


class StockEditBlockedTests(TestCase):
    def setUp(self):
        self.product = make_product(stock=5)
        Product.objects.filter(pk=self.product.pk).update(iq_managed=True, iq_available=5, iq_stock_version=1)
        self.product.refresh_from_db()
        self.staff = User.objects.create_user(username="staff", password="x", is_staff=True)

    def test_serializer_rejects_a_stock_change_but_allows_other_edits(self):
        changed = ProductSerializer(self.product, data={"stock_quantity": 50}, partial=True)
        self.assertFalse(changed.is_valid())
        self.assertEqual(changed.errors["stock_quantity"], [MANAGED])
        unchanged = ProductSerializer(self.product, data={"stock_quantity": 5, "name": "Renamed"}, partial=True)
        self.assertTrue(unchanged.is_valid(), unchanged.errors)
        sneaky = ProductSerializer(self.product, data={"iq_available": 99, "iq_managed": False}, partial=True)
        self.assertTrue(sneaky.is_valid())
        sneaky.save()
        self.product.refresh_from_db()
        self.assertEqual((self.product.iq_available, self.product.iq_managed), (5, True))

    def test_staff_api_cannot_change_stock(self):
        client = APIClient()
        client.force_authenticate(self.staff)
        response = client.patch(f"/shop/products/{self.product.pk}/", {"stock_quantity": 50}, format="json")
        self.assertIn(response.status_code, (400, 404), response.content)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)

    def test_add_stock_page_refuses(self):
        self.client.force_login(self.staff)
        from django.contrib.messages import get_messages

        response = self.client.post(
            reverse("add_product_stock"), {"barcode": self.product.barcode, "quantity_to_add": 10}
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)
        self.assertIn(MANAGED, [str(m) for m in get_messages(response.wsgi_request)])

    def test_admin_shows_stock_read_only(self):
        from django.contrib.admin.sites import site

        admin = site._registry[Product]
        request = type("R", (), {"user": self.staff})()
        self.assertIn("stock_quantity", admin.get_readonly_fields(request, self.product))
        self.assertIn("iq_available", admin.get_readonly_fields(request, None))
        self.assertNotIn("stock_quantity", admin.get_readonly_fields(request, make_product()))

    def test_customers_do_not_see_iq_fields(self):
        from shop.serializers import CustomerFacingProductSerializer

        data = CustomerFacingProductSerializer(self.product).data
        self.assertFalse({"iq_managed", "iq_available", "iq_stock_version"} & set(data))
