import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from shop.integration import signing
from shop.integration.models import IntegrationEvent, emit
from shop.models import Order, OrderItem, UserProfile
from shop.tasks import deliver_integration_event, deliver_integration_events
from shop.tests.test_stock import make_product

SECRET = "s3cret"
BODY = b'{"a": 1}'


class SigningTests(TestCase):
    def test_sign_verify_roundtrip(self):
        header = signing.sign(SECRET, BODY, now=1000)
        self.assertTrue(header.startswith("t=1000,v1="))
        self.assertTrue(signing.verify(SECRET, BODY, header, now=1000))

    def test_verify_rejects_tampered_body(self):
        header = signing.sign(SECRET, BODY, now=1000)
        self.assertFalse(signing.verify(SECRET, b'{"a": 2}', header, now=1000))

    def test_verify_rejects_stale_timestamp(self):
        header = signing.sign(SECRET, BODY, now=1000)
        self.assertFalse(signing.verify(SECRET, BODY, header, now=1301))
        self.assertTrue(signing.verify(SECRET, BODY, header, now=1300))

    def test_verify_rejects_garbage_and_empty_secret(self):
        header = signing.sign(SECRET, BODY, now=1000)
        for bad in (None, "", "garbage", "t=abc,v1=x", "t=1000", "v1=ab"):
            self.assertFalse(signing.verify(SECRET, BODY, bad, now=1000))
        self.assertFalse(signing.verify("", BODY, header, now=1000))
        self.assertFalse(signing.verify("other", BODY, header, now=1000))

    def test_verify_non_ascii_signature_returns_false(self):
        self.assertFalse(signing.verify(SECRET, BODY, "t=1000,v1=\u00e9", now=1000))
        self.assertFalse(
            signing.verify(SECRET, BODY, "t=1000,v1=" + "\u00e9" * 64, now=1000)
        )
        self.assertFalse(signing.verify(SECRET, BODY, "t=\u00b2,v1=ab", now=1000))

    def test_verify_rejects_noncanonical_header(self):
        good = signing.sign(SECRET, BODY, now=1000)
        t, v1 = good.split(",")
        self.assertTrue(signing.verify(SECRET, BODY, good, now=1000))
        for bad in (
            f"{t}, {v1}",
            f"{t},{v1},{v1}",
            f"{t},{v1},extra=1",
            f"t=+1000,{v1}",
            f"{v1},{t}",
            f"{t},{v1.upper()}",
            f"{t},v1={v1[3:-1]}",
        ):
            self.assertFalse(signing.verify(SECRET, BODY, bad, now=1000), bad)


@override_settings(IQ_WEBHOOK_URL="https://iq.example.com/e/")
class EmitTests(TestCase):
    def test_emit_builds_envelope(self):
        event = emit("order.paid", {"order_id": "x"})
        event.refresh_from_db()
        self.assertEqual(
            set(event.payload),
            {"event_id", "event_type", "occurred_at", "data"},
        )
        self.assertEqual(event.payload["event_id"], str(event.event_id))
        self.assertEqual(event.payload["data"], {"order_id": "x"})
        self.assertEqual(event.direction, "out")
        self.assertEqual(event.status, "pending")
        self.assertEqual(IntegrationEvent.objects.count(), 1)


URL = "https://iq.example.com/integrations/m18/events/"


@override_settings(IQ_WEBHOOK_URL=URL, IQ_WEBHOOK_SECRET=SECRET)
class EmitDispatchTests(TestCase):
    def test_emit_dispatches_on_commit(self):
        with patch("shop.tasks.deliver_integration_event.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                event = emit("order.paid", {"order_id": "x"})
            self.assertEqual(len(callbacks), 1)
            delay.assert_called_once_with(event.pk)

    @override_settings(IQ_WEBHOOK_URL="")
    def test_no_url_configured_emits_nothing(self):
        with patch("shop.tasks.deliver_integration_event.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                result = emit("order.paid", {"order_id": "x"})
        self.assertIsNone(result)
        self.assertEqual(IntegrationEvent.objects.count(), 0)
        delay.assert_not_called()

    @override_settings(IQ_WEBHOOK_URL="")
    def test_sweep_returns_zero_without_url(self):
        IntegrationEvent.objects.create(
            event_type="order.paid", payload={"event_id": "e"}
        )
        with patch("shop.tasks.requests.post") as post:
            self.assertEqual(deliver_integration_events(), 0)
        post.assert_not_called()


@override_settings(IQ_WEBHOOK_URL=URL, IQ_WEBHOOK_SECRET=SECRET)
class PaidWebhookEmitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="emit_user")
        UserProfile.objects.create(user=self.user)
        self.product = make_product(stock=10)
        self.order = Order.objects.create(
            user=self.user,
            stripe_payment_session_id="cs_emit",
            delivery_type="Standard",
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            base_total=Decimal("10.00"),
        )

    def post_paid(self):
        event = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_emit", "payment_status": "paid"}},
        }
        with patch("stripe.Webhook.construct_event", return_value=event), patch(
            "stripe.checkout.Session.retrieve",
            return_value=Mock(id="cs_emit", payment_status="paid"),
        ), patch("shop.tasks.deliver_integration_event.delay"):
            return self.client.post(
                reverse("stripe-webhook"),
                data=json.dumps(event),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="dummy_signature",
            )

    def test_paid_webhook_emits_order_paid(self):
        self.assertEqual(self.post_paid().status_code, 200)
        event = IntegrationEvent.objects.get()
        self.assertEqual(event.event_type, "order.paid")
        self.assertEqual(event.direction, "out")
        self.assertEqual(
            event.payload["data"],
            {
                "order_id": str(self.order.order_id),
                "items": [
                    {
                        "product_id": str(self.product.product_id),
                        "quantity": 2,
                        "unit_price": "5.00",
                    }
                ],
            },
        )

    def test_duplicate_paid_webhook_emits_once(self):
        self.assertEqual(self.post_paid().status_code, 200)
        self.assertEqual(self.post_paid().status_code, 200)
        self.assertEqual(IntegrationEvent.objects.count(), 1)


def fake_response(status_code):
    response = Mock()
    response.status_code = status_code
    response.text = "body"
    return response


@override_settings(IQ_WEBHOOK_URL=URL, IQ_WEBHOOK_SECRET=SECRET)
class DeliveryTests(TestCase):
    def setUp(self):
        with patch("shop.tasks.deliver_integration_event.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                self.event = emit("order.paid", {"order_id": "x"})

    def test_success_marks_delivered_and_signs_exact_body(self):
        with patch("shop.tasks.requests.post", return_value=fake_response(200)) as post:
            self.assertTrue(deliver_integration_event(self.event.pk))
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, "delivered")
        args, kwargs = post.call_args
        self.assertEqual(args[0], URL)
        self.assertEqual(kwargs["timeout"], 10)
        body = kwargs["data"]
        self.assertIsInstance(body, bytes)
        self.assertEqual(
            body,
            json.dumps(
                self.event.payload, separators=(",", ":"), sort_keys=True
            ).encode(),
        )
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertTrue(
            signing.verify(SECRET, body, kwargs["headers"]["X-Integration-Signature"])
        )

    def test_failed_delivery_backs_off(self):
        with patch("shop.tasks.requests.post", return_value=fake_response(500)):
            self.assertFalse(deliver_integration_event(self.event.pk))
        self.event.refresh_from_db()
        self.assertEqual(self.event.attempts, 1)
        self.assertEqual(self.event.status, "pending")
        self.assertGreater(self.event.next_attempt_at, timezone.now())
        self.assertIn("500", self.event.last_error)

    def test_exception_counts_as_failed_attempt(self):
        with patch(
            "shop.tasks.requests.post", side_effect=requests.ConnectionError("down")
        ):
            self.assertFalse(deliver_integration_event(self.event.pk))
        self.event.refresh_from_db()
        self.assertEqual(self.event.attempts, 1)
        self.assertEqual(self.event.status, "pending")
        self.assertNotIn(SECRET, self.event.last_error)

    def test_becomes_failed_after_20_attempts(self):
        IntegrationEvent.objects.filter(pk=self.event.pk).update(attempts=19)
        with patch("shop.tasks.requests.post", return_value=fake_response(500)):
            deliver_integration_event(self.event.pk)
        self.event.refresh_from_db()
        self.assertEqual(self.event.attempts, 20)
        self.assertEqual(self.event.status, "failed")

    def test_delivered_event_not_resent(self):
        with patch("shop.tasks.requests.post", return_value=fake_response(200)) as post:
            deliver_integration_event(self.event.pk)
            deliver_integration_event(self.event.pk)
            self.assertEqual(deliver_integration_events(), 0)
        self.assertEqual(post.call_count, 1)

    def test_not_yet_due_is_skipped(self):
        IntegrationEvent.objects.filter(pk=self.event.pk).update(
            next_attempt_at=timezone.now() + timedelta(minutes=5)
        )
        with patch("shop.tasks.requests.post") as post:
            self.assertFalse(deliver_integration_event(self.event.pk))
            self.assertEqual(deliver_integration_events(), 0)
        post.assert_not_called()

    def test_sweep_delivers_due_pending_outbound_only(self):
        inbound = IntegrationEvent.objects.create(
            event_type="x", direction="in", payload={"event_id": "i"}
        )
        with patch("shop.tasks.requests.post", return_value=fake_response(204)) as post:
            self.assertEqual(deliver_integration_events(), 1)
            self.assertFalse(deliver_integration_event(inbound.pk))
        self.assertEqual(post.call_count, 1)
        inbound.refresh_from_db()
        self.assertEqual(inbound.status, "pending")
