"""rewards/models.py"""
import uuid
import random
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_barcode_number() -> str:
    """
    Generate a unique 13-digit numeric barcode.
    Format: 299 (loyalty prefix) + 9 random digits + 1 EAN-13 check digit.
    Retries until a value that doesn't already exist in the DB is found.
    """
    def _checksum(digits: str) -> int:
        total = sum(
            int(d) * (1 if i % 2 == 0 else 3)
            for i, d in enumerate(digits)
        )
        return (10 - (total % 10)) % 10

    while True:
        body = "299" + "".join(str(random.randint(0, 9)) for _ in range(9))
        number = body + str(_checksum(body))
        try:
            if not LoyaltyAccount.objects.filter(barcode_number=number).exists():
                return number
        except Exception:
            return number


# ---------------------------------------------------------------------------
# LoyaltyConfig  (singleton — only row with pk=1 ever exists)
# ---------------------------------------------------------------------------

class LoyaltyConfig(models.Model):
    """
    Global configuration for the loyalty programme.
    Edited via Django Admin — one row only (pk is forced to 1).

    Earning  : points_per_pound   — points earned per £1 spent
    Redeeming: point_value_gbp    — GBP value of 1 point at redemption

    Example  : points_per_pound=10, point_value_gbp=0.01
               → spend £5  → earn 50 pts
               → redeem 50 pts → worth £0.50
    """
    points_per_pound = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Points awarded per £1 of spend (e.g. 1.00 = 1 pt per £1).",
    )
    point_value_gbp = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=Decimal("0.0100"),
        validators=[MinValueValidator(Decimal("0.0001"))],
        help_text="Value of 1 point in GBP when redeeming (e.g. 0.01 = 1p per point).",
    )
    min_points_to_redeem = models.PositiveIntegerField(
        default=100,
        help_text="Minimum point balance required before a redemption is allowed.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Disable to pause the entire loyalty programme (no points will be awarded).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "rewards"
        verbose_name = "Loyalty Configuration"
        verbose_name_plural = "Loyalty Configuration"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # Prevent accidental deletion

    @classmethod
    def get_config(cls) -> "LoyaltyConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self) -> str:
        return (
            f"Loyalty Config — "
            f"{self.points_per_pound} pts/£  |  "
            f"£{self.point_value_gbp:.4f}/pt  |  "
            f"min redeem: {self.min_points_to_redeem} pts"
        )


# ---------------------------------------------------------------------------
# LoyaltyAccount  (one per UserProfile, auto-created via signal)
# ---------------------------------------------------------------------------

class LoyaltyAccount(models.Model):
    account_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    user_profile = models.OneToOneField(
        "shop.UserProfile",
        on_delete=models.CASCADE,
        related_name="loyalty_account",
    )

    points_balance = models.IntegerField(default=0)
    total_points_earned = models.IntegerField(default=0)
    total_points_redeemed = models.IntegerField(default=0)

    # 13-digit numeric barcode (EAN-13 compatible, Code-128 scannable)
    barcode_number = models.CharField(max_length=20, unique=True, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "rewards"
        verbose_name = "Loyalty Account"
        verbose_name_plural = "Loyalty Accounts"

    def save(self, *args, **kwargs):
        if not self.barcode_number:
            self.barcode_number = _generate_barcode_number()
        super().save(*args, **kwargs)

    @property
    def points_gbp_value(self) -> Decimal:
        """Current balance expressed in GBP (for display)."""
        config = LoyaltyConfig.get_config()
        return Decimal(str(self.points_balance)) * config.point_value_gbp

    @property
    def tier(self) -> str:
        """Tier label based on lifetime earned points."""
        earned = self.total_points_earned
        if earned >= 5000:
            return "Gold"
        if earned >= 2000:
            return "Silver"
        return "Bronze"

    def __str__(self) -> str:
        return f"[{self.tier}] {self.user_profile.fullname} — {self.points_balance} pts"


# ---------------------------------------------------------------------------
# LoyaltyTransaction  (immutable audit log of every points movement)
# ---------------------------------------------------------------------------

class LoyaltyTransaction(models.Model):
    class TransactionType(models.TextChoices):
        EARN_ONLINE  = "EARN_ONLINE",  "Earned – Online Order"
        EARN_INSTORE = "EARN_INSTORE", "Earned – In-Store"
        REDEEM       = "REDEEM",       "Redeemed"
        ADJUSTMENT   = "ADJUSTMENT",   "Manual Adjustment"
        EXPIRY       = "EXPIRY",       "Points Expired"

    transaction_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    loyalty_account = models.ForeignKey(
        LoyaltyAccount,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)

    # Positive = earn, negative = redeem / expiry / adjustment
    points = models.IntegerField()

    order_amount_gbp = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    order_reference = models.CharField(max_length=120, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True)

    # Balance snapshot after this transaction
    balance_after = models.IntegerField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "rewards"
        ordering = ["-created_at"]
        verbose_name = "Loyalty Transaction"
        verbose_name_plural = "Loyalty Transactions"

    def __str__(self) -> str:
        sign = "+" if self.points >= 0 else ""
        return (
            f"{self.get_transaction_type_display()}  "
            f"{sign}{self.points} pts  "
            f"→ balance: {self.balance_after}  "
            f"[{self.loyalty_account.user_profile.fullname}]"
        )