"""rewards/signals.py"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db.models.signals import post_save
from django.dispatch import Signal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom signal — dispatch this from your order/payment code
#
# Usage (wherever you mark an order as paid):
#
#   from rewards.signals import order_paid
#   order_paid.send(
#       sender=Order,
#       order_reference="ORD-12345",
#       user_profile=order.user.userprofile,
#       order_amount=order.total,   # Decimal
#   )
# ---------------------------------------------------------------------------

order_paid = Signal()


def _on_order_paid(sender, order_reference, user_profile, order_amount, **kwargs):
    """Award loyalty points when an order transitions to 'paid'."""
    from .services import award_points_for_online_order

    try:
        tx = award_points_for_online_order(
            user_profile=user_profile,
            order_amount=Decimal(str(order_amount)),
            order_reference=str(order_reference),
        )
        if tx:
            logger.info(
                "Awarded %d pts to user_profile_id=%s for order %s",
                tx.points,
                user_profile.user_profile_id,
                order_reference,
            )
        else:
            logger.debug(
                "No points awarded for order %s (already processed or £0).",
                order_reference,
            )
    except Exception as exc:
        # Never let loyalty errors block the checkout flow
        logger.exception(
            "Failed to award loyalty points for order %s: %s",
            order_reference,
            exc,
        )


def _on_user_profile_saved(sender, instance, created, **kwargs):
    """Auto-create a LoyaltyAccount (+ barcode) for every new UserProfile."""
    if not created:
        return
    from .models import LoyaltyAccount
    account, new = LoyaltyAccount.objects.get_or_create(user_profile=instance)
    if new:
        logger.info(
            "LoyaltyAccount created for user_profile_id=%s  barcode=%s",
            instance.user_profile_id,
            account.barcode_number,
        )


def connect_signals():
    """
    Called from RewardsConfig.ready() in apps.py.
    Connects signals after all apps are loaded to avoid circular imports.
    """
    from django.apps import apps

    # Wire order_paid signal
    order_paid.connect(_on_order_paid)

    # Wire UserProfile post_save → auto-create loyalty account
    UserProfile = apps.get_model("shop", "UserProfile")
    post_save.connect(_on_user_profile_saved, sender=UserProfile)