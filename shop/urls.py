from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions
from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
    CategoryViewSet,
    SubCategoryViewSet,
    SupplierViewSet,
    ProductViewSet,
    UserProfileViewSet,
    OrderViewSet,
    OrderItemViewSet,
    CartViewSet,
    CartItemViewSet,
    LikeViewSet,
    ReviewViewSet,
    dashboard,
    order_management,
    product_management,
    order_details,
    StaffLoginView,
    StaffLogoutView,
    qr_login,
    update_product_by_product_id,
    add_product,
    complete_order,
    get_notifications,
    notification_details,
    PromotionViewSet,
    fetch_product_details,
    get_sub_categories,
    add_category,
    add_subcategory,
    add_product_department,
    fetch_product_by_barcode,
    link_product_with_box_product,
    export_products_pdf,
    export_products_csv,
    export_products_excel,
    csrf_token_view,
    stripe_webhook,
    BannerViewSet,
    MiniAdViewSet,
    ProductDepartmentViewSet,
    DeliveryOptionViewSet,
    update_order_status,
    dispatch_order,
    add_product_stock,
    upload_epos_data_dump,
    download_order_info_dump_for_epos,
    update_products_in_batch_by_barcodes,
    update_product_price_by_barcode,
    fetch_marketing_opted_users,
    approve_product,
    superadmin_authenticate,
    fetch_notifications,
    sync_data_with_epos,
    export_orders_csv,
    save_subscription,
    delete_subscription,
    send_notification,
    instore_loyalty_award,
)

router = DefaultRouter()
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"subcategories", SubCategoryViewSet, basename="subcategory")
router.register(
    r"productdepartments", ProductDepartmentViewSet, basename="productdepartment"
)
router.register(r"suppliers", SupplierViewSet, basename="supplier")
router.register(r"products", ProductViewSet, basename="product")
router.register(r"users", UserProfileViewSet, basename="userprofile")
router.register(r"orders", OrderViewSet, basename="order")
router.register(r"orderitems", OrderItemViewSet, basename="orderitem")
router.register(r"carts", CartViewSet, basename="cart")
router.register(r"cartitems", CartItemViewSet, basename="cartitem")
router.register(r"likes", LikeViewSet, basename="like")
router.register(r"reviews", ReviewViewSet, basename="review")
router.register(r"promotions", PromotionViewSet, basename="promotion")
router.register(r"banners", BannerViewSet, basename="banner")
router.register(r"miniads", MiniAdViewSet, basename="miniad")
router.register(r"deliveryoptions", DeliveryOptionViewSet, basename="deliveryoption")

schema_view = get_schema_view(
    openapi.Info(
        title="Your API",
        default_version="v1",
        description="Your API description",
        terms_of_service="https://www.example.com/policies/terms/",
        contact=openapi.Contact(email="contact@example.com"),
        license=openapi.License(name="MIT License"),
    ),
    public=False,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    path("api/", include(router.urls)),
    path('api/notifications/save-subscription/', save_subscription),
    path('api/notifications/delete-subscription/', delete_subscription),
    path('api/notifications/send/', send_notification),
    path("dashboard/", dashboard, name="dashboard"),
    path("order-management/", order_management, name="order_management"),
    path('order-management/export/', export_orders_csv, name='export_orders_csv'),
    path("product-management/", product_management, name="product_management"),
    path(
        "product-management/<slug:category_slug>",
        product_management,
        name="product_management_by_category",
    ),
    path("order-details/<str:order_id>/", order_details, name="order_details"),
    path(
        "login/",
        StaffLoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("qr-login/", qr_login, name="qr_login"),
    path("logout/", StaffLogoutView.as_view(), name="logout"),
    path(
        "products/<str:product_id>/update/",
        update_product_by_product_id,
        name="update_product_by_product_id",
    ),
    path("products/add/", add_product, name="add_product"),
    path("products/add-stock/", add_product_stock, name="add_product_stock"),
    path("products/fetch-product/", fetch_product_details, name="fetch_product"),
    path("products/get-sub-categories/", get_sub_categories, name="get_sub_categories"),
    path("products/add-category/", add_category, name="add_category"),
    path(
        "products/add-product-department/",
        add_product_department,
        name="add_department",
    ),
    path("products/add-subcategory/", add_subcategory, name="add_subcategory"),
    path(
        "products/fetch-product-by-barcode/",
        fetch_product_by_barcode,
        name="fetch_product_by_barcode",
    ),
    path(
        "products/link-product-with-box-product",
        link_product_with_box_product,
        name="link_product_with_box_product",
    ),
    path("products/export-pdf/", export_products_pdf, name="export_products_pdf"),
    path("products/export-csv/", export_products_csv, name="export_products_csv"),
    path("products/export-excel/", export_products_excel, name="export_products_excel"),
    path("products/sync-with-epos/", sync_data_with_epos, name="sync_data_with_epos"),
    path("products/<str:product_id>/approve/", approve_product, name="approve-product"),
    path("order/<str:order_id>/complete/", complete_order, name="complete_order"),
    path("order/<str:order_id>/dispatch/", dispatch_order, name="dispatch_order"),
    path("notifications/", get_notifications, name="notifications"),
    path(
        "notification-details/<int:id>/",
        notification_details,
        name="notification_details",
    ),
    path(
        "swagger/",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
    path("csrf-token/", csrf_token_view, name="csrf-token"),
    path("stripe-webhook/", stripe_webhook, name="stripe-webhook"),
    path(
        "orders/update-order-status/", update_order_status, name="update_order_status"
    ),
    path("upload-epos-data-dump/", upload_epos_data_dump, name="upload_epos_data_dump"),
    path(
        "download-order-info-dump-for-epos/",
        download_order_info_dump_for_epos,
        name="download_order_info_dump_for_epos",
    ),
    path(
        "update-products-in-batch-by-barcodes/",
        update_products_in_batch_by_barcodes,
        name="update_products_in_batch_by_barcodes",
    ),
    path(
        "update-product-price-by-barcode/",
        update_product_price_by_barcode,
        name="update_product_price_by_barcode",
    ),
    path(
        "users/fetch-marketing-opted-users/",
        fetch_marketing_opted_users,
        name="fetch_marketing_opted_users",
    ),
    path("superadmin-auth/", superadmin_authenticate, name="superadmin_auth"),
    path("fetch-notifications/", fetch_notifications, name="fetch_notifications"),
    path("loyalty/instore-award/", instore_loyalty_award, name="instore_loyalty_award")
]
