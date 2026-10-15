"""rewards/admin.py"""
from __future__ import annotations

from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import LoyaltyAccount, LoyaltyConfig, LoyaltyTransaction
from .services import generate_barcode_svg, manual_adjustment


# ===========================================================================
# 1.  LoyaltyConfig  (singleton)
# ===========================================================================

@admin.register(LoyaltyConfig)
class LoyaltyConfigAdmin(admin.ModelAdmin):
    list_display = (
        "points_per_pound",
        "point_value_gbp",
        "min_points_to_redeem",
        "is_active",
        "updated_at",
        "earning_example",
        "redeeming_example",
    )
    fieldsets = (
        (
            "💰 Earning Rate",
            {
                "description": (
                    "How many points a customer earns per £1 they spend. "
                    "Example: 2.00 = 2 points per £1."
                ),
                "fields": ("points_per_pound",),
            },
        ),
        (
            "🎁 Redemption Rate",
            {
                "description": (
                    "How much each point is worth when a customer redeems. "
                    "Example: 0.0100 = 1p per point  →  100 pts = £1.00."
                ),
                "fields": ("point_value_gbp", "min_points_to_redeem"),
            },
        ),
        (
            "⚙️ Programme Status",
            {
                "description": "Disable to pause all points earning across the platform.",
                "fields": ("is_active",),
            },
        ),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not LoyaltyConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Earning example")
    def earning_example(self, obj: LoyaltyConfig) -> str:
        pts = int(Decimal("10.00") * obj.points_per_pound)
        return f"£10 spend → {pts} pts"

    @admin.display(description="Redemption example")
    def redeeming_example(self, obj: LoyaltyConfig) -> str:
        gbp = Decimal("100") * obj.point_value_gbp
        return f"100 pts → £{gbp:.2f}"


# ===========================================================================
# 2.  Transaction inline
# ===========================================================================

class LoyaltyTransactionInline(admin.TabularInline):
    model = LoyaltyTransaction
    extra = 0
    can_delete = False
    max_num = 0
    show_change_link = True
    fields = (
        "created_at",
        "transaction_type",
        "points",
        "order_amount_gbp",
        "order_reference",
        "description",
        "balance_after",
    )
    readonly_fields = fields
    ordering = ("-created_at",)


# ===========================================================================
# 3.  Manual adjustment form
# ===========================================================================

class ManualAdjustmentForm(forms.Form):
    points_delta = forms.IntegerField(
        label="Points delta (positive = add, negative = deduct)",
        help_text="E.g. 50 to add 50 pts, -50 to remove 50 pts.",
    )
    reason = forms.CharField(
        label="Reason",
        max_length=255,
        widget=forms.TextInput(attrs={"size": 60}),
        help_text="Visible in the customer's transaction history.",
    )


# ===========================================================================
# 4.  LoyaltyAccount
# ===========================================================================

@admin.register(LoyaltyAccount)
class LoyaltyAccountAdmin(admin.ModelAdmin):
    list_display = (
        "customer_name",
        "customer_email",
        "barcode_number",
        "points_balance",
        "points_gbp_value_display",
        "tier_badge",
        "total_points_earned",
        "total_points_redeemed",
        "is_active",
        "created_at",
        "barcode_preview",
    )
    list_filter = ("is_active", "created_at")
    search_fields = (
        "barcode_number",
        "user_profile__fullname",
        "user_profile__user__email",
    )
    ordering = ("-created_at",)
    readonly_fields = (
        "account_id",
        "barcode_number",
        "barcode_image",
        "points_balance",
        "total_points_earned",
        "total_points_redeemed",
        "points_gbp_value_display",
        "tier_badge",
        "created_at",
        "updated_at",
    )
    inlines = [LoyaltyTransactionInline]
    actions = ["apply_manual_adjustment", "deactivate_accounts", "reactivate_accounts"]

    fieldsets = (
        (
            "👤 Customer",
            {"fields": ("account_id", "user_profile", "is_active")},
        ),
        (
            "🏆 Points Summary",
            {
                "fields": (
                    "points_balance",
                    "points_gbp_value_display",
                    "tier_badge",
                    "total_points_earned",
                    "total_points_redeemed",
                ),
            },
        ),
        (
            "🔖 Loyalty Barcode",
            {
                "description": (
                    "Scanned at the till for in-store purchases."
                ),
                "fields": ("barcode_number", "barcode_image"),
            },
        ),
        (
            "📅 Timestamps",
            {
                "classes": ("collapse",),
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    @admin.display(description="Customer", ordering="user_profile__fullname")
    def customer_name(self, obj: LoyaltyAccount) -> str:
        try:
            url = reverse("admin:shop_userprofile_change", args=[obj.user_profile.pk])
            return format_html('<a href="{}">{}</a>', url, obj.user_profile.fullname)
        except Exception:
            return obj.user_profile.fullname

    @admin.display(description="Email")
    def customer_email(self, obj: LoyaltyAccount) -> str:
        return obj.user_profile.user.email

    @admin.display(description="£ Value")
    def points_gbp_value_display(self, obj: LoyaltyAccount) -> str:
        return f"£{obj.points_gbp_value:.2f}"

    @admin.display(description="Tier")
    def tier_badge(self, obj: LoyaltyAccount) -> str:
        colours = {"Gold": "#f59e0b", "Silver": "#94a3b8", "Bronze": "#b45309"}
        tier = obj.tier
        colour = colours.get(tier, "#6b7280")
        return format_html(
            '<span style="background:{c};color:#fff;padding:2px 10px;'
            'border-radius:99px;font-size:11px;font-weight:700;">{t}</span>',
            c=colour, t=tier,
        )

    @admin.display(description="Barcode preview")
    def barcode_preview(self, obj: LoyaltyAccount) -> str:
        try:
            svg = generate_barcode_svg(obj.barcode_number)
            encoded = svg.replace('"', "'")
            return format_html(
                '<img src="data:image/svg+xml;utf8,{}" height="30" '
                'style="display:block;" alt="barcode" />',
                mark_safe(encoded),
            )
        except Exception:
            return obj.barcode_number

    @admin.display(description="Barcode image")
    def barcode_image(self, obj: LoyaltyAccount) -> str:
        try:
            svg = generate_barcode_svg(obj.barcode_number)
            encoded = svg.replace('"', "'")
            return format_html(
                '<img src="data:image/svg+xml;utf8,{}" height="80" '
                'style="display:block;margin-top:6px;" alt="barcode" />',
                mark_safe(encoded),
            )
        except Exception:
            return f"(install python-barcode)  #{obj.barcode_number}"

    # ---- actions ----

    @admin.action(description="Apply manual points adjustment to selected accounts")
    def apply_manual_adjustment(
        self, request: HttpRequest, queryset: QuerySet[LoyaltyAccount]
    ):
        if "apply" in request.POST:
            form = ManualAdjustmentForm(request.POST)
            if form.is_valid():
                delta = form.cleaned_data["points_delta"]
                reason = form.cleaned_data["reason"]
                count = 0
                for account in queryset:
                    manual_adjustment(
                        user_profile=account.user_profile,
                        points_delta=delta,
                        reason=reason,
                    )
                    count += 1
                sign = "+" if delta >= 0 else ""
                self.message_user(
                    request,
                    f'Applied {sign}{delta} pts to {count} account(s). Reason: "{reason}"',
                    messages.SUCCESS,
                )
                return None

        form = ManualAdjustmentForm()
        selected_pks = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
        hidden_inputs = "".join(
            f'<input type="hidden" name="{admin.ACTION_CHECKBOX_NAME}" value="{pk}">'
            for pk in selected_pks
        )
        form_rows = "".join(
            f"<tr><th style='text-align:left;padding:6px 12px'>{f.label}</th>"
            f"<td style='padding:6px 12px'>{f}</td>"
            f"<td style='padding:6px 12px;color:#888'><small>{f.help_text}</small></td></tr>"
            for f in form
        )
        csrf = request.META.get("CSRF_COOKIE", "")
        names = ", ".join(a.user_profile.fullname for a in queryset)
        count = queryset.count()

        return HttpResponse(
            f"""<!DOCTYPE html><html><head><title>Manual Adjustment</title>
            <link rel="stylesheet" href="/static/admin/css/base.css">
            <style>body{{padding:20px}} h1{{margin-bottom:12px}}</style>
            </head><body id="django-admin">
            <div id="content" class="colM">
              <h1>Manual Points Adjustment</h1>
              <p>Applying to <strong>{count}</strong> account(s): <em>{names}</em></p>
              <form method="post">
                {hidden_inputs}
                <input type="hidden" name="action" value="apply_manual_adjustment">
                <input type="hidden" name="apply" value="1">
                <input type="hidden" name="csrfmiddlewaretoken" value="{csrf}">
                <table style="border-collapse:collapse">{form_rows}</table>
                <br>
                <input type="submit" value="Apply Adjustment" class="button default"
                       style="margin-right:8px">
                <a href=".." class="button cancel-link">Cancel</a>
              </form>
            </div></body></html>""",
            content_type="text/html",
        )

    @admin.action(description="Deactivate selected loyalty accounts")
    def deactivate_accounts(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} account(s) deactivated.", messages.WARNING)

    @admin.action(description="Reactivate selected loyalty accounts")
    def reactivate_accounts(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} account(s) reactivated.", messages.SUCCESS)


# ===========================================================================
# 5.  LoyaltyTransaction — full audit log
# ===========================================================================

@admin.register(LoyaltyTransaction)
class LoyaltyTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "customer_name",
        "transaction_type_badge",
        "points_display",
        "order_amount_gbp",
        "order_reference",
        "balance_after",
        "description",
    )
    list_filter = ("transaction_type", "created_at")
    search_fields = (
        "loyalty_account__user_profile__fullname",
        "loyalty_account__user_profile__user__email",
        "loyalty_account__barcode_number",
        "order_reference",
        "description",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "transaction_id",
        "loyalty_account",
        "transaction_type",
        "points",
        "order_amount_gbp",
        "order_reference",
        "description",
        "balance_after",
        "created_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return request.user.is_superuser

    @admin.display(description="Customer", ordering="loyalty_account__user_profile__fullname")
    def customer_name(self, obj: LoyaltyTransaction) -> str:
        url = reverse("admin:rewards_loyaltyaccount_change", args=[obj.loyalty_account.pk])
        return format_html(
            '<a href="{}">{}</a>', url, obj.loyalty_account.user_profile.fullname
        )

    @admin.display(description="Type")
    def transaction_type_badge(self, obj: LoyaltyTransaction) -> str:
        colours = {
            "EARN_ONLINE":  "#10b981",
            "EARN_INSTORE": "#3b82f6",
            "REDEEM":       "#f59e0b",
            "ADJUSTMENT":   "#8b5cf6",
            "EXPIRY":       "#ef4444",
        }
        colour = colours.get(obj.transaction_type, "#6b7280")
        return format_html(
            '<span style="background:{c};color:#fff;padding:2px 8px;'
            'border-radius:99px;font-size:11px;font-weight:700;">{l}</span>',
            c=colour, l=obj.get_transaction_type_display(),
        )

    @admin.display(description="Points")
    def points_display(self, obj: LoyaltyTransaction) -> str:
        colour = "#10b981" if obj.points >= 0 else "#ef4444"
        sign = "+" if obj.points >= 0 else ""
        return format_html(
            '<strong style="color:{c}">{s}{p}</strong>',
            c=colour, s=sign, p=obj.points,
        )