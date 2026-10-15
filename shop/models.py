import uuid
from django.contrib.auth.models import User
from enum import Enum
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver
from decimal import Decimal, ROUND_HALF_UP
import re
import stripe
from django.conf import settings
from django.db.models.signals import m2m_changed
from django.utils import timezone
from django.utils.text import slugify
from django.contrib.auth.hashers import make_password, check_password

stripe.api_key = settings.STRIPE_API_KEY


def round_off_decimal(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class UserQRAuth(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="qr_auth")
    secret_hash = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_secret(self, raw_secret):
        self.secret_hash = make_password(raw_secret)

    def check_secret(self, raw_secret):
        return check_password(raw_secret, self.secret_hash)


# For models Cart, CartItem, Order, OrderItem, the sub total refers to the prices without applying the discount, whereas the total refers to the prices after applying discounts and delivery fee.
# The sub_total_excluding_tax refers to the amount after deducting tax from the sub total amount


# Create your models here.
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Automatically generate a slug if not already set
        if not self.slug:
            self.slug = slugify(self.name)
        super(Category, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural = "Categories"


class ProductDepartment(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(
        upload_to="product_department_images/", blank=True, null=True
    )
    image_url = models.URLField(blank=True, null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)  # Save first to ensure image has a URL

        # Update image_url only if needed
        if self.image and self.image.url != self.image_url:
            self.image_url = self.image.url
            # Save again only if image_url needs updating
            super().save(update_fields=["image_url"])

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Product Departments"


class Supplier(models.Model):
    name = models.CharField(max_length=100)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    contact_mobile_number = models.CharField(max_length=15, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class SubCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    associated_category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, related_name="subcategories"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Sub Categories"


class TaxCategory(models.Model):
    name = models.CharField(max_length=25, unique=True)
    description = models.TextField(blank=True, null=True)
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )  # value between 0.00 and 100.00
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Tax Categories"

    def __str__(self):
        return f"{self.name}"


class LocationInStore(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Locations in Store"

    def __str__(self):
        return f"{self.name}"


class ActiveProductManager(models.Manager):
    def get_queryset(self):
        # Only return active products by default
        return super().get_queryset().filter(is_active=True)


class Product(models.Model):
    product_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    barcode = models.CharField(max_length=20, unique=True, null=True, blank=True)
    alternate_barcodes = models.JSONField(
        default=list,
        blank=True,
        help_text="List of alternative barcodes for this product",
    )
    name = models.CharField(max_length=100)
    brand = models.CharField(max_length=100, null=True, blank=True)
    cost_price = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0.00,
    )
    profit_margin = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0.00,
    )
    price = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(0)]
    )
    tax_category = models.ForeignKey(TaxCategory, on_delete=models.SET_NULL, null=True)

    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True
    )  # Asian, Oriental
    sub_category = models.ForeignKey(
        SubCategory, on_delete=models.SET_NULL, blank=True, null=True
    )  # Nepalese, Chinese
    product_department = models.ForeignKey(
        ProductDepartment, on_delete=models.SET_NULL, null=True, blank=True
    )  # Oil, Spices, Household
    is_frozen = models.BooleanField(default=False)
    is_chilled = models.BooleanField(default=False)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True)
    stock_quantity = models.PositiveIntegerField(
        default=0, validators=[MinValueValidator(0)]
    )
    ingredients = models.TextField(blank=True, null=True)
    allergens = models.TextField(blank=True, null=True)
    net_contents = models.CharField(max_length=20, null=True, blank=True)
    preparation_and_usage = models.TextField(blank=True, null=True)

    # Define a foreign key field to reference the box (wholesale) product
    # This field will be nullable since not all products may have a wholesale counterpart
    box_product = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="unit_products",
    )
    location_in_store = models.ForeignKey(
        LocationInStore, on_delete=models.SET_NULL, null=True, blank=True, default=None
    )
    is_available_for_catering = models.BooleanField(default=False)
    product_image_url = models.URLField(blank=True, null=True)
    extra_info = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_trending = models.BooleanField(default=False)
    is_admin_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Assign the custom manager to `objects`
    objects = ActiveProductManager()  # This will filter out inactive products
    all_objects = models.Manager()  # Default manager to be used for Admin interface

    def save(self, *args, **kwargs):
        # Set is_active to True only when the product is first created
        if not self.pk:  # Only set on product creation (not on updates)
            self.is_active = True
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.barcode}_[{self.name}]"

    @property
    def product_like_count(self):
        """Get the number of user likes on a product"""
        return self.likes.count()

    @property
    def product_sale_count(self):
        """Get the number of this product sold"""
        return self.order_items_from_product.count()

    @property
    def linked_promotion(self):
        """Retrieve the promotion in precedence for the product"""
        active_category_promotion = None
        active_subcategory_promotion = None
        now = timezone.now()

        # category promotion >> subcategory promotion >> product promotion
        active_product_promotion = self.product_promotion.filter(
            active=True, start_date__lte=now, end_date__gte=now
        )
        if self.category:
            active_category_promotion = self.category.category_promotion.filter(
                active=True, start_date__lte=now, end_date__gte=now
            )
        if self.sub_category:
            active_subcategory_promotion = (
                self.sub_category.subcategory_promotion.filter(
                    start_date__lte=now, end_date__gte=now
                )
            )

        # Apply the highest priority promotion
        if active_category_promotion:
            promotion = active_category_promotion
        elif active_subcategory_promotion:
            promotion = active_subcategory_promotion
        elif active_product_promotion:
            promotion = active_product_promotion
        else:
            promotion = None

        if promotion:
            assert len(promotion) == 1
            return promotion.first()
        else:
            return None

    @property
    def discounted_price(self, quantity=1, cart=None):
        """
        Apply promotions to calculate the discounted price based on cart quantity.
        If a Buy X Get Y% Discount promotion applies, ensure minimum quantity condition is met.
        """
        promotion = self.linked_promotion
        final_price = round_off_decimal(self.price * quantity)

        if promotion:
            if promotion.promotion_type == PromotionType.PERCENTAGE_DISCOUNT.value:
                discount = (promotion.discount_percentage / Decimal(100)) * final_price
                final_price -= round_off_decimal(discount)

            elif promotion.promotion_type == PromotionType.FIXED_AMOUNT_DISCOUNT.value:
                final_price -= round_off_decimal(
                    promotion.fixed_amount_discount * quantity
                )

            elif (
                promotion.promotion_type
                == PromotionType.BUY_X_GET_Y_PERCENT_DISCOUNT.value
                and cart
            ):
                # Ensure the cart meets the minimum quantity requirement
                cart_item = cart.cart_items.filter(product=self).first()
                if cart_item and cart_item.quantity >= promotion.minimum_quantity:
                    discount = (
                        promotion.discount_percentage / Decimal(100)
                    ) * final_price
                    final_price -= round_off_decimal(discount)
            elif (
                promotion.promotion_type
                == PromotionType.BUY_X_GET_Z_AMOUNT_DISCOUNT.value
                and cart
            ):
                # Ensure the cart meets the minimum quantity requirement
                cart_item = cart.cart_items.filter(product=self).first()
                if cart_item and cart_item.quantity >= promotion.minimum_quantity:
                    # Need to find how many multiples of minimum quanity in the actual quantity value
                    multiples = quantity // promotion.minimum_quantity
                    discount = promotion.fixed_amount_discount * multiples
                    final_price -= round_off_decimal(discount)

        return max(final_price, Decimal("0.00"))

    @property
    def active_promotions(self):
        now = timezone.now()
        return self.product_promotion.filter(
            active=True, start_date__lte=now, end_date__gte=now
        )

    @property
    def tax_rate(self):
        if self.tax_category:
            return round_off_decimal(self.tax_category.tax_rate)
        else:
            return round_off_decimal(0.00)

    @property
    def net_contents_in_kg(self):
        """
        Converts the net contents into kilograms.
        - Treats 'g' and 'ml' as grams and converts them to kg.
        - Treats 'l' as kilograms.
        """
        if not self.net_contents:
            return None  # Return None if net_contents is not set

        # Use a regex to extract the numeric value and unit
        match = re.match(
            r"(\d+(?:\.\d+)?)(?:\s*)?(kg|g|mg||l|ml)", self.net_contents.lower()
        )
        if not match:
            return None  # Return None if the format is invalid

        value, unit = match.groups()
        value = Decimal(value)

        # Conversion logic
        if unit in ["mg"]:
            return value / Decimal(1000000)  # Convert mg to kilograms
        if unit in ["g", "ml"]:
            return value / Decimal(1000)  # Convert grams/ml to kilograms
        elif unit in ["kg", "l"]:
            return value  # Kilograms/liters are already in kg equivalent
        else:
            return None  # Unexpected unit


class UserType(Enum):
    GENERAL = "general customer"
    WHOLESALER = "wholesaler"
    DRIVER = "driver"
    STAFF = "staff"


class Like(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_likes")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Ensures a user can like a product only once
        unique_together = ("user", "product")


class Review(models.Model):
    review_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="user_reviews"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="reviews"
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class UserProfile(models.Model):
    user_profile_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="userprofile"
    )
    fullname = models.CharField(max_length=100, default="Test user")
    street_address = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=50, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    county = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=50, blank=True, null=True)
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    nationality = models.CharField(max_length=50, blank=True, null=True)
    right_to_work = models.BooleanField(default=False, blank=True, null=True)
    user_type = models.CharField(
        max_length=25, choices=[(_type.value, _type.name) for _type in UserType]
    )
    is_account_activated = models.BooleanField(default=False, blank=True)
    marketing_preference = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def full_address(self):
        return ", ".join(
            [
                self.street_address,
                self.city,
                self.postal_code,
                self.county,
                self.country,
            ]
        )


class OrderStatus(Enum):
    CANCELED = "Canceled"
    PENDING = "Pending"
    DISPATCHED = "Dispatched"
    DELIVERED = "Delivered"
    READY_FOR_DISPATCH = "Ready for Dispatch"
    RETURNED = "Returned"


class OrderPaymentStatus(Enum):
    UNPAID = "Unpaid"
    PAID = "Paid"
    NO_PAYMENT_REQUIRED = "No Payment Required"
    REFUNDED = "Refunded"


class DispatchMethod(Enum):
    CLICK_N_COLLECT = "Click & Collect"
    HOME_DELIVERY = "Home Delivery"


class DeliveryType(Enum):
    LOCAL = "Local"
    NATIONAL = "National"
    INTERNATIONAL = "International"


class DeliveryOption(models.Model):
    name = models.CharField(max_length=50, unique=True)
    delivery_fee = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.00)],
    )
    description = models.CharField(max_length=100, null=True, blank=True)
    max_weight_allowed_in_kg = models.DecimalField(
        max_digits=5, decimal_places=2
    )  # in kg
    max_distance_covered_in_miles = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )  # in miles, if miles = None, it means there is no max limit on the distance covered
    minimum_purchase_required = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00
    )


class Order(models.Model):
    """For Order model, since it is created only once after the user completes the payment checkout,
    it makes sense to use model fields for total_amount"""

    order_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_orders")
    status = models.CharField(
        max_length=20,
        choices=[(status.value, status.name) for status in OrderStatus],
        default=OrderStatus.PENDING.value,
    )  # e.g., pending, shipped
    is_temporary = models.BooleanField(
        default=True
    )  # temporary orders are the ones created from the frontend when the user reaches the stripe payment checkout page
    stripe_payment_status = models.CharField(
        max_length=20,
        choices=[(status.value, status.name) for status in OrderPaymentStatus],
        default=OrderPaymentStatus.UNPAID.value,
    )
    stripe_payment_session_id = models.CharField(
        max_length=100, default="No payment session id available"
    )
    stock_reserved = models.BooleanField(
        default=False
    )  # True while this order's quantities are held (decremented) from Product stock
    dispatch_method = models.CharField(
        max_length=20,
        choices=[(method.value, method.name) for method in DispatchMethod],
        default=DispatchMethod.HOME_DELIVERY.value,
    )
    delivery_type = models.CharField(
        max_length=50
    )  # the type is set from the name of the DeliveryOption, even if the DeliveryOption is deleted, the name here will be intact
    delivery_fee = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.00)],
    )  # the fee is set from the name of the DeliveryOption, even if the DeliveryOption is deleted, the fee here will be intact
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    voucher_type = models.CharField(max_length=25, null=True, blank=True)
    voucher_code = models.CharField(
        max_length=10, blank=True, null=True
    )  # voucher code
    voucher_amount = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.00)],
    )  # if the discount in on the Order model, it refers to the vocher discount

    def __str__(self):
        return str(self.order_id)

    @property
    def delivery_address(self):
        street_address = self.user.userprofile.street_address
        city = self.user.userprofile.city
        postal_code = self.user.userprofile.postal_code
        country = self.user.userprofile.country
        full_address = ", ".join(
            [a for a in [street_address, city, postal_code, country] if a]
        )
        return full_address if full_address else "N/A"

    @property
    def total_discount(self):
        """Total discount for the entire order"""
        return round_off_decimal(
            max(
                sum(item.discount_amount for item in self.order_items_from_order.all()),
                0,
            )
        )

    @property
    def sub_total(self):
        """Subtotal of all order items before discounts and vouchers and delivery fees"""
        return round_off_decimal(
            max(
                sum(
                    item.order_item_subtotal
                    for item in self.order_items_from_order.all()
                ),
                0,
            )
        )

    @property
    def total_amount(self):
        """Final amount after applying discounts, voucher, and delivery fee"""
        return max(
            sum(
                [
                    Decimal(item.order_item_subtotal)
                    for item in self.order_items_from_order.all()
                ]
            )
            - Decimal(
                self.total_discount
            )  # Subtract total discount and voucher discount
            - Decimal(self.voucher_amount)
            + Decimal(self.delivery_fee),  # Add delivery fee
            0,
        )


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="order_items_from_order"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="order_items_from_product"
    )
    product_image_url = models.URLField(
        blank=True, null=True, default=None
    )  # Snapshot of product image at time of order
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    base_total = models.DecimalField(  # Equivalent to cart item base_total
        max_digits=10,  # Increased for large total values
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.00)],
    )  # Total price before discounts/taxes (unit price * quantity)
    discount_category = models.CharField(
        max_length=50, default=None, null=True, blank=True
    )
    discount_amount = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.00)],
    )  # Total discount applied to this item
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )  # Tax as percentage
    tax_category = models.CharField(max_length=25, null=True, blank=True, default=None)

    def __str__(self):
        return f"{self.quantity} x {self.product.name} in Order {self.order.id}"

    def save(self, *args, **kwargs):
        """Ensure calculated values are stored properly before saving."""
        super().save(*args, **kwargs)

    @property
    def order_item_total_after_discount(self):
        """Total after discount"""
        return round_off_decimal(self.base_total - Decimal(self.discount_amount))

    @property
    def tax_amount(self):
        """Total tax amount based on the total after discount"""
        return round_off_decimal(
            self.order_item_total_after_discount * self.tax_rate / 100
        )

    @property
    def base_total_excluding_tax(self):
        """Base total before tax application"""
        return round_off_decimal(max(0, self.base_total - self.tax_amount))

    @property
    def order_item_subtotal(self):
        """Subtotal before discount"""
        return round_off_decimal(self.base_total)

    @property
    def order_item_unit_price(self):
        """Unitprice calculated from base total"""
        return round_off_decimal(self.base_total / self.quantity)

    @property
    def order_item_total_amount(self):
        """Final amount after discount"""
        return round_off_decimal(self.order_item_total_after_discount)


class Voucher(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ("percentage", "Percentage"),
        ("fixed", "Fixed Amount"),
    ]

    CONDITION_TYPE_CHOICES = [
        ("none", "None"),
        ("first_order", "First Order"),
        ("min_spend", "Minimum Spend"),
    ]

    unique_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    code = models.CharField(max_length=20, unique=True, db_index=True)
    discount_type = models.CharField(
        max_length=10, choices=DISCOUNT_TYPE_CHOICES, default="percentage"
    )
    discount_value = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="For percentage, value should be between 0 and 100.",
    )
    max_discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        null=True,
        blank=True,
        help_text="Optional: Maximum discount amount for percentage-based vouchers.",
    )
    min_spend = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0,
        help_text="Minimum spend required to use this voucher.",
    )
    start_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum number of times this voucher can be used. Leave blank for unlimited.",
    )
    times_used = models.PositiveIntegerField(default=0, editable=False)
    is_active = models.BooleanField(default=True)

    # Tie voucher to a specific user or make it global if user is null
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="user_vouchers",
        help_text="Specify a user if this voucher is restricted to a particular user. Leave blank for global use.",
    )

    # Add conditions for specific voucher types
    condition_type = models.CharField(
        max_length=20,
        choices=CONDITION_TYPE_CHOICES,
        default="none",
        help_text="Condition for using this voucher (e.g., first order, minimum spend).",
    )

    def is_valid(self, user=None, cart_total=None):
        """Check if the voucher is valid for the given conditions."""

        # Check if the voucher is active
        if not self.is_active:
            return False

        # Check expiry date
        if self.end_date and timezone.now() > self.end_date:
            return False

        # Check usage limits
        if self.usage_limit and self.times_used >= self.usage_limit:
            return False

        # Check if voucher is tied to a specific user
        if self.user and self.user != user:
            return False

        # Handle condition: first order only
        if self.condition_type == "first_order" and user:
            user_orders = user.user_orders.all()

            # Allow only if the user has no valid completed orders
            if user_orders.count() > 1 or (
                user_orders.count() == 1 and not user_orders.first().is_temporary
            ):
                return False

            # Check if the temporary order is incomplete in Stripe, i.e. user didn't full go through the stripe checkout
            user_only_order = user_orders.first()
            if user_only_order:
                if not user_only_order.is_temporary:
                    return False

                try:
                    stripe_session = stripe.checkout.Session.retrieve(
                        user_only_order.stripe_payment_session_id
                    )
                    if stripe_session.get("status") == "complete":
                        return False
                except stripe.error.InvalidRequestError:
                    # Handle invalid session ID gracefully
                    return False

        # Check minimum spend condition
        if self.min_spend > 0 and (cart_total is None or cart_total < self.min_spend):
            return False

        return True

    def calculate_discount(self, total_amount, user=None):
        """
        Calculate the discount based on the voucher's rules and optionally check if it's valid for the given user.
        :param total_amount: Decimal - The total amount of the cart or order.
        :param user: User - The user trying to apply the voucher (optional).
        :return: Decimal - Discount amount or 0 if not applicable.
        """
        if not self.is_valid(user=user, cart_total=total_amount):
            return Decimal("0.00")

        if self.discount_type == "percentage":
            discount = (Decimal(self.discount_value) / 100) * total_amount
            if self.max_discount_value:
                discount = min(discount, self.max_discount_value)
        else:  # fixed amount
            discount = self.discount_value

        return round_off_decimal(min(discount, total_amount))

    def __str__(self):
        user_info = f" (User: {self.user.username})" if self.user else ""
        return f"{self.code}{user_info} ({'Active' if self.is_valid() else 'Inactive'})"


class Cart(models.Model):
    """The Cart model dynamically calculates totals based on CartItem values."""

    cart_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    voucher = models.ForeignKey(
        Voucher,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="voucher_applied_to_cart",
        help_text="Optional voucher applied to this cart.",
    )
    delivery_option = models.ForeignKey(
        DeliveryOption, on_delete=models.SET_NULL, null=True, default=None, blank=True
    )

    def __str__(self):
        return f"Cart for {self.user.username}"

    @property
    def delivery_type(self):
        return self.delivery_option.name if self.delivery_option else None

    @property
    def delivery_fee(self):
        return (
            self.delivery_option.delivery_fee
            if self.delivery_option
            else Decimal("0.00")
        )

    @property
    def total_tax(self):
        """Total VAT applied to all cart items, calculated on discounted prices."""
        return round_off_decimal(
            sum(item.total_tax_amount for item in self.cart_items.all()) or 0
        )

    @property
    def total_discount(self):
        """Total discount applied to all cart items."""
        return round_off_decimal(
            sum(item.total_discount_amount for item in self.cart_items.all()) or 0
        )

    @property
    def sub_total(self):
        """Subtotal before discounts, vouchers and delivery fee"""
        return round_off_decimal(
            sum(item.base_total for item in self.cart_items.all()) or 0
        )

    @property
    def sub_total_after_discount(self):
        """Subtotal after discounts"""
        return round_off_decimal(self.sub_total - self.total_discount or 0)

    @property
    def sub_total_excluding_tax(self):
        """Subtotal before VAT but after discount."""
        return round_off_decimal(
            sum(item.total_excluding_tax for item in self.cart_items.all()) or 0
        )

    @property
    def applied_voucher_discount_amount(self):
        """Discount amount from an applied voucher, if any."""
        return (
            self.voucher.calculate_discount(self.sub_total_after_discount, self.user)
            if self.voucher
            else Decimal("0.00")
        )

    @property
    def total_amount(self):
        """
        Total payable amount after applying:
        - Discounts
        - VAT
        - Delivery Fee
        - Voucher Discount (if any)
        """
        return round_off_decimal(
            max(
                self.sub_total
                - self.total_discount
                - self.applied_voucher_discount_amount
                + self.delivery_fee,
                0,
            )
        )

    @property
    def total_weight(self):
        """Total weight of all items in the cart (treating ml as grams)."""
        return round_off_decimal(
            sum(
                item.quantity * item.product.net_contents_in_kg
                for item in self.cart_items.all()
                if item.product.net_contents_in_kg
            )
            or 0
        )

    def unique_item_count(self):
        """Count unique product types in the cart."""
        return (
            self.cart_items.aggregate(unique_item_count=models.Count("product"))[
                "unique_item_count"
            ]
            or 0
        )

    def total_item_count(self):
        """Total quantity of items in the cart."""
        return (
            self.cart_items.aggregate(total_item_count=models.Sum("quantity"))[
                "total_item_count"
            ]
            or 0
        )


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="cart_items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    def __str__(self):
        return f"{self.quantity} x {self.product.name} in Cart {self.cart.id}"

    @property
    def tax_category(self):
        return self.product.tax_category

    @property
    def tax_rate(self):
        """Tax rate from the product"""
        return round_off_decimal(self.product.tax_rate)

    @property
    def base_total(self):
        """Total price before discounts

        Setting a unit price for a cart item can become tricky for products with buy x get y % offers. To fix this, we should do the calculations at
        the whole cart item level including number of items

        """
        return round_off_decimal(self.product.price * self.quantity)

    @property
    def total_discount_amount(self):
        """Total discount applied to this cart item"""
        total_discount = Decimal("0.00")
        promotion = self.product.linked_promotion

        if promotion:
            if promotion.promotion_type == PromotionType.PERCENTAGE_DISCOUNT.value:
                discount = (
                    promotion.discount_percentage / Decimal(100)
                ) * self.base_total
                total_discount = round_off_decimal(discount)

            elif promotion.promotion_type == PromotionType.FIXED_AMOUNT_DISCOUNT.value:
                total_discount = round_off_decimal(
                    promotion.discount_value * self.quantity
                )

            elif (
                promotion.promotion_type
                == PromotionType.BUY_X_GET_Y_PERCENT_DISCOUNT.value
            ):
                if self.quantity >= promotion.minimum_quantity:
                    # Apply discount only to eligible units
                    eligible_discount_units = (
                        self.quantity // promotion.minimum_quantity
                    ) * promotion.minimum_quantity
                    discount_per_unit = (
                        promotion.discount_percentage / Decimal(100)
                    ) * self.product.price
                    total_discount = round_off_decimal(
                        eligible_discount_units * discount_per_unit
                    )
            elif (
                promotion.promotion_type
                == PromotionType.BUY_X_GET_Z_AMOUNT_DISCOUNT.value
            ):
                if self.quantity >= promotion.minimum_quantity:
                    multiples = self.quantity // promotion.minimum_quantity
                    total_discount = round_off_decimal(
                        promotion.fixed_amount_discount * multiples
                    )

        return round_off_decimal(max(total_discount, 0))

    @property
    def total_after_discount(self):
        """Total amount after applying the discount"""
        return round_off_decimal(self.base_total - self.total_discount_amount)

    @property
    def total_excluding_tax(self):
        """Total price before tax, after applying discounts"""
        tax_rate = self.tax_rate / Decimal(100)
        return round_off_decimal(self.total_after_discount / (1 + tax_rate))

    @property
    def total_tax_amount(self):
        """Tax amount calculated on the discounted price"""
        return round_off_decimal(self.total_excluding_tax * (self.tax_rate / 100))

    @property
    def discount_category(self):  # type of promotion linked with the cart item product
        return self.product.linked_promotion.promotion_type


# Order notification
class Notification(models.Model):
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="order_notifications"
    )
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_read = models.BooleanField(default=False)


class PromotionType(models.TextChoices):
    PERCENTAGE_DISCOUNT = "percentage", "Percentage Discount"
    FIXED_AMOUNT_DISCOUNT = "fixed", "Fixed Amount Discount"
    BUY_X_GET_Y_PERCENT_DISCOUNT = (
        "buy_x_get_y_percent_discount",
        "Buy X Get Y Percent Discount",
    )
    BUY_X_GET_Z_AMOUNT_DISCOUNT = (
        "buy_x_get_z_amount_discount",
        "Buy X Get Z Amount Discount",
    )


class Promotion(models.Model):
    # promotional offers that is applied to the products/categories/subcategories
    name = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    active = models.BooleanField(default=True)
    discount_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, default=Decimal("0.00")
    )
    fixed_amount_discount = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"), blank=True
    )
    promotion_type = models.CharField(
        max_length=50,
        choices=PromotionType.choices,
        default=PromotionType.PERCENTAGE_DISCOUNT,
    )
    categories = models.ManyToManyField(
        "Category", blank=True, related_name="category_promotion"
    )
    subcategories = models.ManyToManyField(
        "SubCategory", blank=True, related_name="subcategory_promotion"
    )
    products = models.ManyToManyField(
        "Product", blank=True, related_name="product_promotion"
    )
    minimum_quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)]
    )  # For bulk purchase and Buy X to get discount
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Promotion: {self.start_date.strftime('%Y-%m-%d')} to {self.end_date.strftime('%Y-%m-%d')}"

    def clean(self):
        super().clean()
        if self.end_date < self.start_date:
            raise ValidationError("End date cannot be earlier than start date.")

    @property
    def is_active(self):
        now = timezone.now()
        return self.active and self.start_date <= now <= self.end_date
    
    @property
    def discount_value(self) -> Decimal:
        """
        Backward-compatible accessor used by CartItem calculations.
        For fixed amount promotions -> fixed_amount_discount
        For percentage promotions -> discount_percentage
        """
        if self.promotion_type == PromotionType.FIXED_AMOUNT_DISCOUNT:
            return self.fixed_amount_discount or Decimal("0.00")
        return self.discount_percentage or Decimal("0.00")



@receiver(m2m_changed, sender=Promotion.products.through)
@receiver(m2m_changed, sender=Promotion.categories.through)
@receiver(m2m_changed, sender=Promotion.subcategories.through)
def validate_promotion_m2m(sender, instance, action, **kwargs):
    if action in ["post_add", "post_remove", "post_clear"]:
        conflicting_products = (
            Promotion.objects.filter(
                active=True,
                end_date__gt=timezone.now(),
                products__in=instance.products.all(),
            )
            .exclude(pk=instance.pk)
            .distinct()
        )

        if conflicting_products.exists():
            raise ValidationError(
                "Some of your selected products for this promotion are already linked to another active promotion."
            )

        conflicting_categories = (
            Promotion.objects.filter(
                active=True,
                end_date__gt=timezone.now(),
                categories__in=instance.categories.all(),
            )
            .exclude(pk=instance.pk)
            .distinct()
        )

        if conflicting_categories.exists():
            raise ValidationError(
                "Some of your selected categories for this promotion are already linked to another active promotion."
            )

        conflicting_subcategories = (
            Promotion.objects.filter(
                active=True,
                end_date__gt=timezone.now(),
                subcategories__in=instance.subcategories.all(),
            )
            .exclude(pk=instance.pk)
            .distinct()
        )

        if conflicting_subcategories.exists():
            raise ValidationError(
                "Some of your selected subcategories for this promotion are already linked to another active promotion."
            )


class Banner(models.Model):
    banner_image_425 = models.ImageField(upload_to="banners/")
    banner_image_768 = models.ImageField(upload_to="banners/")
    banner_image_1024 = models.ImageField(upload_to="banners/")
    banner_image_1440 = models.ImageField(upload_to="banners/")

    banner_image_url_425 = models.URLField(blank=True, null=True, editable=False)
    banner_image_url_768 = models.URLField(blank=True, null=True, editable=False)
    banner_image_url_1024 = models.URLField(blank=True, null=True, editable=False)
    banner_image_url_1440 = models.URLField(blank=True, null=True, editable=False)

    banner_location = models.CharField(max_length=50)

    def clean(self):
        """Validate that all 4 images are provided."""
        missing = []
        if not self.banner_image_425:
            missing.append("banner_image_425")
        if not self.banner_image_768:
            missing.append("banner_image_768")
        if not self.banner_image_1024:
            missing.append("banner_image_1024")
        if not self.banner_image_1440:
            missing.append("banner_image_1440")

        if missing:
            raise ValidationError(
                f"Missing required image fields: {', '.join(missing)}"
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

        updated_fields = []

        if (
            self.banner_image_425
            and self.banner_image_url_425 != self.banner_image_425.url
        ):
            self.banner_image_url_425 = self.banner_image_425.url
            updated_fields.append("banner_image_url_425")

        if (
            self.banner_image_768
            and self.banner_image_url_768 != self.banner_image_768.url
        ):
            self.banner_image_url_768 = self.banner_image_768.url
            updated_fields.append("banner_image_url_768")

        if (
            self.banner_image_1024
            and self.banner_image_url_1024 != self.banner_image_1024.url
        ):
            self.banner_image_url_1024 = self.banner_image_1024.url
            updated_fields.append("banner_image_url_1024")

        if (
            self.banner_image_1440
            and self.banner_image_url_1440 != self.banner_image_1440.url
        ):
            self.banner_image_url_1440 = self.banner_image_1440.url
            updated_fields.append("banner_image_url_1440")

        # 4️⃣ Only save again if URLs updated
        if updated_fields:
            super().save(update_fields=updated_fields)

    def __str__(self):
        return f"Banner - {self.banner_location}"


class MiniAd(models.Model):
    ad_text = models.CharField(max_length=60)
    ad_description = models.CharField(max_length=300, null=True, blank=True, default="")
    ad_location = models.CharField(max_length=20)


class FeatureFlag(models.Model):
    name = models.CharField(max_length=100, unique=True)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class PushSubscription(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='push_subscriptions'
    )
    subscription_json = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'subscription_json']

    def __str__(self):
        return f"Push subscription for {self.user.email}"