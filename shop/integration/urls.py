from django.urls import path

from .views import IntegrationEventView, StockSnapshotView

urlpatterns = [
    path("events/", IntegrationEventView.as_view(), name="integration-events"),
    path("stock/", StockSnapshotView.as_view(), name="integration-stock"),
]
