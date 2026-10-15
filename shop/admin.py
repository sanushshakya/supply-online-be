import csv
from decimal import Decimal
from django.http import HttpResponse, HttpResponseRedirect
from django.utils import timezone
from django.contrib import messages, admin
from django import forms
from django.contrib.admin.helpers import ActionForm
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.shortcuts import render
from shop.forms import CartItemExportActionForm
from shop.integration.models import IntegrationEvent
from .models import (
    Category,
    Supplier,
    Product,
    UserProfile,
    Order,
    OrderItem,
    Cart,
    CartItem,
    Like,
    Review,
    Notification,
    Promotion,
    SubCategory,
    Banner,
    MiniAd,
    ProductDepartment,
    FeatureFlag,
    DeliveryOption,
    TaxCategory,
    LocationInStore,
    Voucher,
    UserQRAuth,
    PushSubscription,
    OrderStatus
)
from .utils import build_qr_response
from .utils import send_push_to_user 
import logging
from shop.tasks import send_bulk_push_notification

# Import your push utility

logger = logging.getLogger(__name__)

# Register your models here.
@admin.action(description="📣 Send Marketing Push Notification")
def send_marketing_push(modeladmin, request, queryset):
    """
    Production-ready bulk push using Celery background tasks.
    """
    if 'apply' in request.POST:
        title = request.POST.get('push_title', '').strip()
        body = request.POST.get('push_body', '').strip()
        url = request.POST.get('push_url', '/').strip()
        marketing_only = request.POST.get('marketing_only') == 'on'

        if not title or not body:
            messages.error(request, "Title and body are required.")
            return HttpResponseRedirect(request.get_full_path())

        # Get user IDs from selected profiles
        if marketing_only:
            user_ids = list(
                queryset.filter(
                    marketing_preference=True
                ).values_list('user__id', flat=True)
            )
        else:
            user_ids = list(
                queryset.values_list('user__id', flat=True)
            )

        # Filter only users who have push subscriptions
        subscribed_user_ids = list(
            PushSubscription.objects.filter(
                user__id__in=user_ids
            ).values_list('user__id', flat=True).distinct()
        )

        if not subscribed_user_ids:
            messages.warning(
                request,
                "None of the selected users have push notifications enabled."
            )
            return HttpResponseRedirect(request.get_full_path())

        # Fire Celery background task
        task = send_bulk_push_notification.apply_async(
            args=[subscribed_user_ids, title, body, url],
        )

        messages.success(
            request,
            f"✅ Push notification queued for {len(subscribed_user_ids)} users. "
            f"Task ID: {task.id}. "
            f"Check task progress in Celery results."
        )
        return HttpResponseRedirect(request.get_full_path())

    # Show the form
    subscribed_count = PushSubscription.objects.filter(
        user__in=queryset.values_list('user', flat=True)
    ).values('user').distinct().count()

    return render(request, 'admin/send_push_form.html', {
        'items': queryset,
        'action': 'send_marketing_push',
        'subscribed_count': subscribed_count,
        'total_count': queryset.count(),
    })

@admin.action(description="Complete selected orders and send PWA notification")
def complete_and_notify_users(modeladmin, request, queryset):
    from shop.tasks import complete_orders_and_notify

    # Get order IDs as strings (UUID safe)
    order_ids = [str(order.order_id) for order in queryset]

    if not order_ids:
        messages.warning(request, "No orders selected.")
        return

    # Fire Celery task — returns instantly ✅
    task = complete_orders_and_notify.apply_async(
        args=[order_ids],
        countdown=0,
    )

    messages.success(
        request,
        f"✅ Processing {len(order_ids)} orders in background. "
        f"Task ID: {task.id}. "
        f"Check Flower dashboard for progress."
    )
        
@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "subscription_json","created_at")
    readonly_fields = ("created_at",)

class UserQRAuthAdmin(admin.ModelAdmin):
    list_display = ("user", "is_active")
    list_filter = ("is_active",)
    readonly_fields = ("created_at",)
    actions = ["download_qr"]
    
    @admin.action(description="Generate & Download QR")
    def download_qr(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request, "Please select exactly one user.", level=messages.ERROR
            )
            return
        
        # FIX 2: Get the UserQRAuth instance first, then extract the User
        qr_auth_instance = queryset.first() 
        user = qr_auth_instance.user 

        if not user.is_staff:
            self.message_user(
                request, "QR login only allowed for staff.", level=messages.ERROR
            )
            return
            
        return build_qr_response(user)
    
class ProductInline(admin.TabularInline):
    model = Product
    extra = 0  # Set to 0 to prevent the display of extra empty forms
    max_num = 0  # Set max_num to 0 to hide the "Add Another" button
    can_delete = False

    # all fields except for those linked via relation
    readonly_fields = [
        field.name for field in Product._meta.get_fields() if not (field.is_relation)
    ]


class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "slug", "created_at", "updated_at")


class SubCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "description",
        "associated_category",
        "created_at",
        "updated_at",
    )


class ProductDepartmentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "description", "image_url" ,"created_at", "updated_at")


class SupplierAdmin(admin.ModelAdmin):
    inlines = [ProductInline]
    list_display = (
        "name",
        "contact_person",
        "contact_email",
        "contact_mobile_number",
        "created_at",
        "updated_at",
    )


class ReviewInline(admin.TabularInline):
    model = Review
    extra = 0
    max_num = 0  # Set max_num to 0 to hide the "Add Another" button
    readonly_fields = ["user", "product", "text"]
    can_delete = False


class LikeInline(admin.TabularInline):
    model = Like
    extra = 0
    max_num = 0  # Set max_num to 0 to hide the "Add Another" button
    readonly_fields = ["user", "product"]
    can_delete = False
    
class ProductActionForm(ActionForm):
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        required=False,
        label=_("New Category")
    )


    
class ProductAdmin(admin.ModelAdmin):
    inlines = [ReviewInline, LikeInline]
    list_display = (
        "product_id", "name", "barcode", "cost_price", "price", "is_active", "stock_quantity", "tax_category", "category",
        "sub_category", "product_department", "supplier",
        "is_available_for_catering", "is_trending", "is_chilled", "is_frozen",
        "product_like_count", "product_sale_count", "active_promotions", "discounted_price",
    )
    list_filter = (
        "location_in_store", "category", "sub_category", "product_department",
        "supplier", "is_available_for_catering", "is_trending"
    )
    search_fields = ("name",)

    # Show all products including soft-deleted
    def get_queryset(self, request):
        return self.model.all_objects.get_queryset()

    def product_like_count(self, obj):
        return obj.likes.count()
    product_like_count.short_description = "User Like Count"

    def product_sale_count(self, obj):
        return sum(item.quantity for item in obj.order_items_from_product.all())
    product_sale_count.short_description = "Product Sale Count"

    def active_promotions(self, obj):
        return ", ".join(p.name for p in obj.active_promotions)
    active_promotions.short_description = "Active Promotions"
    
    # ✅ add the action form so you get dropdowns above the list
    action_form = ProductActionForm

    actions = ["mark_active", "mark_inactive", "bulk_update_category"]

    @admin.action(description="Mark selected products as Active")
    def mark_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} product(s) marked as active.")

    @admin.action(description="Mark selected products as Inactive")
    def mark_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} product(s) marked as inactive.")

    @admin.action(description="Bulk update: set Category")
    def bulk_update_category(self, request, queryset):
        """
        Uses the extra fields from action_form (category).
        Only updates fields the admin selected (non-empty).
        """
        # The action form data is in request.POST when the action is submitted
        category_id = request.POST.get('category') or None

        # If nothing was selected, inform the user
        if not any([category_id]):
            self.message_user(
                request,
                "No changes applied. Please choose at least one field (Category/Sub-category/Department).",
                level="warning",
            )
            return

        # Prepare a dict of updates
        updates = {}
        if category_id:
            updates['category_id'] = category_id

        # Apply updates efficiently
        updated_count = queryset.update(**updates)


        self.message_user(
            request,
            f"{updated_count} product(s) updated.",
        )
        
class OrderInline(admin.TabularInline):
    model = Order
    readonly_fields = ["status", "created_at", "updated_at"]
    can_delete = False
    extra = 0  # Set to 0 to prevent the display of extra empty forms
    max_num = 0  # Set max_num to 0 to hide the "Add Another" button


class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user_profile_id",
        "user",
        "street_address",
        "mobile_number",
        "push_subscribed",
        "created_at",
        "updated_at",
    )
    actions = [send_marketing_push]
    
    def push_subscribed(self, obj):
        """Show if user has push notifications enabled"""
        has_sub = PushSubscription.objects.filter(user=obj.user).exists()
        return "🔔 Yes" if has_sub else "❌ No"
    push_subscribed.short_description = "Push Enabled"


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False  # Don't allow deletion from the user page
    verbose_name_plural = "User Profiles"


class CartInline(admin.TabularInline):
    model = Cart
    can_delete = False
    verbose_name_plural = "Carts"
    readonly_fields = ["user", "created_at", "updated_at"]


class CustomUserAdmin(UserAdmin):
    list_display = ("email", "first_name", "last_name", "is_active", "last_login")
    inlines = [UserProfileInline, ReviewInline, LikeInline, OrderInline, CartInline]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0  # Set to 0 to prevent the display of extra empty forms
    max_num = 0  # Set max_num to 0 to hide the "Add Another" button
    can_delete = False
    readonly_fields = ["product", "base_total", "quantity"]


class OrderAdmin(admin.ModelAdmin):
    inlines = [OrderItemInline]
    list_display = (
        "order_id",
        "user",
        "status",
        "dispatch_method",
        "delivery_type",
        "total_amount",
        "delivery_address",
        "created_at",
        "updated_at",
    )
    search_fields = ("order_id",)
    
    list_filter = (
            "status",
            "dispatch_method",
            "delivery_type",
            ("created_at", admin.DateFieldListFilter),  # built-in “by day/month/year” sidebar filter
        )
    date_hierarchy = "created_at"  # adds a navigation bar across years/months/days at top

    actions = ["export_orders_csv", complete_and_notify_users]

    @admin.action(description="Export selected orders as CSV")
    def export_orders_csv(self, request, queryset):
        """
        Exports only the selected/filtered queryset to CSV.
        """
        # Optional: restrict huge exports if you want
        # if queryset.count() > 100000:
        #     self.message_user(request, "Too many rows to export at once.", level=messages.ERROR)
        #     return

        now_str = timezone.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"orders_{now_str}.csv"

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        # Header row (adjust as needed)
        writer.writerow([
            "order_id",
            "user_id",
            "user_email",
            "status",
            "dispatch_method",
            "delivery_type",
            "total_amount",
            "delivery_address",
            "created_at",
            "updated_at",
        ])

        # Write data rows
        # Use .select_related for efficiency with FK fields like user, if available.
        qs = queryset.select_related("user")
        for obj in qs.iterator():
            writer.writerow([
                obj.order_id,
                getattr(obj.user, "id", ""),
                getattr(obj.user, "email", ""),
                obj.status,
                obj.dispatch_method,
                obj.delivery_type,
                obj.total_amount,  # if Decimal, csv writer will cast to str
                obj.delivery_address,
                obj.created_at.isoformat(),
                obj.updated_at.isoformat(),
            ])

        return response



class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "product", "quantity", "base_total")


# You can use admin.StackedInline for a different layout
class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0  # Set to 0 to prevent the display of extra empty forms
    max_num = 0  # Set max_num to 0 to hide the "Add Another" button
    can_delete = False
    readonly_fields = ["product", "quantity"]


class CartAdmin(admin.ModelAdmin):
    inlines = [CartItemInline]
    list_display = (
        "cart_id",
        "user",
        "created_at",
        "updated_at",
        "unique_item_count",
        "total_item_count",
        "delivery_type",
        "delivery_fee",
        "total_amount",
        "total_weight",
    )

    def unique_item_count(self, obj):
        return obj.unique_item_count()

    unique_item_count.short_description = "Cart Unique Item Count"

    def total_item_count(self, obj):
        return obj.total_item_count()

    total_item_count.short_description = "Cart Total Item Count"

    def total_amount(self, obj):
        return obj.total_amount

    total_amount.short_description = "Cart Total Amount"


class CartItemAdmin(admin.ModelAdmin):
    list_display = ("cart", "product", "quantity")
    
    action_form = CartItemExportActionForm
    actions = ["export_cartitems_csv"]

    @admin.action(description="Export selected to CSV (with optional date range)")
    def export_cartitems_csv(self, request, queryset):
            # Read form inputs
            start_date = request.POST.get("start_date") or None
            end_date = request.POST.get("end_date") or None
            include_headers = request.POST.get("include_headers") == "on"

            # Apply date range filter if provided.
            # If you have Cart.created_at, use cart__created_at__date__range.
            # If you have CartItem.created_at, use created_at__date__range instead.
            if start_date and end_date:
                queryset = queryset.filter(cart__created_at__date__range=[start_date, end_date])
            elif start_date:
                queryset = queryset.filter(cart__created_at__date__gte=start_date)
            elif end_date:
                queryset = queryset.filter(cart__created_at__date__lte=end_date)

            # Prepare CSV response
            today = timezone.now().strftime("%Y-%m-%d")
            filename = f"cartitems_export_{today}.csv"
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            # Add BOM so Excel opens UTF-8 correctly
            response.write('\ufeff')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'

            writer = csv.writer(response)

            # Define columns (you can change order/fields)
            columns = [
                "CartItem ID",
                "Cart ID",
                "Product ID",
                "Product Name",
                "Quantity",
                "Unit Price",
                "Base Total",
                "Discount Total",
                "Total After Discount",
                "Total Excl. Tax",
                "Tax Amount",
                "Cart Created At",
            ]

            if include_headers:
                writer.writerow(columns)

            # To avoid N+1 queries
            qs = queryset.select_related("cart", "product")

            for item in qs:
                # Safely get values (your model already exposes properties we can call)
                product = item.product
                unit_price = getattr(product, "price", Decimal("0.00")) or Decimal("0.00")
                product_name = getattr(product, "name", "")
                product_id = getattr(product, "id", None)
                base_total = item.base_total
                discount = item.total_discount_amount
                total_after_discount = item.total_after_discount
                total_excl_tax = item.total_excluding_tax
                tax_amt = item.total_tax_amount

                cart_created_at = getattr(item.cart, "created_at", None)

                row = [
                    item.id,
                    item.cart_id,
                    product_id,
                    product_name,
                    item.quantity,
                    f"{unit_price:.2f}",
                    f"{base_total:.2f}",
                    f"{discount:.2f}",
                    f"{total_after_discount:.2f}",
                    f"{total_excl_tax:.2f}",
                    f"{tax_amt:.2f}",
                    cart_created_at.isoformat() if cart_created_at else "",
                ]
                writer.writerow(row)

            return response



class LikeAdmin(admin.ModelAdmin):
    list_display = ["user", "product", "created_at"]


class ReviewAdmin(admin.ModelAdmin):
    list_display = ["review_id", "user", "product", "text", "created_at", "updated_at"]


class NotificationAdmin(admin.ModelAdmin):
    list_display = ["order", "message", "created_at", "updated_at", "is_read"]


class PromotionAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "start_date",
        "end_date",
        "promotion_type",
        "discount_percentage",
        "active",
    ]

    filter_horizontal = (
        "products",
        "categories",
        "subcategories",
    )  # Allows selecting products in a horizontal filter
    
    actions = ["mark_active", "mark_inactive"]
    
    @admin.action(description="Mark selected products as Active")
    def mark_active(self, request, queryset):
        updated = queryset.update(active=True)
        self.message_user(request, f"{updated} product(s) marked as active.")

    @admin.action(description="Mark selected products as Inactive")
    def mark_inactive(self, request, queryset):
        updated = queryset.update(active=False)
        self.message_user(request, f"{updated} product(s) marked as inactive.")


class VoucherAdmin(admin.ModelAdmin):
    list_display = [
        "unique_id",
        "code",
        "discount_type",
        "discount_value",
        "max_discount_value",
        "min_spend",
        "start_date",
        "end_date",
        "usage_limit",
        "times_used",
        "is_active",
        "condition_type"
    ]


class BannerAdmin(admin.ModelAdmin):
    list_display = [
        "banner_image_url_425",
        "banner_image_url_768",
        "banner_image_url_1024",
        "banner_image_url_1440",
        "banner_location",
    ]
    fields = [
        "banner_image_425",
        "banner_image_768",
        "banner_image_1024",
        "banner_image_1440",
        "banner_location",
    ]


class MiniAdAdmin(admin.ModelAdmin):
    list_display = ["ad_text", "ad_location"]


class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ["name", "enabled"]


class DeliveryOptionAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "description",
        "delivery_fee",
        "max_weight_allowed_in_kg",
        "max_distance_covered_in_miles",
        "minimum_purchase_required"
    ]


class TaxCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "description", "tax_rate"]


class LocationInStoreAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]

    verbose_name_plural = "Locations in Store"


admin.site.register(UserQRAuth, UserQRAuthAdmin)
admin.site.register(Product, ProductAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(SubCategory, SubCategoryAdmin)
admin.site.register(ProductDepartment, ProductDepartmentAdmin)
admin.site.register(Supplier, SupplierAdmin)
admin.site.register(UserProfile, UserProfileAdmin)
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
admin.site.register(Order, OrderAdmin)
admin.site.register(OrderItem, OrderItemAdmin)
admin.site.register(Cart, CartAdmin)
admin.site.register(CartItem, CartItemAdmin)
admin.site.register(Like, LikeAdmin)
admin.site.register(Review, ReviewAdmin)
admin.site.register(Notification, NotificationAdmin)
admin.site.register(Promotion, PromotionAdmin)
admin.site.register(Banner, BannerAdmin)
admin.site.register(MiniAd, MiniAdAdmin)
admin.site.register(FeatureFlag, FeatureFlagAdmin)
admin.site.register(DeliveryOption, DeliveryOptionAdmin)
admin.site.register(TaxCategory, TaxCategoryAdmin)
admin.site.register(LocationInStore, LocationInStoreAdmin)
admin.site.register(Voucher, VoucherAdmin)


@admin.register(IntegrationEvent)
class IntegrationEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "direction", "status", "attempts", "created_at")
    list_filter = ("direction", "status", "event_type")
    readonly_fields = [f.name for f in IntegrationEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
