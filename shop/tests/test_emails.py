import datetime
import re
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from shop.emails import render_email

NASTY = "<script>alert(1)</script> & Co"
NASTY_HTML = "&lt;script&gt;alert(1)&lt;/script&gt; &amp; Co"


class FakeOrder:
    order_id = "ord-1"
    total_amount = Decimal("12.50")
    created_at = datetime.datetime(2026, 10, 29, 9, 30)


class RenderEmailTests(SimpleTestCase):
    """Customer-typed text is escaped in the HTML part and left as typed in the plain-text part."""

    emails = {
        "password_reset": {"first_name": NASTY, "link": "https://shop.example/reset?token=a&b=1"},
        "activation": {"first_name": NASTY, "link": "https://shop.example/activate?token=a&b=1"},
        "order_confirmation": {"first_name": NASTY, "order": FakeOrder()},
        "order_dispatched": {"first_name": NASTY, "order_id": "ord-1", "delivery_partner": "<b>Royal & Mail</b>",
                             "tracking_id": "<i>TR1</i>"},
    }

    def test_customer_text_is_escaped_in_html(self):
        for name, context in self.emails.items():
            with self.subTest(name):
                text, html = render_email(name, **context)
                self.assertIn(f"Hi {NASTY_HTML}", html)
                self.assertNotIn("<script>", html)
                self.assertIn("M18 Foods", html)
                self.assertIn("Privacy Policy</a>", html)  # the shop's own markup still renders

    def test_plain_text_keeps_what_was_typed_and_has_no_html(self):
        for name, context in self.emails.items():
            with self.subTest(name):
                text, html = render_email(name, **context)
                self.assertIn(f"Hi {NASTY}", text)
                self.assertNotIn("&amp;", text)
                for typed in context.values():  # what people typed stays as typed; the template adds no markup
                    if isinstance(typed, str):
                        text = text.replace(typed, "")
                self.assertNotRegex(text, r"<(br|a |b>|u>|p>)")

    def test_links_and_order_details_are_included(self):
        text, html = render_email("password_reset", **self.emails["password_reset"])
        self.assertIn("https://shop.example/reset?token=a&amp;b=1", html)
        self.assertIn("https://shop.example/reset?token=a&b=1", text)
        text, html = render_email("order_confirmation", **self.emails["order_confirmation"])
        for part in (text, html):
            self.assertIn("ord-1", part)
            self.assertIn("£12.50", part)
            self.assertIn("2026-10-29", part)
        text, html = render_email("order_dispatched", **self.emails["order_dispatched"])
        self.assertIn("&lt;b&gt;Royal &amp; Mail&lt;/b&gt;", html)
        self.assertIn("&lt;i&gt;TR1&lt;/i&gt;", html)
        self.assertIn("<i>TR1</i>", text)


class NoFStringHtmlTests(SimpleTestCase):
    def test_no_html_is_built_with_f_strings_in_email_code(self):
        source = (Path(__file__).resolve().parents[1] / "views.py").read_text()
        self.assertFalse("format_html(" in source, "views.py still builds email HTML with format_html")
        self.assertFalse(re.search(r'html_email_footer\s*=\s*f"', source))
