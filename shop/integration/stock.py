"""Apply Supply Chain IQ's stock.changed snapshots to the shop's stock."""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation

from django.db.models import Sum

from shop.models import OrderItem, OrderPaymentStatus
from shop.stock import lock_products

logger = logging.getLogger(__name__)

# Product.price is max_digits=5, decimal_places=2.
MAX_PRICE = Decimal("999.99")
NO_PRICE = object()  # the item carries no price (IQ is not pushing prices)
BAD_PRICE = object()


def _price(item):
    if "price" not in item:
        return NO_PRICE
    try:
        price = Decimal(item["price"]) if isinstance(item["price"], str) else None
    except InvalidOperation:
        price = None
    if price is None or not price.is_finite() or price != price.quantize(Decimal("0.01")) or not 0 < price <= MAX_PRICE:
        return BAD_PRICE
    return price.quantize(Decimal("0.01"))


def _valid_items(items):
    """``{product_id: (online_available, version, price)}``, keeping the newest version; and how many were invalid."""
    valid, invalid = {}, 0
    for item in items:
        try:
            product_id = str(uuid.UUID(str(item["product_id"])))
            available, version = item["online_available"], item["version"]
        except (TypeError, KeyError, ValueError, AttributeError):
            invalid += 1
            continue
        if type(available) is not int or available < 0 or type(version) is not int or version < 1:
            invalid += 1
            continue
        if product_id not in valid or version > valid[product_id][1]:
            valid[product_id] = (available, version, _price(item))
    return valid, invalid


def held_for_unpaid_checkouts(product):
    """Units already taken out of stock_quantity for checkouts that are not paid (IQ has not heard of them)."""
    return (
        OrderItem.objects.filter(
            product=product,
            order__stock_reserved=True,
            order__stripe_payment_status=OrderPaymentStatus.UNPAID.value,
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )


def apply_stock_changed(data):
    """
    ``{"items": [{"product_id", "online_available", "version", "price"?}]}``: set each product's stock (and
    price, when IQ sends one) from IQ's figures.

    A snapshot older than (or the same as) the product's ``iq_stock_version`` is skipped, so late or
    repeated deliveries cannot move stock backwards. stock_quantity = IQ's figure minus units held for
    unpaid checkouts, never below zero. A price outside 0 < p <= 999.99 (the column's cap) is refused for that
    item only: the stock still applies and the product is listed in ``price_rejected``. Must run inside
    ``transaction.atomic()`` (rows are locked).
    """
    items = data.get("items")
    if not isinstance(items, list):
        return {"status": "ignored"}
    valid, invalid = _valid_items(items)
    if not valid:
        return {"status": "ignored"}

    products = lock_products(valid)
    unknown = sorted(product_id for product_id in valid if product_id not in products)
    stale, price_rejected = 0, []
    for product_id, (available, version, price) in valid.items():
        product = products.get(product_id)
        if product is None:
            continue
        if version <= product.iq_stock_version:
            stale += 1
            continue
        product.iq_available = available
        product.iq_stock_version = version
        product.iq_managed = True
        product.stock_quantity = max(available - held_for_unpaid_checkouts(product), 0)
        fields = ["iq_available", "iq_stock_version", "iq_managed", "stock_quantity"]
        if price is BAD_PRICE:
            price_rejected.append(product_id)
        elif price is not NO_PRICE:
            product.price = price
            product.iq_price_managed = True
            fields += ["price", "iq_price_managed"]
        product.save(update_fields=fields)
    if price_rejected:
        logger.warning("Refused Supply Chain IQ prices for %s product(s): %s", len(price_rejected), price_rejected)
    status = "partial" if unknown or invalid or price_rejected else "applied"
    return {"status": status, "unknown_products": unknown, "stale": stale, "price_rejected": sorted(price_rejected)}
