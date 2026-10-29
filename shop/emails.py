"""
Customer emails, rendered from templates in ``shop/templates/shop/emails/``.

Each email is a pair: ``<name>.html`` (autoescaped, so a customer's name or a tracking id can never add markup)
and ``<name>.txt`` (plain text, autoescape off). Never build email HTML with f-strings, not even inside format_html.
"""

from django.conf import settings
from django.template.loader import render_to_string

SHOP = {
    "name": "M18 Foods",
    "contact_email": "contactus@m18foods.co.uk",
    "address": "Unit 6, St James Centre East Rd, Temple Fields, Harlow CM20 2SX, United Kingdom",
    "currency": "£",
}


def render_email(name, **context):
    """Return ``(text, html)`` for the email ``name`` with ``context`` plus the shop's details as ``shop``."""
    context = {
        "shop": {
            **SHOP,
            "privacy_url": f"{settings.DOMAIN_BASE_URL}/policy",
            "terms_url": f"{settings.DOMAIN_BASE_URL}/terms-of-service",
        },
        **context,
    }
    text = render_to_string(f"shop/emails/{name}.txt", context).strip() + "\n"
    html = render_to_string(f"shop/emails/{name}.html", context)
    return text, html
