"""rewards/views.py"""
from __future__ import annotations

from decimal import Decimal

from django.http import HttpResponse
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LoyaltyAccount, LoyaltyConfig
from .serializers import (
    InstoreAwardSerializer,
    LoyaltyAccountSerializer,
    LoyaltyConfigSerializer,
    RedeemPointsSerializer,
)
from .services import (
    award_points_for_instore,
    generate_barcode_svg,
    get_or_create_loyalty_account,
    redeem_points,
)


class IsStaffOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and (request.user.is_staff or request.user.is_superuser))


# ---------------------------------------------------------------------------
# Customer — own account
# ---------------------------------------------------------------------------

class MyLoyaltyAccountView(APIView):
    """GET /api/rewards/account/  — authenticated customer's loyalty account."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        account, _ = get_or_create_loyalty_account(request.user.userprofile)
        return Response(LoyaltyAccountSerializer(account).data)


class MyLoyaltyBarcodeView(APIView):
    """GET /api/rewards/account/barcode/  — returns barcode as inline SVG."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        account, _ = get_or_create_loyalty_account(request.user.userprofile)
        try:
            svg = generate_barcode_svg(account.barcode_number)
            return HttpResponse(svg, content_type="image/svg+xml")
        except ImportError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_501_NOT_IMPLEMENTED)


class RedeemPointsView(APIView):
    """POST /api/rewards/account/redeem/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = RedeemPointsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tx, gbp_value = redeem_points(
                user_profile=request.user.userprofile,
                points_to_redeem=serializer.validated_data["points_to_redeem"],
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "message": f"Successfully redeemed {abs(tx.points)} points (£{gbp_value:.2f}).",
            "points_redeemed": abs(tx.points),
            "gbp_value": str(gbp_value),
            "new_balance": tx.balance_after,
            "transaction_id": str(tx.transaction_id),
        })


# ---------------------------------------------------------------------------
# Staff — in-store award endpoint
# ---------------------------------------------------------------------------

class InstoreAwardView(APIView):
    """POST /api/rewards/instore/award/  — staff only."""
    permission_classes = [IsStaffOrAdmin]

    def post(self, request):
        serializer = InstoreAwardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tx = award_points_for_instore(
                barcode_number=serializer.validated_data["barcode_number"],
                order_amount=Decimal(str(serializer.validated_data["order_amount"])),
                order_reference=serializer.validated_data.get("order_reference"),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "message": f"Awarded {tx.points} points.",
            "points_awarded": tx.points,
            "new_balance": tx.balance_after,
            "customer": tx.loyalty_account.user_profile.fullname,
            "transaction_id": str(tx.transaction_id),
        })


# ---------------------------------------------------------------------------
# Admin — look up any customer's account by barcode
# ---------------------------------------------------------------------------

class AdminLoyaltyAccountDetailView(generics.RetrieveAPIView):
    """GET /api/rewards/admin/accounts/<barcode_number>/  — staff only."""
    permission_classes = [IsStaffOrAdmin]
    serializer_class = LoyaltyAccountSerializer
    queryset = LoyaltyAccount.objects.select_related("user_profile").all()
    lookup_field = "barcode_number"


# ---------------------------------------------------------------------------
# Config — read (all authenticated) / write (staff only)
# ---------------------------------------------------------------------------

class LoyaltyConfigView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.IsAuthenticated()]
        return [IsStaffOrAdmin()]

    def get(self, request):
        return Response(LoyaltyConfigSerializer(LoyaltyConfig.get_config()).data)

    def put(self, request):
        config = LoyaltyConfig.get_config()
        serializer = LoyaltyConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)