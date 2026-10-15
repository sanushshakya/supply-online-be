from django.contrib.auth.models import User
from rest_framework import serializers
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
    Promotion,
    SubCategory,
    Banner,
    MiniAd,
    ProductDepartment,
    DeliveryOption,
    LocationInStore,
)

# ModelSerializer automatically handles the model objects serialization for you
# PartialSerializer are supposed to be used for serializing the instances to be sent back in the response object, may be it should be called ResponeSerializer or RetrieveSerializer or something


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = "__all__"


class ProductDepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductDepartment
        fields = "__all__"


class SubCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubCategory
        fields = "__all__"


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = "__all__"


class LikeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Like
        fields = "__all__"


class CustomerFacingLikeSerializer(serializers.ModelSerializer):
    product_id = serializers.SerializerMethodField()
    user_profile_id = serializers.SerializerMethodField()

    class Meta:
        model = Like
        fields = ["created_at", "user_profile_id", "product_id"]

    def get_product_id(self, obj):
        return obj.product.product_id

    def get_user_profile_id(self, obj):
        return obj.user.userprofile.user_profile_id


class PartialUserSerializer(serializers.ModelSerializer):
    # Use to dump the user object for api response
    # we should not return the password in the api response

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name"]


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["review_id", "user", "product", "text", "updated_at"]


class PartialReviewSerializer(serializers.ModelSerializer):
    user = PartialUserSerializer(read_only=True)

    class Meta:
        model = Review
        fields = ["review_id", "user", "text", "updated_at"]


class ProductSerializer(serializers.ModelSerializer):
    
    product_department = serializers.CharField(
            source="product_department.name",
            read_only=True
        )


    reviews = PartialReviewSerializer(read_only=True, many=True)

    class Meta:
        model = Product
        fields = "__all__"


class PromotionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Promotion
        fields = "__all__"


class CustomerFacingProductSerializer(serializers.ModelSerializer):
    reviews = PartialReviewSerializer(read_only=True, many=True)
    likes = CustomerFacingLikeSerializer(read_only=True, many=True)
    discounted_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    linked_promotion = PromotionSerializer(read_only=True)

    class Meta:
        model = Product
        exclude = [
            "cost_price",
            "profit_margin",
            "id",
            "barcode",
            "is_admin_approved",
            "created_at",
            "updated_at",
            "supplier",
            "location_in_store",
        ]

    def get_discounted_price(self, obj):
        return obj.discounted_price

    def get_linked_promotion(self, obj):
        return obj.linked_promotion


class ProductSerializerForExport(serializers.ModelSerializer):
    category = serializers.CharField(source="category.name", read_only=True)
    sub_category = serializers.CharField(source="sub_category.name", read_only=True)
    product_department = serializers.CharField(
        source="product_department.name", read_only=True
    )
    supplier = serializers.CharField(source="supplier.name", read_only=True)
    alternate_barcodes = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "barcode",
            "alternate_barcodes",
            "name",
            "price",
            "stock_quantity",
            "category",
            "sub_category",
            "product_department",
            "supplier",
            "location_in_store",
        ]

    def get_alternate_barcodes(self, obj):
        # Join list into comma-separated string, or return empty string
        return ", ".join(obj.alternate_barcodes) if obj.alternate_barcodes else ""


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["username", "email", "password", "first_name", "last_name"]


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = [
            "fullname",
            "street_address",
            "city",
            "postal_code",
            "county",
            "country",
            "mobile_number",
            "user_type",
            "user",
            "marketing_preference",
            "nationality",  # for users registered as drivers
            "right_to_work",  # for users registered as drivers
        ]


class LikeSerializerForProfile(serializers.ModelSerializer):
    product = CustomerFacingProductSerializer(read_only=True)

    class Meta:
        model = Like
        fields = ["product"]


class ReviewSerializerForProfile(serializers.ModelSerializer):
    product = CustomerFacingProductSerializer(read_only=True)

    class Meta:
        model = Review
        fields = ["product", "review_id", "text", "created_at", "updated_at"]


class CustomerFacingUserProfileSerializer(serializers.ModelSerializer):
    # Use to dump the user profile object for api response
    # we should not return the django user id for security reasons
    email = serializers.SerializerMethodField()
    reviews = ReviewSerializerForProfile(
        many=True, read_only=True, source="user.user_reviews"
    )
    likes = LikeSerializerForProfile(
        many=True, read_only=True, source="user.user_likes"
    )

    def get_email(self, obj):
        return obj.user.email

    class Meta:
        model = UserProfile
        fields = [
            "fullname",
            "street_address",
            "city",
            "postal_code",
            "county",
            "country",
            "mobile_number",
            "user_type",
            "user_profile_id",
            "email",
            "reviews",
            "likes",
        ]


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    # only include the fields that the user should be allowed to update
    class Meta:
        model = UserProfile
        fields = [
            "fullname",
            "street_address",
            "city",
            "postal_code",
            "county",
            "country",
            "mobile_number",
            "user_type",
        ]


class LocationInStoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationInStore
        fields = "__all__"


class PartialProductSerializer(serializers.ModelSerializer):
    location_in_store = LocationInStoreSerializer(read_only=True)

    class Meta:
        model = Product
        fields = [
            "product_id",
            "barcode",
            "name",
            "price",
            "description",
            "stock_quantity",
            "location_in_store",
        ]


class OrderItemSerializer(serializers.ModelSerializer):
    product = PartialProductSerializer(read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            "product",
            "quantity",
            "discount_amount",
            "discount_category",
            "tax_amount",
            "tax_rate",
            "tax_category",
            "order_item_subtotal",
            "order_item_unit_price",
            "product_image_url",
        ]


class OrderSerializer(serializers.ModelSerializer):
    order_items_from_order = OrderItemSerializer(read_only=True, many=True)
    total_amount = serializers.DecimalField(
        max_digits=7, decimal_places=2, read_only=True
    )
    total_discount = serializers.DecimalField(
        max_digits=7, decimal_places=2, read_only=True
    )

    customer_email = serializers.SerializerMethodField()
    customer_mobile_number = serializers.SerializerMethodField()
    delivery_address = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = "__all__"

    def get_customer_email(self, obj):
        return obj.user.email if obj.user else None

    def get_customer_mobile_number(self, obj):
        return getattr(obj.user.userprofile, "mobile_number", None)

    def get_delivery_address(self, obj):
        return obj.delivery_address if obj.delivery_address else None


class CustomerFacingOrderSerializer(serializers.ModelSerializer):
    order_items_from_order = OrderItemSerializer(read_only=True, many=True)

    class Meta:
        model = Order
        fields = [
            "order_id",
            "status",
            "dispatch_method",
            "delivery_type",
            "delivery_fee",
            "created_at",
            "updated_at",
            "order_items_from_order",
            "total_amount",
            "total_discount",
            "voucher_amount",
            "sub_total",
            "stripe_payment_status",
        ]


class CartItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CartItem
        fields = "__all__"


class PartialCartItemSerializer(serializers.ModelSerializer):
    product = CustomerFacingProductSerializer(read_only=True)

    class Meta:
        model = CartItem
        fields = ["product", "quantity"]


class CartSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cart
        fields = "__all__"


class CustomerFacingCartSerializer(serializers.ModelSerializer):
    cart_items = PartialCartItemSerializer(read_only=True, many=True)
    # Directly include the properties/methods in the fields attribute
    sub_total = serializers.DecimalField(max_digits=7, decimal_places=2, read_only=True)
    sub_total_excluding_tax = serializers.DecimalField(
        max_digits=7, decimal_places=2, read_only=True
    )
    total_discount = serializers.DecimalField(
        max_digits=7, decimal_places=2, read_only=True
    )
    total_tax = serializers.DecimalField(max_digits=7, decimal_places=2, read_only=True)
    total_amount = serializers.DecimalField(
        max_digits=7, decimal_places=2, read_only=True
    )
    unique_item_count = serializers.IntegerField(read_only=True)
    total_item_count = serializers.IntegerField(read_only=True)
    total_weight = serializers.DecimalField(
        max_digits=7, decimal_places=2, read_only=True
    )
    applied_voucher_discount_amount = serializers.DecimalField(
        max_digits=7, decimal_places=2, read_only=True
    )

    class Meta:
        model = Cart
        fields = [
            "cart_id",
            "cart_items",
            "sub_total",
            "total_amount",
            "sub_total_excluding_tax",
            "total_discount",
            "total_tax",
            "unique_item_count",
            "total_item_count",
            "delivery_option",
            "total_weight",
            "applied_voucher_discount_amount",
        ]

    # Override the to_representation method if necessary
    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if not instance.cart_items.exists():
            representation["cart_items"] = []
        return representation


class CustomerFacingPromotionSerializer(serializers.ModelSerializer):
    categories = CategorySerializer(read_only=True, many=True)
    subcategories = SubCategorySerializer(read_only=True, many=True)
    products = CustomerFacingProductSerializer(read_only=True, many=True)

    class Meta:
        model = Promotion
        fields = "__all__"


class BannerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Banner
        fields = "__all__"


class MiniAdSerializer(serializers.ModelSerializer):
    class Meta:
        model = MiniAd
        fields = "__all__"


class DeliveryOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryOption
        fields = "__all__"

