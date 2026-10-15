"""rewards/serializers.py"""
from rest_framework import serializers
from .models import LoyaltyAccount, LoyaltyConfig, LoyaltyTransaction


class LoyaltyConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoyaltyConfig
        fields = [
            "points_per_pound",
            "point_value_gbp",
            "min_points_to_redeem",
            "is_active",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


class LoyaltyTransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(
        source="get_transaction_type_display", read_only=True
    )

    class Meta:
        model = LoyaltyTransaction
        fields = [
            "transaction_id",
            "transaction_type",
            "transaction_type_display",
            "points",
            "order_amount_gbp",
            "order_reference",
            "description",
            "balance_after",
            "created_at",
        ]
        read_only_fields = fields


class LoyaltyAccountSerializer(serializers.ModelSerializer):
    """Full read-only view — includes transaction history."""
    tier = serializers.CharField(read_only=True)
    points_gbp_value = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    transactions = LoyaltyTransactionSerializer(many=True, read_only=True)

    class Meta:
        model = LoyaltyAccount
        fields = [
            "account_id",
            "points_balance",
            "total_points_earned",
            "total_points_redeemed",
            "points_gbp_value",
            "barcode_number",
            "tier",
            "is_active",
            "created_at",
            "transactions",
        ]
        read_only_fields = fields


class LoyaltyAccountSummarySerializer(serializers.ModelSerializer):
    """Lightweight — embed inside user-profile responses (no transaction list)."""
    tier = serializers.CharField(read_only=True)
    points_gbp_value = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = LoyaltyAccount
        fields = [
            "account_id",
            "points_balance",
            "points_gbp_value",
            "barcode_number",
            "tier",
            "is_active",
        ]
        read_only_fields = fields


class InstoreAwardSerializer(serializers.Serializer):
    barcode_number = serializers.CharField(max_length=20)
    order_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    order_reference = serializers.CharField(max_length=120, required=False, allow_blank=True)


class RedeemPointsSerializer(serializers.Serializer):
    points_to_redeem = serializers.IntegerField(min_value=1)

    def validate_points_to_redeem(self, value):
        config = LoyaltyConfig.get_config()
        if value < config.min_points_to_redeem:
            raise serializers.ValidationError(
                f"Minimum {config.min_points_to_redeem} points required to redeem."
            )
        return value