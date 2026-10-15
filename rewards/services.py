"""rewards/services.py"""
from __future__ import annotations

import io
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from django.db import transaction as db_tx

from .models import LoyaltyAccount, LoyaltyConfig, LoyaltyTransaction


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------

def get_or_create_loyalty_account(user_profile) -> tuple[LoyaltyAccount, bool]:
    return LoyaltyAccount.objects.get_or_create(user_profile=user_profile)


# ---------------------------------------------------------------------------
# Points calculation
# ---------------------------------------------------------------------------

def calculate_points(amount_gbp: Decimal) -> int:
    """
    Convert a spend amount to loyalty points using the current config.
    Returns 0 if the programme is paused.
    Formula: floor(amount_gbp × points_per_pound)
    """
    config = LoyaltyConfig.get_config()
    if not config.is_active:
        return 0
    raw = Decimal(str(amount_gbp)) * config.points_per_pound
    return int(raw.to_integral_value(rounding=ROUND_DOWN))


def points_to_gbp(points: int) -> Decimal:
    """Convert a point count to its GBP redemption value."""
    config = LoyaltyConfig.get_config()
    return (Decimal(str(points)) * config.point_value_gbp).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Earning points — online orders
# ---------------------------------------------------------------------------

def award_points_for_online_order(
    user_profile,
    order_amount: Decimal,
    order_reference: str,
) -> Optional[LoyaltyTransaction]:
    """
    Called when an online order transitions to 'paid'.
    Idempotent: duplicate calls with the same order_reference are ignored.
    """
    if LoyaltyTransaction.objects.filter(
        loyalty_account__user_profile=user_profile,
        order_reference=order_reference,
        transaction_type=LoyaltyTransaction.TransactionType.EARN_ONLINE,
    ).exists():
        return None

    points = calculate_points(order_amount)
    if points <= 0:
        return None

    with db_tx.atomic():
        account, _ = get_or_create_loyalty_account(user_profile)
        account.points_balance += points
        account.total_points_earned += points
        account.save(update_fields=["points_balance", "total_points_earned", "updated_at"])

        return LoyaltyTransaction.objects.create(
            loyalty_account=account,
            transaction_type=LoyaltyTransaction.TransactionType.EARN_ONLINE,
            points=points,
            order_amount_gbp=order_amount,
            order_reference=order_reference,
            description=f"Online order #{order_reference}  (£{order_amount:.2f})",
            balance_after=account.points_balance,
        )


# ---------------------------------------------------------------------------
# Earning points — in-store via barcode scan
# ---------------------------------------------------------------------------

def award_points_for_instore(
    barcode_number: str,
    order_amount: Decimal,
    order_reference: Optional[str] = None,
) -> LoyaltyTransaction:
    """
    Called by till staff when they scan a customer's loyalty barcode.
    Raises ValueError for unknown / inactive barcodes.
    """
    try:
        account = (
            LoyaltyAccount.objects
            .select_related("user_profile")
            .get(barcode_number=barcode_number, is_active=True)
        )
    except LoyaltyAccount.DoesNotExist:
        raise ValueError(
            f"No active loyalty account found for barcode '{barcode_number}'."
        )

    points = calculate_points(order_amount)
    if points <= 0:
        raise ValueError("No points to award — loyalty programme may be paused.")

    with db_tx.atomic():
        account.points_balance += points
        account.total_points_earned += points
        account.save(update_fields=["points_balance", "total_points_earned", "updated_at"])

        return LoyaltyTransaction.objects.create(
            loyalty_account=account,
            transaction_type=LoyaltyTransaction.TransactionType.EARN_INSTORE,
            points=points,
            order_amount_gbp=order_amount,
            order_reference=order_reference,
            description=f"In-store purchase  (£{order_amount:.2f})",
            balance_after=account.points_balance,
        )


# ---------------------------------------------------------------------------
# Redeeming points
# ---------------------------------------------------------------------------

def redeem_points(
    user_profile,
    points_to_redeem: int,
) -> tuple[LoyaltyTransaction, Decimal]:
    """
    Deduct points and return (transaction, gbp_value).
    Raises ValueError if balance or minimum threshold not met.
    """
    config = LoyaltyConfig.get_config()
    account, _ = get_or_create_loyalty_account(user_profile)

    if points_to_redeem < config.min_points_to_redeem:
        raise ValueError(
            f"Minimum {config.min_points_to_redeem} points required to redeem "
            f"(attempted: {points_to_redeem})."
        )
    if account.points_balance < points_to_redeem:
        raise ValueError(
            f"Insufficient points. Balance: {account.points_balance}, "
            f"requested: {points_to_redeem}."
        )

    gbp_value = points_to_gbp(points_to_redeem)

    with db_tx.atomic():
        account.points_balance -= points_to_redeem
        account.total_points_redeemed += points_to_redeem
        account.save(update_fields=["points_balance", "total_points_redeemed", "updated_at"])

        tx = LoyaltyTransaction.objects.create(
            loyalty_account=account,
            transaction_type=LoyaltyTransaction.TransactionType.REDEEM,
            points=-points_to_redeem,
            description=f"Redeemed {points_to_redeem} pts  → £{gbp_value:.2f} discount",
            balance_after=account.points_balance,
        )

    return tx, gbp_value


# ---------------------------------------------------------------------------
# Manual adjustment (admin / CS use)
# ---------------------------------------------------------------------------

def manual_adjustment(
    user_profile,
    points_delta: int,
    reason: str,
) -> LoyaltyTransaction:
    """Add or remove points with a free-text reason (positive or negative delta)."""
    with db_tx.atomic():
        account, _ = get_or_create_loyalty_account(user_profile)
        account.points_balance += points_delta
        if points_delta > 0:
            account.total_points_earned += points_delta
        else:
            account.total_points_redeemed += abs(points_delta)
        account.save(update_fields=[
            "points_balance", "total_points_earned", "total_points_redeemed", "updated_at"
        ])

        return LoyaltyTransaction.objects.create(
            loyalty_account=account,
            transaction_type=LoyaltyTransaction.TransactionType.ADJUSTMENT,
            points=points_delta,
            description=reason,
            balance_after=account.points_balance,
        )


# ---------------------------------------------------------------------------
# Barcode image generation (SVG — no Pillow required)
# ---------------------------------------------------------------------------

def generate_barcode_svg(barcode_number: str) -> str:
    import barcode
    from barcode.writer import SVGWriter
    from io import BytesIO

    ean = barcode.get("ean13", barcode_number, writer=SVGWriter())
    buffer = BytesIO()
    ean.write(buffer)
    svg_str = buffer.getvalue().decode("utf-8")   # ← the fix

    # Strip XML declaration so React can inject it as innerHTML cleanly
    if svg_str.startswith("<?xml"):
        svg_str = svg_str[svg_str.index("<svg"):]

    return svg_str