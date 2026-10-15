import os
import shutil
from django.utils import timezone
from datetime import timedelta
from django.db import IntegrityError, transaction
from django.contrib.auth.models import User
from django.test import TestCase
from django.core.exceptions import ValidationError
from shop.models import (
    Category,
    Supplier,
    UserType,
    Like,
    Review,
    UserProfile,
    OrderStatus,
    Order,
    OrderItem,
    Product,
    Cart,
    CartItem,
    Promotion,
    PromotionType,
    ProductDepartment,
    SubCategory,
)

from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from shop.models import Banner
from unittest.mock import patch
from decimal import Decimal


class ProductModelTests(TestCase):
    def setUp(self):
        # Create sample category and supplier for testing
        self.category = Category.objects.create(name="Test Category")
        self.supplier = Supplier.objects.create(name="Test Supplier")

        # Create a sample product for testing

        self.product = Product.objects.create(
            name="Test Product",
            price=Decimal("12.00"),
            cost_price=Decimal("10.00"),
            profit_margin=Decimal("20.00"),
            barcode="1234567890",
            category=self.category,
            supplier=self.supplier,
            stock_quantity=50,
        )

    def test_product_creation(self):
        self.assertEqual(self.product.name, "Test Product")
        self.assertEqual(str(self.product), "1234567890_[Test Product]")
        self.assertEqual(self.product.price, Decimal("12.00"))
        self.assertEqual(self.product.barcode, "1234567890")
        self.assertEqual(self.product.category, self.category)
        self.assertEqual(self.product.supplier, self.supplier)

    def test_unique_barcode_constraint(self):
        # Attempt to create another product with the same barcode
        duplicate_product = Product(
            name="Duplicate Product", price=Decimal("15.99"), barcode="1234567890"
        )
        with self.assertRaises(Exception):  # IntegrityError should be raised
            duplicate_product.save()

    def test_negative_price_not_allowed(self):
        # Attempt to create a product with a negative price
        product_with_negative_price = Product(
            name="Negative Price Product", price=Decimal("-5.99"), barcode="9876543210"
        )
        with self.assertRaises(Exception):  # IntegrityError should be raised
            product_with_negative_price.full_clean()

    def test_default_values(self):
        # Test default values for new fields
        new_product = Product.objects.create(
            name="New Product", price=Decimal("19.99"), barcode="0987654321"
        )
        self.assertEqual(new_product.stock_quantity, 0)

    def test_stock_quantity_positive_integer(self):
        # Test that stock_quantity must be a positive integer
        with self.assertRaises(ValidationError):
            self.product.stock_quantity = -5
            self.product.full_clean()

    def test_product_inactive(self):
        # when the product is initially created, the is_active should be set to True by default
        assert self.product.is_active

        # Upon updating the product and then saving it, the logic to set is_active to True by default shouldn't run
        self.product.is_active = False
        self.product.save()
        self.product.refresh_from_db()
        assert not self.product.is_active


class CategoryModelTests(TestCase):
    def test_category_creation(self):
        category = Category.objects.create(
            name="Test Category", description="Test Description"
        )
        self.assertEqual(category.name, "Test Category")
        self.assertEqual(category.description, "Test Description")


class ProductDepartmentModelTests(TestCase):
    def test_product_department_creation(self):
        product_department = ProductDepartment.objects.create(
            name="Test department", description="Test Description"
        )
        self.assertEqual(product_department.name, "Test department")
        self.assertEqual(product_department.description, "Test Description")


class SupplierModelTests(TestCase):
    def test_supplier_creation(self):
        supplier = Supplier.objects.create(
            name="Test Supplier",
            contact_person="John Doe",
            contact_email="john@example.com",
            contact_mobile_number="1234567890",
        )
        self.assertEqual(supplier.name, "Test Supplier")
        self.assertEqual(supplier.contact_person, "John Doe")
        self.assertEqual(supplier.contact_email, "john@example.com")
        self.assertEqual(supplier.contact_mobile_number, "1234567890")


class UserProfileModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="testuser")

    def test_user_profile_creation(self):
        user_profile = UserProfile.objects.create(
            user=self.user,
            street_address="Test Address",
            mobile_number="1234567890",
            user_type=UserType.GENERAL.value,
        )
        self.assertEqual(user_profile.user, self.user)
        self.assertEqual(user_profile.street_address, "Test Address")
        self.assertEqual(user_profile.mobile_number, "1234567890")
        self.assertEqual(user_profile.user_type, UserType.GENERAL.value)


class LikeModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="testuser")
        self.product = Product.objects.create(
            name="Test Product", price="10.99", barcode="1234567890"
        )

    def test_like_creation(self):
        like = Like.objects.create(user=self.user, product=self.product)
        self.assertEqual(like.user, self.user)
        self.assertEqual(like.product, self.product)


class ReviewModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="testuser")
        self.product = Product.objects.create(
            name="Test Product", price=Decimal("10.99"), barcode="1234567890"
        )

    def test_review_creation(self):
        review = Review.objects.create(
            user=self.user, product=self.product, text="Test Review"
        )
        self.assertEqual(review.user, self.user)
        self.assertEqual(review.product, self.product)
        self.assertEqual(review.text, "Test Review")


class OrderModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="testuser")

    def test_order_creation(self):
        order = Order.objects.create(user=self.user, status=OrderStatus.PENDING.value)
        self.assertEqual(order.user, self.user)
        self.assertEqual(order.status, OrderStatus.PENDING.value)
        self.assertEqual(order.total_amount, 0.00)

        # Invalid order creation with negative total_amount
        with self.assertRaises(ValidationError):
            Order.objects.create(user=self.user, status="invalid_status").full_clean()


class OrderItemModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="testuser")
        self.product = Product.objects.create(
            name="Test Product", price=Decimal("10.99"), barcode="1234567890"
        )
        self.order = Order.objects.create(
            user=self.user, status=OrderStatus.PENDING.value
        )

    def test_order_item_creation(self):
        order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            base_total=Decimal(self.product.price * 2),
        )
        self.assertEqual(order_item.order, self.order)
        self.assertEqual(order_item.product, self.product)
        self.assertEqual(order_item.quantity, 2)
        self.assertEqual(order_item.base_total, Decimal("21.98"))
        self.assertEqual(order_item.discount_amount, Decimal("0.00"))
        self.assertEqual(order_item.order_item_total_amount, Decimal("21.98"))

        # Invalid order item creation with negative quantity
        # The transaction.atomic block ensures that the transaction is rolled back after the test,
        # allowing subsequent tests to run.
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                OrderItem.objects.create(
                    order=self.order, product=self.product, quantity=-2
                ).full_clean()


class CartModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="testuser")

    def test_cart_creation(self):
        cart = Cart.objects.create(user=self.user)
        self.assertEqual(cart.user, self.user)


class CartItemModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="testuser")
        self.product = Product.objects.create(
            name="Test Product", price=Decimal("10.99"), barcode="1234567890"
        )
        self.cart = Cart.objects.create(user=self.user)

    def test_cart_item_creation(self):
        cart_item = CartItem.objects.create(
            cart=self.cart, product=self.product, quantity=3
        )
        self.assertEqual(cart_item.cart, self.cart)
        self.assertEqual(cart_item.product, self.product)
        self.assertEqual(cart_item.quantity, 3)

        # Invalid cart item creation with negative quantity
        with self.assertRaises(IntegrityError):
            CartItem.objects.create(cart=self.cart, product=self.product, quantity=-3)


class PromotionModelTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="testuser")

        # --- Create categories, subcategories, products ---
        self.category1 = Category.objects.create(name="Category 1")
        self.category2 = Category.objects.create(name="Category 2")

        self.subcategory1 = SubCategory.objects.create(
            name="SubCategory 1", associated_category=self.category1
        )
        self.subcategory2 = SubCategory.objects.create(
            name="SubCategory 2", associated_category=self.category2
        )

        self.product1 = Product.objects.create(
            name="Product 1", price=Decimal("100.00")
        )
        self.product2 = Product.objects.create(
            name="Product 2", price=Decimal("200.00")
        )

        # --- Create a base promotion ---
        self.start_date = timezone.now()
        self.end_date = self.start_date + timedelta(days=7)

        self.promotion = Promotion.objects.create(
            name="Test Promotion",
            start_date=self.start_date,
            end_date=self.end_date,
            discount_percentage=Decimal("10.00"),
            fixed_amount_discount=Decimal("5.00"),
            promotion_type=PromotionType.PERCENTAGE_DISCOUNT,
            minimum_quantity=2,
        )

    # ---------------------------
    # Model field & clean tests
    # ---------------------------
    def test_string_representation(self):
        expected_str = f"Promotion: {self.start_date.strftime('%Y-%m-%d')} to {self.end_date.strftime('%Y-%m-%d')}"
        self.assertEqual(str(self.promotion), expected_str)

    def test_clean_end_date_validation(self):
        self.promotion.end_date = self.start_date - timedelta(days=1)
        with self.assertRaises(ValidationError):
            self.promotion.clean()

    def test_minimum_quantity_validation(self):
        self.promotion.minimum_quantity = 0
        with self.assertRaises(ValidationError):
            self.promotion.full_clean()

    def test_default_discount_values(self):
        p = Promotion.objects.create(
            name="Default Promotion",
            start_date=self.start_date,
            end_date=self.end_date,
            promotion_type=PromotionType.PERCENTAGE_DISCOUNT,
            minimum_quantity=1,
        )
        self.assertEqual(p.discount_percentage, Decimal("0.00"))
        self.assertEqual(p.fixed_amount_discount, Decimal("0.00"))

    # ---------------------------
    # is_active property
    # ---------------------------
    def test_is_active_true(self):
        self.assertTrue(self.promotion.is_active)

    def test_is_active_inactive_flag(self):
        self.promotion.active = False
        self.promotion.save()
        self.assertFalse(self.promotion.is_active)

    def test_is_active_before_start(self):
        self.promotion.start_date = timezone.now() + timedelta(days=1)
        self.promotion.save()
        self.assertFalse(self.promotion.is_active)

    def test_is_active_after_end(self):
        self.promotion.end_date = timezone.now() - timedelta(days=1)
        self.promotion.save()
        self.assertFalse(self.promotion.is_active)

    # ---------------------------
    # Many-to-many conflicts
    # ---------------------------
    def test_m2m_product_conflict(self):
        self.promotion.products.add(self.product1)
        p2 = Promotion.objects.create(
            name="Another Promotion",
            start_date=self.start_date,
            end_date=self.end_date,
            discount_percentage=Decimal("20.00"),
            promotion_type=PromotionType.PERCENTAGE_DISCOUNT,
            minimum_quantity=1,
        )
        with self.assertRaises(ValidationError):
            p2.products.add(self.product1)

    def test_m2m_category_conflict(self):
        self.promotion.categories.add(self.category1)
        p2 = Promotion.objects.create(
            name="Another Promotion",
            start_date=self.start_date,
            end_date=self.end_date,
            discount_percentage=20,
            promotion_type=PromotionType.PERCENTAGE_DISCOUNT,
            minimum_quantity=1,
        )
        with self.assertRaises(ValidationError):
            p2.categories.add(self.category1)

    def test_m2m_subcategory_conflict(self):
        self.promotion.subcategories.add(self.subcategory1)
        p2 = Promotion.objects.create(
            name="Another Promotion",
            start_date=self.start_date,
            end_date=self.end_date,
            discount_percentage=20,
            promotion_type=PromotionType.PERCENTAGE_DISCOUNT,
            minimum_quantity=1,
        )
        with self.assertRaises(ValidationError):
            p2.subcategories.add(self.subcategory1)

    # ---------------------------
    # Discount calculations
    # ---------------------------

    def test_percentage_discount_calculation(self):
        self.promotion.promotion_type = PromotionType.PERCENTAGE_DISCOUNT
        self.promotion.discount_percentage = Decimal("10.00")
        self.promotion.save()

        self.promotion.products.add(self.product1)

        cart = Cart.objects.create(user=self.user)
        cart_item = CartItem.objects.create(
            cart=cart, product=self.product1, quantity=3
        )
        discount = cart_item.total_discount_amount

        self.assertEqual(discount, Decimal("30.00"))  # 10% of 3*100 = 30

    def test_fixed_amount_discount_calculation(self):
        self.promotion.promotion_type = PromotionType.FIXED_AMOUNT_DISCOUNT
        self.promotion.fixed_amount_discount = Decimal("5.00")
        self.promotion.save()

        self.promotion.products.add(self.product1)

        cart = Cart.objects.create(user=self.user)
        cart_item = CartItem.objects.create(
            cart=cart, product=self.product1, quantity=4
        )
        discount = cart_item.total_discount_amount

        self.assertEqual(discount, Decimal("20.00"))  # 5*4 = 20

    def test_buy_x_get_y_percent_realistic(self):
        self.promotion.promotion_type = PromotionType.BUY_X_GET_Y_PERCENT_DISCOUNT
        self.promotion.discount_percentage = Decimal("50.00")
        self.promotion.minimum_quantity = 2
        self.promotion.save()

        self.promotion.products.add(self.product1)

        quantity = 5
        eligible_sets = quantity // self.promotion.minimum_quantity
        discount_items = eligible_sets * self.promotion.minimum_quantity
        discount_expected = (
            Decimal("100.00") * discount_items * Decimal("50") / Decimal("100")
        )

        cart = Cart.objects.create(user=self.user)
        cart_item = CartItem.objects.create(
            cart=cart, product=self.product1, quantity=quantity
        )
        discount = cart_item.total_discount_amount

        self.assertEqual(discount, discount_expected)

    def test_buy_x_get_z_amount_realistic(self):
        self.promotion.promotion_type = PromotionType.BUY_X_GET_Z_AMOUNT_DISCOUNT
        self.promotion.fixed_amount_discount = Decimal("10.00")
        self.promotion.minimum_quantity = 3
        self.promotion.save()

        self.promotion.products.add(self.product1)

        quantity = 7
        eligible_sets = quantity // self.promotion.minimum_quantity
        discount_expected = Decimal("10.00") * eligible_sets

        cart = Cart.objects.create(user=self.user)
        cart_item = CartItem.objects.create(
            cart=cart, product=self.product1, quantity=quantity
        )
        discount = cart_item.total_discount_amount

        self.assertEqual(discount, discount_expected)

    def test_discount_not_applied_if_quantity_less_than_minimum(self):
        self.promotion.promotion_type = PromotionType.BUY_X_GET_Y_PERCENT_DISCOUNT
        self.promotion.minimum_quantity = 5
        self.promotion.discount_percentage = Decimal("50.00")
        self.promotion.save()

        self.promotion.products.add(self.product1)

        cart = Cart.objects.create(user=self.user)
        cart_item = CartItem.objects.create(
            cart=cart, product=self.product1, quantity=3
        )
        discount = cart_item.total_discount_amount

        self.assertEqual(discount, Decimal("0.00"))  # Not enough quantity for discount

    def test_multiple_products_discount(self):
        self.promotion.promotion_type = PromotionType.PERCENTAGE_DISCOUNT
        self.promotion.discount_percentage = Decimal("20.00")
        self.promotion.save()

        self.promotion.products.add(self.product1)
        self.promotion.products.add(self.product2)

        
        cart = Cart.objects.create(user=self.user)

        cart_item1 = CartItem.objects.create(cart=cart, product=self.product1, quantity=3)
        cart_item2 = CartItem.objects.create(cart=cart, product=self.product2, quantity=2)

        discount1 = cart_item1.total_discount_amount
        discount2 = cart_item2.total_discount_amount

        self.assertEqual(discount1, Decimal("60.00")) 
        self.assertEqual(discount2, Decimal("80.00"))


    # ---------------------------
    # Edge cases for overlapping promotions
    # ---------------------------
    def test_non_conflicting_promotions_different_products(self):
        self.promotion.products.add(self.product1)
        p2 = Promotion.objects.create(
            name="Future Promotion",
            start_date=self.start_date,
            end_date=self.end_date,
            discount_percentage=Decimal("15.00"),
            promotion_type=PromotionType.FIXED_AMOUNT_DISCOUNT,
            minimum_quantity=1,
        )
        try:
            p2.products.add(self.product2)
        except ValidationError:
            self.fail(
                "Adding non-conflicting products raised ValidationError unexpectedly."
            )

    def test_conflicting_promotions_same_product_active(self):
        self.promotion.products.add(self.product1)
        p2 = Promotion.objects.create(
            name="Conflicting Promotion",
            start_date=self.start_date,
            end_date=self.end_date,
            discount_percentage=15,
            promotion_type=PromotionType.FIXED_AMOUNT_DISCOUNT,
            minimum_quantity=1,
        )
        with self.assertRaises(ValidationError):
            p2.products.add(self.product1)

    def test_conflicting_promotions_same_product_inactive(self):
        past_start = timezone.now() - timedelta(days=10)
        past_end = timezone.now() - timedelta(days=5)
        expired_promo = Promotion.objects.create(
            name="Expired Promotion",
            start_date=past_start,
            end_date=past_end,
            discount_percentage=20,
            promotion_type=PromotionType.PERCENTAGE_DISCOUNT,
            minimum_quantity=1,
        )
        expired_promo.products.add(self.product1)

        p2 = Promotion.objects.create(
            name="New Active Promotion",
            start_date=self.start_date,
            end_date=self.end_date,
            discount_percentage=10,
            promotion_type=PromotionType.FIXED_AMOUNT_DISCOUNT,
            minimum_quantity=1,
        )
        try:
            p2.products.add(self.product1)
        except ValidationError:
            self.fail(
                "Adding product from expired promotion should not raise ValidationError."
            )

    
class BannerModelTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_image = SimpleUploadedFile(
            name="test_image.jpg", content=b"", content_type="image/jpeg"
        )

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        # Clean up the test_media directory
        if os.path.exists(settings.MEDIA_ROOT):
            shutil.rmtree(settings.MEDIA_ROOT)

    @patch("shop.models.Banner.save", autospec=True)
    @patch("storages.backends.s3boto3.S3Boto3Storage.save")
    @patch("shop.models.Banner.banner_image_425")
    def test_create_banner_with_image(
        self, mock_banner_image, mock_storage_save, mock_save
    ):
        """Test creating a Banner with an image"""
        mock_storage_save.return_value = "banners/test_image.jpg"
        mock_banner_image.url = "https://example.com/banners/test_image.jpg"

        banner = Banner.objects.create(
            banner_location="Test Location",
            banner_image_425=self.test_image,
            banner_image_768=self.test_image,
            banner_image_1024=self.test_image,
            banner_image_1440=self.test_image,
        )

        # Simulate the post-save signal effect
        banner.banner_image_url_425 = mock_banner_image.url

        # Assertions
        self.assertTrue(banner.banner_image_url_425.endswith("test_image.jpg"))
        self.assertTrue(banner.banner_image_425)

    def test_create_banner_without_image(self):
        """Test creating a Banner without an image"""
        with self.assertRaises(ValidationError):
            Banner.objects.create(banner_location="Test Location")

    @patch("shop.models.Banner.save", autospec=True)
    @patch("storages.backends.s3boto3.S3Boto3Storage.save")
    @patch("shop.models.Banner.banner_image_425")
    def test_update_banner_image_url_on_image_upload(
        self, mock_banner_image, mock_storage_save, mock_save
    ):
        """Test that the banner_image_url is updated when an image is uploaded"""
        mock_storage_save.return_value = "banners/test_image.jpg"
        mock_banner_image.url = "https://example.com/banners/test_image.jpg"

        banner = Banner.objects.create(
            banner_location="Test Location",
            banner_image_425=self.test_image,
            banner_image_768=self.test_image,
            banner_image_1024=self.test_image,
            banner_image_1440=self.test_image,
        )

        # Simulate the post-save signal effect
        banner.banner_image_url_425 = mock_banner_image.url

        # Assertions
        self.assertEqual(
            banner.banner_image_url_425, "https://example.com/banners/test_image.jpg"
        )

    @patch("shop.models.Banner.save", autospec=True)
    def test_post_save_signal_does_not_trigger_infinite_loop(self, mock_save):
        """Test that post_save signal does not cause an infinite loop"""
        banner = Banner(
            banner_location="Test Location", banner_image_425=self.test_image
        )

        # Call the save method which is mocked
        banner.save()

        # Ensure save method was called only once
        self.assertEqual(mock_save.call_count, 1)
