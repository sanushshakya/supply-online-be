"""Stock checking, row locking, reservation and release.

Stock is reserved (decremented) when a temporary order is created and released if
that order is deleted, expires or is abandoned. Callers that reserve or release
must be inside, or are wrapped by, `transaction.atomic()`.
"""

import logging

from django.db import transaction

from shop.exceptions import InsufficientStockError
from shop.models import Product

logger = logging.getLogger(__name__)


def shortfall(product, requested):
    """Return the contract item dict if `requested` exceeds stock, else None."""
    available = product.stock_quantity if product.is_active else 0
    if requested <= available:
        return None
    return {
        "product_id": str(product.product_id),
        "name": product.name,
        "requested": requested,
        "available": available,
    }


def lock_products(product_ids):
    """Lock product rows (ordered by pk to avoid deadlocks), inactive ones included.

    Returns {str(product_id): Product}. Must be called inside transaction.atomic().
    """
    products = (
        Product.all_objects.select_for_update()
        .filter(product_id__in=list(product_ids))
        .order_by("pk")
    )
    return {str(p.product_id): p for p in products}


def _shortfalls(quantities, products):
    items = []
    for product_id, requested in quantities.items():
        product = products.get(product_id)
        if product is None:
            continue
        item = shortfall(product, requested)
        if item:
            items.append(item)
    return items


def assert_cart_stock(cart, lock=False):
    """Raise InsufficientStockError listing every cart item that exceeds DB stock."""
    quantities = {}
    for cart_item in cart.cart_items.select_related("product"):
        key = str(cart_item.product.product_id)
        quantities[key] = quantities.get(key, 0) + cart_item.quantity
    if lock:
        products = lock_products(quantities)
    else:
        products = {
            str(p.product_id): p
            for p in Product.all_objects.filter(product_id__in=list(quantities))
        }
    items = _shortfalls(quantities, products)
    if items:
        raise InsufficientStockError(items)


def _order_quantities(order):
    quantities = {}
    for order_item in order.order_items_from_order.select_related("product"):
        key = str(order_item.product.product_id)
        quantities[key] = quantities.get(key, 0) + order_item.quantity
    return quantities


def reserve_order_stock(order):
    """Atomically check and decrement stock for an order's items."""
    with transaction.atomic():
        quantities = _order_quantities(order)
        products = lock_products(quantities)
        items = _shortfalls(quantities, products)
        if items:
            raise InsufficientStockError(items)
        for product_id, quantity in quantities.items():
            product = products[product_id]
            product.stock_quantity -= quantity
            product.save(update_fields=["stock_quantity"])
        order.stock_reserved = True
        order.save(update_fields=["stock_reserved"])


def release_order_stock(order):
    """Return a reserved order's quantities to stock. No-op if not reserved."""
    if not order.stock_reserved:
        return
    with transaction.atomic():
        quantities = _order_quantities(order)
        products = lock_products(quantities)
        for product_id, quantity in quantities.items():
            product = products.get(product_id)
            if product is None:
                continue
            product.stock_quantity += quantity
            product.save(update_fields=["stock_quantity"])
        order.stock_reserved = False
        order.save(update_fields=["stock_reserved"])


def commit_paid_order_stock(order):
    """Decrement stock for a paid order, never raising on a shortfall.

    Each product is decremented by min(requested, available) under a row lock and
    the uncovered remainder is returned as shortfall dicts (and logged). No-op
    returning [] if the order's stock was already reserved. Must be called inside
    transaction.atomic(), together with the paid-status update.
    """
    if order.stock_reserved:
        return []
    quantities = _order_quantities(order)
    products = lock_products(quantities)
    items = _shortfalls(quantities, products)
    for product_id, requested in quantities.items():
        product = products.get(product_id)
        if product is None:
            continue
        available = product.stock_quantity if product.is_active else 0
        take = min(requested, max(available, 0))
        if take:
            product.stock_quantity -= take
            product.save(update_fields=["stock_quantity"])
    for item in items:
        logger.warning(
            "Order %s paid with insufficient stock: %s", order.order_id, item
        )
    return items
