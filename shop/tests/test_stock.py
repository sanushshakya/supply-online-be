import itertools
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.test import TestCase

from shop.exceptions import InsufficientStockError
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from shop.models import Cart, CartItem, Order, OrderItem, Product, UserProfile
from shop.stock import (
    assert_cart_stock,
    lock_products,
    release_order_stock,
    reserve_order_stock,
    shortfall,
)

_counter = itertools.count(1)


def make_product(stock=10, active=True, name=None):
    n = next(_counter)
    product = Product.objects.create(
        name=name or f"Stock Product {n}",
        price=Decimal("5.00"),
        barcode=f"SB{n:08d}",
        stock_quantity=stock,
    )
    if not active:
        Product.all_objects.filter(pk=product.pk).update(is_active=False)
        product.refresh_from_db()
    return product


def make_cart(*lines):
    """lines: (product, quantity) tuples"""
    user = User.objects.create(username=f"stock_user_{next(_counter)}")
    cart = Cart.objects.create(user=user)
    for product, quantity in lines:
        CartItem.objects.create(cart=cart, product=product, quantity=quantity)
    return cart


def make_order(*lines, user=None):
    user = user or User.objects.create(username=f"stock_order_user_{next(_counter)}")
    order = Order.objects.create(user=user, delivery_type="Standard")
    for product, quantity in lines:
        OrderItem.objects.create(
            order=order, product=product, quantity=quantity, base_total=Decimal("5.00")
        )
    return order


class ShortfallTests(TestCase):
    def test_shortfall_none_when_within_stock(self):
        self.assertIsNone(shortfall(make_product(stock=5), 5))

    def test_shortfall_reports_available_when_over(self):
        product = make_product(stock=3, name="Rice")
        self.assertEqual(
            shortfall(product, 4),
            {
                "product_id": str(product.product_id),
                "name": "Rice",
                "requested": 4,
                "available": 3,
            },
        )

    def test_shortfall_inactive_product_available_zero(self):
        product = make_product(stock=9, active=False)
        self.assertEqual(shortfall(product, 1)["available"], 0)


class AssertCartStockTests(TestCase):
    def test_assert_cart_stock_passes_when_all_in_stock(self):
        cart = make_cart((make_product(stock=2), 2))
        assert_cart_stock(cart)

    def test_assert_cart_stock_lists_all_short_items(self):
        a, b, ok = make_product(stock=1), make_product(stock=0), make_product(stock=9)
        cart = make_cart((a, 3), (b, 1), (ok, 2))
        with self.assertRaises(InsufficientStockError) as ctx:
            assert_cart_stock(cart)
        by_id = {i["product_id"]: i for i in ctx.exception.items}
        self.assertEqual(set(by_id), {str(a.product_id), str(b.product_id)})
        self.assertEqual(by_id[str(a.product_id)]["available"], 1)

    def test_assert_cart_stock_reads_stock_from_database(self):
        product = make_product(stock=5)
        cart = make_cart((product, 3))
        Product.objects.filter(pk=product.pk).update(stock_quantity=1)
        with self.assertRaises(InsufficientStockError):
            assert_cart_stock(cart)

    def test_error_response_data_follows_contract(self):
        cart = make_cart((make_product(stock=0), 1))
        with self.assertRaises(InsufficientStockError) as ctx:
            assert_cart_stock(cart)
        data = ctx.exception.to_response_data()
        self.assertEqual(data["code"], "INSUFFICIENT_STOCK")
        self.assertIn("error", data)
        self.assertEqual(len(data["items"]), 1)


class ReserveReleaseTests(TestCase):
    def test_reserve_decrements_and_sets_flag(self):
        product = make_product(stock=5)
        order = make_order((product, 2))
        reserve_order_stock(order)
        product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(product.stock_quantity, 3)
        self.assertTrue(order.stock_reserved)

    def test_reserve_raises_and_changes_nothing_when_short(self):
        ok, short = make_product(stock=5), make_product(stock=1)
        order = make_order((ok, 2), (short, 2))
        with self.assertRaises(InsufficientStockError):
            reserve_order_stock(order)
        ok.refresh_from_db()
        short.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual((ok.stock_quantity, short.stock_quantity), (5, 1))
        self.assertFalse(order.stock_reserved)

    def test_release_restores_once(self):
        product = make_product(stock=5)
        order = make_order((product, 2))
        reserve_order_stock(order)
        release_order_stock(order)
        release_order_stock(order)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 5)
        self.assertFalse(order.stock_reserved)

    def test_release_noop_when_not_reserved(self):
        product = make_product(stock=5)
        order = make_order((product, 2))
        release_order_stock(order)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 5)

    def test_reserve_of_inactive_product_raises(self):
        product = make_product(stock=5, active=False)
        order = make_order((product, 1))
        with self.assertRaises(InsufficientStockError):
            reserve_order_stock(order)


class LockTests(TestCase):
    def test_lock_products_uses_select_for_update(self):
        product = make_product()
        original = QuerySet.select_for_update
        with patch.object(
            QuerySet, "select_for_update", autospec=True, side_effect=original
        ) as spy:
            locked = lock_products([product.product_id])
        spy.assert_called()
        self.assertEqual(locked[str(product.product_id)].pk, product.pk)

    def test_lock_products_includes_inactive_products(self):
        product = make_product(active=False)
        locked = lock_products([product.product_id])
        self.assertIn(str(product.product_id), locked)

    def test_reserve_uses_select_for_update(self):
        order = make_order((make_product(stock=3), 1))
        original = QuerySet.select_for_update
        with patch.object(
            QuerySet, "select_for_update", autospec=True, side_effect=original
        ) as spy:
            reserve_order_stock(order)
        spy.assert_called()


class CartStockTests(APITestCase):
    ADD_URL = "/shop/api/carts/add-item-to-cart/"
    ADD_MANY_URL = "/shop/api/carts/add-multiple-items-to-cart/"

    def setUp(self):
        self.user = User.objects.create(username="cart_stock_user", email="c@example.com")
        UserProfile.objects.create(
            user=self.user, fullname="Cart Stock", user_type="general customer"
        )
        self.cart = Cart.objects.create(user=self.user)
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def add(self, product, quantity):
        return self.client.post(
            self.ADD_URL,
            {
                "cart_id": str(self.cart.cart_id),
                "product_id": str(product.product_id),
                "quantity": quantity,
            },
            format="json",
        )

    def cart_quantity(self, product):
        item = CartItem.objects.filter(cart=self.cart, product=product).first()
        return item.quantity if item else 0

    def test_add_over_stock_returns_409_and_cart_unchanged(self):
        product = make_product(stock=3, name="Dal")
        response = self.add(product, 4)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "INSUFFICIENT_STOCK")
        self.assertEqual(
            response.data["items"],
            [
                {
                    "product_id": str(product.product_id),
                    "name": "Dal",
                    "requested": 4,
                    "available": 3,
                }
            ],
        )
        self.assertEqual(self.cart_quantity(product), 0)

    def test_add_accumulates_with_existing_cart_quantity(self):
        product = make_product(stock=3)
        self.assertEqual(self.add(product, 2).status_code, 200)
        response = self.add(product, 2)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["items"][0]["requested"], 4)
        self.assertEqual(response.data["items"][0]["available"], 3)
        self.assertEqual(self.cart_quantity(product), 2)

    def test_add_exactly_stock_succeeds(self):
        product = make_product(stock=3)
        self.assertEqual(self.add(product, 3).status_code, 200)
        self.assertEqual(self.cart_quantity(product), 3)

    def test_add_out_of_stock_returns_409(self):
        product = make_product(stock=0)
        response = self.add(product, 1)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["items"][0]["available"], 0)

    def test_add_multiple_skips_over_stock_items_and_warns(self):
        ok, short = make_product(stock=5), make_product(stock=1)
        response = self.client.post(
            self.ADD_MANY_URL,
            {
                "cart_id": str(self.cart.cart_id),
                "items": [
                    {"product_id": str(ok.product_id), "quantity": 2},
                    {"product_id": str(short.product_id), "quantity": 3},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(str(short.product_id), response.data["warning"])
        self.assertEqual(self.cart_quantity(ok), 2)
        self.assertEqual(self.cart_quantity(short), 0)


class CheckoutStockTests(APITestCase):
    URL = "/shop/api/carts/create-payment-checkout-session/"

    def setUp(self):
        self.user = User.objects.create(username="checkout_user", email="co@example.com")
        self.profile = UserProfile.objects.create(
            user=self.user, fullname="Checkout User", user_type="general customer"
        )
        self.product = make_product(stock=5)
        self.cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=3)
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def post(self):
        return self.client.post(
            self.URL,
            {
                "user_profile_id": str(self.profile.user_profile_id),
                "cart_id": str(self.cart.cart_id),
            },
            format="json",
        )

    @patch("shop.views.stripe.checkout.Session.create")
    def test_session_blocked_when_stock_dropped_after_add(self, create):
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=2)
        response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "INSUFFICIENT_STOCK")
        self.assertEqual(response.data["items"][0]["available"], 2)
        create.assert_not_called()

    @patch("shop.views.stripe.checkout.Session.create")
    def test_session_blocked_when_product_deactivated(self, create):
        Product.all_objects.filter(pk=self.product.pk).update(is_active=False)
        response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["items"][0]["available"], 0)
        create.assert_not_called()

    @patch("shop.views.stripe.checkout.Session.create")
    def test_session_created_when_stock_ok(self, create):
        create.return_value = type("S", (), {"client_secret": "sec", "id": "cs_1"})()
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["sessionId"], "cs_1")
        create.assert_called_once()

    @patch("shop.views.stripe.checkout.Session.create", side_effect=Exception("boom"))
    def test_session_error_returns_serializable_500(self, create):
        response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["error"], "boom")
