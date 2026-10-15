from django.test import TestCase

from shop.integration import signing
from shop.integration.models import IntegrationEvent, emit

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
