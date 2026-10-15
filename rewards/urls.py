"""rewards/urls.py"""
from django.urls import path
from .views import (
    AdminLoyaltyAccountDetailView,
    InstoreAwardView,
    LoyaltyConfigView,
    MyLoyaltyAccountView,
    MyLoyaltyBarcodeView,
    RedeemPointsView,
)

app_name = "rewards"

urlpatterns = [
    path("api/account/",         MyLoyaltyAccountView.as_view(),  name="my-account"),
    path("api/account/barcode/", MyLoyaltyBarcodeView.as_view(),  name="my-barcode"),
    path("api/account/redeem/",  RedeemPointsView.as_view(),      name="redeem"),

    # Till staff — in-store award
    path("api/instore/award/",   InstoreAwardView.as_view(),      name="instore-award"),

    # Staff — look up any customer by barcode
    path(
        "api/admin/accounts/<str:barcode_number>/",
        AdminLoyaltyAccountDetailView.as_view(),
        name="admin-account-detail",
    ),

    # Programme config
    path("api/config/",          LoyaltyConfigView.as_view(),     name="config"),
]