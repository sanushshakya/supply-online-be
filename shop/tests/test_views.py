from django.core.files.uploadedfile import SimpleUploadedFile
import csv
import io
from django.test import TestCase, Client
from unittest.mock import patch, MagicMock
import datetime
from django.urls import reverse
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status
from decimal import Decimal
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from django.core.exceptions import PermissionDenied
from unittest.mock import Mock
import json
import uuid
import pandas as pd

from stripe import SignatureVerificationError

from shop.models import (
    Product,
    Category,
    SubCategory,
    Supplier,
    Review,
    Like,
    Order,
    OrderItem,
    Cart,
    CartItem,
    UserProfile,
    Notification,
    ProductDepartment,
    FeatureFlag,
    OrderPaymentStatus,
    OrderStatus,
    TaxCategory,
    LocationInStore,
    Promotion,
    DeliveryOption,
)


"""
    Since we will create model objects directly from django admin, we won't use APIs for CRUD operations on our models related to Product, Supplier and Category so, the list and retrieve apis test should be enough for these models

"""


def mock_send_email(
    subject, text_content, recipient_list, html_content=None, *args, **kwargs
):
    assert len(recipient_list) > 0
    return True


def mock_push_purchased_order_info_to_sqs_for_epos_backend(data_dict, queue_url):
    assert len(data_dict) > 0
    return True


class ProductViewSetTests(APITestCase):
    """
    When you use the APITestCase to make a request, it doesn't make a real HTTP request to the server.
    Instead, it simulates the request internally within the Django test framework.
    And, since the APITestCase operates within the test environment,
    it bypasses the network stack and directly calls the relevant view function

    """

    def setUp(self):
        self.category = Category.objects.create(name="Test Category")
        self.supplier = Supplier.objects.create(name="Test Supplier")
        self.tax_category = TaxCategory.objects.create(
            name="Zero tax", tax_rate=Decimal(0.00)
        )
        self.location_in_store = LocationInStore.objects.create(name="Aisle 6A")
        self.product_department = ProductDepartment.objects.create(
            name="Test Product Department"
        )
        self.product = Product.objects.create(
            name="Test Product",
            price=Decimal(10.00),
            barcode="1234567890",
            category=self.category,
            supplier=self.supplier,
            product_department=self.product_department,
            cost_price=12.00,
            profit_margin=20,
            description="Test description here",
            stock_quantity=10,
            ingredients="Test ingredients here",
            allergens="Test allergens here",
            net_contents="100g",
            preparation_and_usage="Test prep here",
            location_in_store=self.location_in_store,
            product_image_url="https://example.com",
            extra_info="Extra info here",
            tax_category=self.tax_category,
        )

        self.staff_user = User.objects.create(
            username="staffuser", password="password", is_staff=True
        )
        self.staff_user_access_token = str(
            RefreshToken.for_user(user=self.staff_user).access_token
        )

        self.superuser = User.objects.create(
            username="superuser", password="superuserpassword", is_superuser=True
        )
        self.superuser_access_token = str(
            RefreshToken.for_user(user=self.superuser).access_token
        )

        self.regular_user = User.objects.create(
            username="regularuser", password="regularpassword"
        )
        self.regular_user_access_token = str(
            RefreshToken.for_user(user=self.regular_user).access_token
        )

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.staff_user_access_token}"
        )

    def test_list_products(self):
        response = self.client.get("/shop/api/products/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_retrieve_product(self):
        fields_to_be_excluded = [
            "barcode",
            "cost_price",
            "profit_margin",
            "is_admin_approved",
            "created_at",
            "updated_at",
            "supplier",
            "location_in_store",
        ]
        response = self.client.get(f"/shop/api/products/{self.product.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Test Product")
        self.assertEqual(response.data["price"], "10.00")
        self.assertEqual(response.data["category"], 1)
        self.assertEqual(response.data["product_department"], 1)
        self.assertTrue("cost_price" not in response.data)
        self.assertTrue("profit_margin" not in response.data)
        self.assertEqual(response.data["description"], "Test description here")
        self.assertEqual(response.data["stock_quantity"], 10)
        self.assertEqual(response.data["ingredients"], "Test ingredients here")
        self.assertEqual(response.data["allergens"], "Test allergens here")
        self.assertEqual(response.data["net_contents"], "100g")
        self.assertEqual(response.data["preparation_and_usage"], "Test prep here")
        self.assertEqual(response.data["product_image_url"], "https://example.com")
        self.assertEqual(response.data["extra_info"], "Extra info here")
        self.assertEqual(
            set(fields_to_be_excluded).intersection(set(response.data.keys())), set()
        )

    def test_create_product(self):
        data = {
            "name": "New Product",
            "price": "15.99",
            "barcode": "9876543210",
            "category": self.category.id,  # use same category as in setUp
            "supplier": self.supplier.id,  # use same category as in setUp
            # use same product department as in setUp
            "product_department": self.product_department.id,
        }
        response = self.client.post("/shop/api/products/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Product.objects.count(), 2)

    def test_update_product(self):
        data = {
            "name": "Updated Product",
            "price": "12.99",
            "barcode": "0987654321",
            "category": self.category.id,  # use same category as in setUp
            "supplier": self.supplier.id,  # use same category as in setUp
            # use same product department as in setUp
            "product_department": self.product_department.id,
        }
        response = self.client.put(
            f"/shop/api/products/{self.product.id}/", data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Refresh the product instance from the database
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Updated Product")
        self.assertEqual(self.product.price, Decimal("12.99"))

    def test_partial_update_product(self):
        data = {"price": "14.99"}
        response = self.client.patch(
            f"/shop/api/products/{self.product.id}/", data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Refresh the product instance from the database
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal("14.99"))

    def test_delete_product(self):
        # try the delete operation using staff user
        response = self.client.delete(f"/shop/api/products/{self.product.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Product.objects.filter(id=self.product.id).exists())

        # try the delete operation using superuser
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.superuser_access_token}"
        )
        response = self.client.delete(f"/shop/api/products/{self.product.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Product.objects.filter(id=self.product.id).exists())

        # try the delete operation using regular user
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.regular_user_access_token}"
        )
        self.product2 = Product.objects.create(
            name="Test Product 2",
            price=Decimal(10.00),
            barcode="1234567890",
            category=self.category,
            supplier=self.supplier,
            product_department=self.product_department,
            cost_price=12.00,
            profit_margin=20,
            description="Test description here",
            stock_quantity="10",
            ingredients="Test ingredients here",
            allergens="Test allergens here",
            net_contents="100g",
            preparation_and_usage="Test prep here",
            location_in_store=self.location_in_store,
            product_image_url="https://example.com",
            extra_info="Extra info here",
            tax_category=self.tax_category,
        )

        response2 = self.client.delete(f"/shop/api/products/{self.product2.id}/")
        self.assertEqual(response2.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Product.objects.filter(id=self.product2.id).exists())

    def test_get_product_by_category(self):
        url = reverse("product-get-product-by-category")
        category_name = "Test Category"

        # Test with a valid category name
        response = self.client.get(url, {"category_name": category_name})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Assuming both products are in the same category
        self.assertEqual(len(response.data), 1)

        # Test with an invalid category name
        response = self.client.get(url, {"category_name": "Nonexistent Category"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_get_product_by_department(self):
        url = reverse("product-get-product-by-department")
        product_department_name = "Test Product Department"

        # Test with a valid category name
        response = self.client.get(
            url, {"product_department_name": product_department_name}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Assuming both products are in the same category
        self.assertEqual(len(response.data), 1)

        # Test with an invalid category name
        response = self.client.get(
            url, {"product_department_name": "Nonexistent Department"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_get_all_product_names_with_id(self):
        url = reverse("product-get-all-product-names-with-id")

        # Test the endpoint
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(str(self.product.product_id), response.json())
        self.assertEqual(response.json()[str(self.product.product_id)], "Test Product")

    def test_get_all_wholesale_products(self):
        # Create additional test data for wholesale products
        self.wholesale_product = Product.objects.create(
            name="Wholesale Product",
            price=Decimal(50.00),
            barcode="9876543210",
            category=self.category,
            supplier=self.supplier,
            product_department=self.product_department,
            cost_price=40.00,
            profit_margin=20,
            description="Wholesale description here",
            stock_quantity=50,
            ingredients="Wholesale ingredients here",
            allergens="Wholesale allergens here",
            net_contents="500g",
            preparation_and_usage="Wholesale prep here",
            location_in_store=self.location_in_store,
            product_image_url="https://example.com/wholesale",
            extra_info="Wholesale extra info here",
        )
        self.wholesale_product.unit_products.add(self.product)  # Link to retail product

        url = reverse("product-get-all-wholesale-products")

        # Test the endpoint
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_get_all_wholesale_products_no_data(self):
        # Create additional test data for wholesale products
        self.wholesale_product = Product.objects.create(
            name="Wholesale Product",
            price=Decimal(50.00),
            barcode="9876543210",
            category=self.category,
            supplier=self.supplier,
            product_department=self.product_department,
            cost_price=40.00,
            profit_margin=20,
            description="Wholesale description here",
            stock_quantity=50,
            ingredients="Wholesale ingredients here",
            allergens="Wholesale allergens here",
            net_contents="500g",
            preparation_and_usage="Wholesale prep here",
            location_in_store=self.location_in_store,
            product_image_url="https://example.com/wholesale",
            extra_info="Wholesale extra info here",
        )
        self.wholesale_product.unit_products.add(self.product)  # Link to retail product

        # Create a scenario where there are no wholesale products
        self.wholesale_product.unit_products.clear()  # Remove link to retail product

        url = reverse("product-get-all-wholesale-products")

        # Test the endpoint with no wholesale products
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    # tests for newly arrived products and best selling products are very basic for now
    def test_get_newly_arrived_products_within_30_days(self):
        # Ensure product is newly added within 30 days
        self.product.created_at = timezone.now() - timedelta(days=10)
        self.product.save()
        response = self.client.get("/shop/api/products/get-newly-arrived-products/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data) > 0, "Should return at least one product")
        self.assertEqual(
            response.data[0]["name"],
            self.product.name,
            "Should include the newly arrived product",
        )

    def test_get_best_seller_products_with_data(self):
        # Create multiple OrderItems for the product to simulate sales
        self.order = Order.objects.create(user=self.regular_user)
        for _ in range(10):
            OrderItem.objects.create(order=self.order, product=self.product, quantity=1)

        for i in range(20):
            Product.objects.create(
                name=f"product {i}", price=Decimal(2.99), stock_quantity=10
            )

        response = self.client.get("/shop/api/products/get-best-seller-products/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data) > 0, "Should return at least one product")
        self.assertIn(
            "name", response.data[0], "Response should include product details"
        )


class CategoryViewSetTests(APITestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Test Category")
        self.staff_user = User.objects.create(
            username="staffuser", password="password", is_staff=True
        )
        self.access_token = str(
            RefreshToken.for_user(user=self.staff_user).access_token
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_list_categories(self):
        response = self.client.get("/shop/api/categories/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_category(self):
        response = self.client.get(f"/shop/api/categories/{self.category.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # Add other test methods...


class ProductDepartmentViewSetTests(APITestCase):
    def setUp(self):
        self.product_department = ProductDepartment.objects.create(
            name="Test Product Department"
        )
        self.staff_user = User.objects.create(
            username="staffuser", password="password", is_staff=True
        )
        self.access_token = str(
            RefreshToken.for_user(user=self.staff_user).access_token
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_list_product_departments(self):
        response = self.client.get("/shop/api/productdepartments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_category(self):
        response = self.client.get(
            f"/shop/api/productdepartments/{self.product_department.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class SupplierViewSetTests(APITestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(name="Test Supplier")
        self.staff_user = User.objects.create(
            username="staffuser", password="password", is_staff=True
        )
        self.access_token = str(
            RefreshToken.for_user(user=self.staff_user).access_token
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_retrieve_without_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token invalid_token")
        response1 = self.client.get("/shop/api/suppliers/")
        self.assertEqual(response1.status_code, status.HTTP_401_UNAUTHORIZED)

        response2 = self.client.get(f"/shop/api/suppliers/{self.supplier.id}/")
        self.assertEqual(response2.status_code, status.HTTP_401_UNAUTHORIZED)

    # Add other test methods...


class LikeViewSetTests(APITestCase):
    def setUp(self):
        # Create users
        self.user = User.objects.create(username="testuser")
        self.user_profile = UserProfile.objects.create(user=self.user)

        # Create category and supplier
        self.category = Category.objects.create(name="Test Category")
        self.supplier = Supplier.objects.create(name="Test Supplier")

        # Create products
        self.product = Product.objects.create(
            name="Test Product",
            price=Decimal(10.99),
            barcode="1234567890",
            category=self.category,
            supplier=self.supplier,
        )

        # Create like
        self.like = Like.objects.create(user=self.user, product=self.product)

        # JWT token for authentication
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_liked_products_by_user_profile_id(self):
        # Valid request
        response = self.client.get(
            "/shop/api/likes/liked-products-by-user-profile-id/",
            {"user_profile_id": self.user_profile.user_profile_id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Invalid request - missing user_profile_id
        response = self.client.get("/shop/api/likes/liked-products-by-user-profile-id/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid request - non-existent user_profile_id
        response = self.client.get(
            "/shop/api/likes/liked-products-by-user-profile_id/",
            {"user_profile_id": str(uuid.uuid4())},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_like_product_by_user_profile_id(self):
        # Valid request

        product2 = Product.objects.create(
            name="Test Product2",
            price=Decimal(10.99),
            barcode="1234531890",
            category=self.category,
            supplier=self.supplier,
        )
        like_data = {
            "user_profile_id": self.user_profile.user_profile_id,
            "product_id": product2.product_id,
        }
        response = self.client.post(
            "/shop/api/likes/like-product-by-user-profile-id/", like_data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Invalid request - missing user_profile_id
        product3 = Product.objects.create(
            name="Test Product3",
            price=Decimal(10.99),
            barcode="123455120",
            category=self.category,
            supplier=self.supplier,
        )
        like_data = {
            "product_id": product3.product_id,
        }
        response = self.client.post(
            "/shop/api/likes/like-product-by-user-profile-id/", like_data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid request - missing product_id
        like_data = {
            "user_profile_id": self.user_profile.user_profile_id,
        }
        response = self.client.post(
            "/shop/api/likes/like-product-by-user-profile-id/", like_data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid request - non-existent user_profile_id
        like_data = {
            "user_profile_id": "invalid",
            "product_id": product3.product_id,
        }
        response = self.client.post(
            "/shop/api/likes/like-product-by-user-profile-id/", like_data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        import uuid

        # Invalid request - non-existent product_id
        like_data = {
            "user_profile_id": self.user_profile.user_profile_id,
            "product_id": str(uuid.uuid4()),
        }
        response = self.client.post(
            "/shop/api/likes/like-product-by-user-profile-id/", like_data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_crud_without_auth(self):
        self.client.credentials()  # Remove authentication

        # Attempt to retrieve likes without authentication
        response1 = self.client.get("/shop/api/likes/")
        self.assertEqual(response1.status_code, status.HTTP_401_UNAUTHORIZED)

        # Attempt to retrieve a single like without authentication
        response2 = self.client.get(f"/shop/api/likes/{self.like.id}/")
        self.assertEqual(response2.status_code, status.HTTP_401_UNAUTHORIZED)

        # Attempt to create a new like without authentication
        new_product = Product.objects.create(
            name="New Test Product",
            price=Decimal(14.99),
            barcode="12567890",
            category=self.category,
            supplier=self.supplier,
        )
        like_data = {
            "user": self.user.id,
            "product": new_product.id,
        }
        response3 = self.client.post("/shop/api/likes/", like_data, format="json")
        self.assertEqual(response3.status_code, status.HTTP_401_UNAUTHORIZED)

        # Attempt to update a like without authentication
        new_like_data = {
            "user": self.user.id,
            "product": self.product.id,
        }
        response4 = self.client.put(
            f"/shop/api/likes/{self.like.id}/", new_like_data, format="json"
        )
        self.assertEqual(response4.status_code, status.HTTP_401_UNAUTHORIZED)

        # Attempt to delete a like without authentication
        response5 = self.client.delete(f"/shop/api/likes/{self.like.id}/")
        self.assertEqual(response5.status_code, status.HTTP_401_UNAUTHORIZED)


class ReviewViewSetTests(APITestCase):
    def setUp(self):
        # Create users
        self.user = User.objects.create(username="testuser")
        self.user_profile = UserProfile.objects.create(user=self.user)

        # Create category and supplier
        self.category = Category.objects.create(name="Test Category")
        self.supplier = Supplier.objects.create(name="Test Supplier")

        # Create products
        self.product = Product.objects.create(
            name="Test Product",
            price=Decimal(10.99),
            barcode="1234567890",
            category=self.category,
            supplier=self.supplier,
        )

        # Create review
        self.review = Review.objects.create(
            user=self.user, product=self.product, text="Test Review"
        )

        # JWT token for authentication
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_reviewed_products_by_user_profile_id(self):
        # Valid request
        response = self.client.get(
            "/shop/api/reviews/reviewed-products-by-user-profile-id/",
            {"user_profile_id": self.user_profile.user_profile_id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Invalid request - missing user_profile_id
        response = self.client.get(
            "/shop/api/reviews/reviewed-products-by-user-profile-id/"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid request - non-existent user_profile_id
        response = self.client.get(
            "/shop/api/reviews/reviewed-products-by-user-profile-id/",
            {"user_profile_id": "invalid"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_review_by_user_profile_id(self):
        # Valid request
        review_data = {
            "user_profile_id": self.user_profile.user_profile_id,
            "product_id": self.product.product_id,
            "review": "Great product!",
        }
        response = self.client.post(
            "/shop/api/reviews/submit-review-by-user-profile-id/",
            review_data,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Invalid request - missing user_profile_id
        review_data = {
            "product_id": self.product.product_id,
            "review": "Great product!",
        }
        response = self.client.post(
            "/shop/api/reviews/submit-review-by-user-profile-id/",
            review_data,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid request - missing product_id
        review_data = {"user_profile_id": "user1", "review": "Great product!"}
        response = self.client.post(
            "/shop/api/reviews/submit-review-by-user-profile-id/",
            review_data,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid request - missing review text
        review_data = {
            "user_profile_id": self.user_profile.user_profile_id,
            "product_id": self.product.product_id,
        }
        response = self.client.post(
            "/shop/api/reviews/submit-review-by-user-profile-id/",
            review_data,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid request - non-existent user_profile_id
        review_data = {
            "user_profile_id": "invalid",
            "product_id": self.product.product_id,
            "review": "Great product!",
        }
        response = self.client.post(
            "/shop/api/reviews/submit-review-by-user-profile-id/",
            review_data,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid request - non-existent product_id
        review_data = {
            "user_profile_id": self.user_profile.user_profile_id,
            "product_id": str(uuid.uuid4()),
            "review": "Great product!",
        }
        response = self.client.post(
            "/shop/api/reviews/submit-review-by-user-profile-id/",
            review_data,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_crud_without_auth(self):
        self.client.credentials()  # Remove authentication

        # Attempt to retrieve reviews without authentication
        response1 = self.client.get("/shop/api/reviews/")
        self.assertEqual(response1.status_code, status.HTTP_401_UNAUTHORIZED)

        # Attempt to retrieve a single review without authentication
        response2 = self.client.get(f"/shop/api/reviews/{self.review.id}/")
        self.assertEqual(response2.status_code, status.HTTP_401_UNAUTHORIZED)

        # Attempt to create a new review without authentication
        new_product = Product.objects.create(
            name="New Test Product",
            price=Decimal(14.99),
            barcode="12567890",
            category=self.category,
            supplier=self.supplier,
        )
        review_data = {
            "user": self.user.id,
            "product": new_product.id,
            "text": "This is a sample test review",
        }
        response3 = self.client.post("/shop/api/reviews/", review_data, format="json")
        self.assertEqual(response3.status_code, status.HTTP_401_UNAUTHORIZED)

        # Attempt to update a review without authentication
        new_review_data = {
            "user": self.user.id,
            "product": self.product.id,
            "text": "This is updated review",
        }
        response4 = self.client.put(
            f"/shop/api/reviews/{self.review.id}/", new_review_data, format="json"
        )
        self.assertEqual(response4.status_code, status.HTTP_401_UNAUTHORIZED)

        # Attempt to delete a review without authentication
        response5 = self.client.delete(f"/shop/api/reviews/{self.review.id}/")
        self.assertEqual(response5.status_code, status.HTTP_401_UNAUTHORIZED)


class UserProfileViewSetTests(APITestCase):
    def setUp(self):
        self.user_data = {
            "password": "test_password",
            "email": "xyz@gmail.com",
            "user_type": "general customer",
            "mobile_number": "1234567890",
            "fullname": "Test User",
            "marketing_preference": True,
        }

        # Create some test products
        self.category1 = Category.objects.create(name="Category 1")
        self.category2 = Category.objects.create(name="Category 2")
        self.supplier = Supplier.objects.create(name="Supplier 1")

        self.product1 = Product.objects.create(
            name="Test Product1",
            price=Decimal(10.00),
            barcode="1234567890",
            category=self.category1,
            supplier=self.supplier,
            stock_quantity=10,
        )
        self.product2 = Product.objects.create(
            name="Test Product2",
            price=Decimal(9.00),
            barcode="1234512890",
            category=self.category2,
            supplier=self.supplier,
            stock_quantity=10,
        )
        self.product3 = Product.objects.create(
            name="Test Product3",
            price=Decimal(8.00),
            barcode="1234417890",
            category=self.category1,
            supplier=self.supplier,
            stock_quantity=10,
        )
        self.product4 = Product.objects.create(
            name="Test Product4",
            price=Decimal(7.00),
            barcode="21337890",
            category=self.category1,
            supplier=self.supplier,
            stock_quantity=10,
        )
        self.product3 = Product.objects.create(
            name="Test Product5",
            price=Decimal(6.00),
            barcode="312312343",
            category=self.category2,
            supplier=self.supplier,
            stock_quantity=10,
        )

    def test_register(self):
        response = self.client.post("/shop/api/users/register/", self.user_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = User.objects.get(email=self.user_data["email"])
        user_profile = UserProfile.objects.get(user=user)

        self.assertEqual(user_profile.mobile_number, self.user_data["mobile_number"])
        self.assertTrue("password" not in response.data)
        self.assertTrue("user" not in response.data)
        self.assertEqual(user_profile.user, user)
        self.assertEqual(user_profile.marketing_preference, True)

    def test_login(self):
        """Test user login api"""

        self.client.post("/shop/api/users/register/", self.user_data)

        # manually set the account as activated
        user = User.objects.get(email=self.user_data["email"])
        user.userprofile.is_account_activated = True
        user.userprofile.full_clean()
        user.userprofile.save()

        response = self.client.post("/shop/api/users/login/", self.user_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertTrue("password" not in response.data)
        self.assertTrue("user" not in response.data)
        self.assertEqual(response.data["email"], self.user_data["email"])

    def test_invalid_login(self):
        invalid_user_data = {"username": "testuser", "password": "invalidpwd"}
        response = self.client.post("/shop/api/users/login/", invalid_user_data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.post("/shop/api/users/login/", {})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_register(self):
        response = self.client.post("/shop/api/users/register/", {})
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_superuser_staff_register(self):
        # test whether the api call throws bad request error or not
        user_data1 = self.user_data
        user_data1["is_superuser"] = True
        response = self.client.post("/shop/api/users/register/", user_data1)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        user_data2 = self.user_data
        user_data2["is_staff"] = True
        response = self.client.post("/shop/api/users/register/", user_data2)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resend_activation(self):
        self.client.post("/shop/api/users/register/", self.user_data)
        data = {"email": "xyz@gmail.com", "password": "test_password"}
        with patch(
            "shop.views.UserProfileViewSet.send_activation_email"
        ) as send_activation_email_mock:
            send_activation_email_mock.return_value = True
            response = self.client.post("/shop/api/users/resend-activation/", data)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            send_activation_email_mock.assert_called_once()

    def test_resend_activation_invalid_credentials(self):
        self.client.post("/shop/api/users/register/", self.user_data)
        data = {"email": "xyz@gmail.com", "password": "invalid_password"}
        response = self.client.post("/shop/api/users/resend-activation/", data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_request_password_reset_link(self):
        self.client.post("/shop/api/users/register/", self.user_data)
        response = self.client.post(
            "/shop/api/users/request-password-reset-link/", {"email": "xyz@gmail.com"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_request_password_reset_link_invalid_email(self):
        response = self.client.post(
            "/shop/api/users/request-password-reset-link/",
            {"email": "invalidemail@test.com"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_password(self):
        self.client.post("/shop/api/users/register/", self.user_data)

        dummy_pwd_reset_token = "dummypasswordresettoken"
        with patch("shop.views.jwt") as jwt_mock:
            jwt_mock.encode.return_value = dummy_pwd_reset_token
            self.client.post(
                "/shop/api/users/request-password-reset-link/",
                {"email": "xyz@gmail.com"},
            )

        user = User.objects.get(username=self.user_data["email"])
        user.userprofile.is_account_activated = True
        user.userprofile.save()

        payload = {"token": dummy_pwd_reset_token, "new_password": "newpassword123"}
        # test for the case when the token is valid
        with patch("shop.views.jwt") as jwt_mock:
            jwt_mock.decode.return_value = {
                "email": self.user_data["email"],
                "user_profile_id": str(
                    User.objects.get(
                        username=self.user_data["email"]
                    ).userprofile.user_profile_id
                ),
                "exp": (
                    datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
                ).timestamp(),
            }
            response = self.client.put("/shop/api/users/update-password/", payload)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

            login_with_old_pwd = self.client.post(
                "/shop/api/users/login/", self.user_data
            )
            from copy import copy

            self.assertEqual(
                login_with_old_pwd.status_code, status.HTTP_401_UNAUTHORIZED
            )
            updated_user_data = copy(self.user_data)
            updated_user_data["password"] = payload["new_password"]
            login_with_new_pwd = self.client.post(
                "/shop/api/users/login/", updated_user_data
            )
            self.assertEqual(login_with_new_pwd.status_code, status.HTTP_200_OK)

        # test for the case when the token is expired
        with patch("shop.views.jwt") as jwt_mock:
            jwt_mock.decode.return_value = {
                "email": self.user_data["email"],
                "user_profile_id": str(
                    User.objects.get(
                        username=self.user_data["email"]
                    ).userprofile.user_profile_id
                ),
                "exp": (
                    datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=3)
                ).timestamp(),
            }
            response = self.client.put("/shop/api/users/update-password/", payload)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_product_recommendation_for_user(self):
        self.user = User.objects.create_user(
            username="testuser_no_orders",
            email="test_no_orders@example.com",
            password="password",
            first_name="Jane",
            last_name="Smith",
        )
        self.user_profile = UserProfile.objects.create(
            user=self.user, fullname="Jane Smith"
        )

        self.user_access_token = str(RefreshToken.for_user(user=self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_access_token}")

        # Create some test orders for the user
        self.order1 = Order.objects.create(user=self.user)
        self.order2 = Order.objects.create(user=self.user)

        # Add order items
        self.order_item1 = OrderItem.objects.create(
            order=self.order1, product=self.product1, quantity=1, base_total=10.0
        )
        self.order_item2 = OrderItem.objects.create(
            order=self.order1, product=self.product2, quantity=2, base_total=9.0
        )
        self.order_item3 = OrderItem.objects.create(
            order=self.order2, product=self.product3, quantity=1, base_total=8.0
        )

        # URL and query parameters
        url = reverse("userprofile-get-product-recommendation-for-user")
        query_params = {"user_profile_id": self.user_profile.user_profile_id}

        # Perform the request to get product recommendations
        response = self.client.get(url, query_params)

        # Assert the response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            len(response.data), 2
        )  # because we have created product4 and product5 that belong to category 1 and category 2

        # Assert the structure and content of each product in the response
        for product_data in response.data:
            self.assertIn("name", product_data)
            self.assertIn("category", product_data)
            self.assertIn(
                product_data["category"], [self.category1.id, self.category2.id]
            )

    def test_get_product_recommendation_for_user_no_orders(self):
        self.user = User.objects.create_user(
            username="testuser_no_orders",
            email="test_no_orders@example.com",
            password="password",
            first_name="Jane",
            last_name="Smith",
        )
        self.user_profile = UserProfile.objects.create(
            user=self.user, fullname="Jane Smith"
        )

        self.user_access_token = str(RefreshToken.for_user(user=self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_access_token}")

        # Test case where user has no orders
        url = reverse("userprofile-get-product-recommendation-for-user")
        query_params = {"user_profile_id": self.user_profile.user_profile_id}

        response = self.client.get(url, query_params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_register_driver(self):
        self.url = reverse("userprofile-register-driver")
        self.valid_payload = {
            "email": "testdriver@example.com",
            "nationality": "American",
            "fullname": "John Doe",
            "mobile_number": "1234567890",
            "right_to_work": True,
        }
        response = self.client.post(self.url, self.valid_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            User.objects.filter(username=self.valid_payload["email"]).exists()
        )
        self.assertTrue(
            UserProfile.objects.filter(
                user__username=self.valid_payload["email"]
            ).exists()
        )

        # should not allow to register if fields are missing
        invalid_payload = self.valid_payload.copy()
        invalid_payload.pop("fullname")
        response = self.client.post(self.url, invalid_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)
        self.assertEqual(
            response.data["detail"],
            "Bad request. All the required fields are not present",
        )

        # should not allow to register as superuser
        invalid_payload = self.valid_payload.copy()
        invalid_payload["is_superuser"] = True
        response = self.client.post(self.url, invalid_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)
        self.assertEqual(
            response.data["detail"],
            "Bad request. You are not allowed to register as a superuser or a staff",
        )

        # should not allow to register as staff
        invalid_payload.pop("is_superuser")
        invalid_payload["is_staff"] = True
        response = self.client.post(self.url, invalid_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)
        self.assertEqual(
            response.data["detail"],
            "Bad request. You are not allowed to register as a superuser or a staff",
        )

        # should not allow user duplication
        response = self.client.post(self.url, self.valid_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)
        self.assertEqual(response.data["error"], "User with this email already exists")

    def test_update_password_while_logged_in(self):
        self.user = User.objects.create_user(
            username="testuser@example.com",
            email="testuser@example.com",
            password="oldpassword",
        )
        self.user_profile = UserProfile.objects.create(
            user=self.user, is_account_activated=True
        )
        self.refresh_token = RefreshToken.for_user(self.user)

        # Login the user to get initial tokens
        login_url = reverse("userprofile-login")
        login_data = {
            "email": "testuser@example.com",
            "password": "oldpassword",
        }
        response = self.client.post(login_url, login_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response.data)
        self.assertIn("refresh_token", response.data)
        from copy import copy

        initial_access_token = copy(response.data["access_token"])
        initial_refresh_token = copy(response.data["refresh_token"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {initial_access_token}")

        # Update password while logged in
        update_password_url = reverse("userprofile-update-password-while-logged-in")
        new_password_data = {
            "old_password": "oldpassword",
            "new_password": "newpassword",
            "user_profile_id": self.user_profile.user_profile_id,
        }
        response = self.client.put(
            update_password_url, new_password_data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response.data)
        self.assertIn("refresh_token", response.data)
        new_refresh_token = response.data["refresh_token"]

        # Attempt to refresh old refresh token should fail
        refresh_old_refresh_response = self.client.post(
            reverse("userprofile-refresh-token"),
            {"refresh_token": initial_refresh_token},
        )
        self.assertEqual(
            refresh_old_refresh_response.status_code, status.HTTP_400_BAD_REQUEST
        )

        # Refresh new refresh token should succeed
        refresh_new_refresh_response = self.client.post(
            reverse("userprofile-refresh-token"), {"refresh_token": new_refresh_token}
        )
        self.assertEqual(refresh_new_refresh_response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", refresh_new_refresh_response.data)


class OrderViewSetTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        # Create the OrderFeatureFlag object if it doesn't exist
        if not FeatureFlag.objects.filter(name="is_ordering_enabled").exists():
            FeatureFlag.objects.create(name="is_ordering_enabled", enabled=True)

    def setUp(self):
        self.user = User.objects.create(username="testuser")
        self.user_profile = UserProfile.objects.create(
            user=self.user, user_type="general customer", fullname="Test User"
        )
        self.order = Order.objects.create(
            user=self.user, status="Pending", is_temporary=False
        )

        self.category = Category.objects.create(name="Test Category")
        self.supplier = Supplier.objects.create(name="Test Supplier")
        self.tax_category = TaxCategory.objects.create(
            name="Tax@20", tax_rate=Decimal("20.00")
        )
        self.product1 = Product.objects.create(
            name="Test Product",
            price=Decimal(10.99),
            barcode="1234567890",
            category=self.category,
            supplier=self.supplier,
            tax_category=self.tax_category,
            stock_quantity=10,
        )
        self.product2 = Product.objects.create(
            name="Test Product2",
            price=Decimal(12.99),
            barcode="123456120",
            category=self.category,
            supplier=self.supplier,
            stock_quantity=10,
        )

        refresh = RefreshToken.for_user(user=self.user)
        self.access_token = str(refresh.access_token)
        self.refresh_token = str(refresh)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_orders_by_user_profile_id(self):
        # Test with a valid user_profile_id
        response1 = self.client.get(
            "/shop/api/orders/orders-by-user-profile-id/",
            {"user_profile_id": self.user.userprofile.user_profile_id},
        )
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        # Assuming only one order for the user
        self.assertEqual(len(response1.data), 1)

        # Test without providing user_profile_id
        response2 = self.client.get("/shop/api/orders/orders-by-user-profile-id/")
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)

        # Test with an invalid user_profile_id
        response3 = self.client.get(
            "/shop/api/orders/orders-by-user-profile-id/",
            {"user_profile_id": "invalid"},
        )
        self.assertEqual(response3.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response3.data)

        # create new user and set the new tokens in the client
        new_user = User.objects.create(username="New test user")
        UserProfile.objects.create(
            user=new_user, user_type="general customer", fullname="New user"
        )

        refresh = RefreshToken.for_user(user=new_user)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}"
        )
        # try to access the orders of original user
        response4 = self.client.get(
            "/shop/api/orders/orders-by-user-profile-id/",
            {"user_profile_id": self.user.userprofile.user_profile_id},
        )
        self.assertEqual(response4.status_code, status.HTTP_400_BAD_REQUEST)

    def test_crud_with_auth(self):
        order_data = {
            "user": self.user.id,
            "status": "Pending",
            "delivery_type": "Standard",
        }

        # Test create order
        response1 = self.client.post("/shop/api/orders/", order_data, format="json")
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        # Test retrieve order
        response2 = self.client.get(f"/shop/api/orders/{response1.data['id']}/")
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        # Test update order
        updated_order_data = {
            "user": response1.data["user"],
            "status": "Dispatched",
            "delivery_type": "Standard",
        }
        response3 = self.client.put(
            f"/shop/api/orders/{response1.data['id']}/",
            updated_order_data,
            format="json",
        )
        self.assertEqual(response3.status_code, status.HTTP_200_OK)
        self.assertEqual(response3.data["status"], updated_order_data["status"])

        # New user shouldnot be allowed to hit any requests against the object of original user
        new_user = User.objects.create(username="Test user 2")
        refresh = RefreshToken.for_user(user=new_user)
        new_user_access_token = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_user_access_token}")
        response4 = self.client.get(f"/shop/api/orders/{response1.data['id']}/")
        self.assertEqual(response4.status_code, status.HTTP_403_FORBIDDEN)

        response5 = self.client.put(
            f"/shop/api/orders/{response1.data['id']}/",
            updated_order_data,
            format="json",
        )
        self.assertEqual(response5.status_code, status.HTTP_403_FORBIDDEN)

        response6 = self.client.delete(f"/shop/api/orders/{response1.data['id']}/")
        self.assertEqual(response6.status_code, status.HTTP_403_FORBIDDEN)

        # Put back the credentials of the original user and test delete order
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        response7 = self.client.delete(f"/shop/api/orders/{response1.data['id']}/")
        self.assertEqual(response7.status_code, status.HTTP_204_NO_CONTENT)

    # Mock the send_email function
    @patch("shop.views.send_email", side_effect=mock_send_email)
    def test_create_order_from_cart(
        self,
        mock_send_email
    ):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        url = "/shop/api/orders/create-order-from-cart/"

        delivery_option = DeliveryOption.objects.create(
            name="standard", delivery_fee=Decimal("2.99"), max_weight_allowed_in_kg=2.00
        )
        self.cart = Cart.objects.create(user=self.user, delivery_option=delivery_option)
        self.cart_item = CartItem.objects.create(
            cart=self.cart, product=self.product1, quantity=2
        )

        # Define the request data
        data = {
            "user_profile_id": self.user_profile.user_profile_id,
            "cart_id": self.cart.cart_id,
            "dispatch_method": "Click & Collect",
            "delivery_type": "standard",
            "stripe_payment_session_id": "paymentid123",
        }

        # Make a POST request to the endpoint
        response = self.client.post(url, data, format="json")

        # Check if the response status code is 201 (Created)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Check if send_email function was called with the correct arguments
        mock_send_email.assert_called_once()

        # create new user and set the new tokens in the client
        # try to create the order for the original user with this new user tokens
        new_user = User.objects.create(username="New test user")
        UserProfile.objects.create(
            user=new_user, user_type="general customer", fullname="New user"
        )

        refresh = RefreshToken.for_user(user=new_user)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}"
        )
        # try to access the orders of original user
        response2 = self.client.post(url, data, format="json")
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_crud_with_invalid_auth(self):
        # Test create order with invalid token
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid_token")
        order_data = {"user": self.user.id, "status": "Pending"}
        response1 = self.client.post("/shop/api/orders/", order_data, format="json")
        self.assertEqual(response1.status_code, status.HTTP_401_UNAUTHORIZED)

        # Test update order with invalid token
        updated_order_data = {
            "status": "Shipped",
        }
        response2 = self.client.put(
            f"/shop/api/orders/{self.order.id}/", updated_order_data, format="json"
        )
        self.assertEqual(response2.status_code, status.HTTP_401_UNAUTHORIZED)

        # Test delete order with invalid token
        response3 = self.client.delete(f"/shop/api/orders/{self.order.id}/")
        self.assertEqual(response3.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_crud_without_auth(self):
        self.client.credentials()
        response1 = self.client.get("/shop/api/orders/")
        self.assertEqual(response1.status_code, status.HTTP_401_UNAUTHORIZED)

        response2 = self.client.get(f"/shop/api/orders/{self.order.id}/")
        self.assertEqual(response2.status_code, status.HTTP_401_UNAUTHORIZED)

        order_data = {"user": self.user.id, "status": "Pending"}
        response3 = self.client.post("/shop/api/orders/", order_data, format="json")
        self.assertEqual(response3.status_code, status.HTTP_401_UNAUTHORIZED)

        new_order_data = {
            "user": self.user.id,
            "status": "Dispatched",
        }
        response4 = self.client.put(
            f"/shop/api/orders/{self.user.id}/", new_order_data, format="json"
        )
        self.assertEqual(response4.status_code, status.HTTP_401_UNAUTHORIZED)

        response5 = self.client.delete(f"/shop/api/orders/{self.user.id}/")
        self.assertEqual(response5.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_crud_with_feature_flag_disabled(self):
        order_feature_flag = FeatureFlag.objects.get(name="is_ordering_enabled")
        order_feature_flag.enabled = False
        order_feature_flag.full_clean()
        order_feature_flag.save()

        order_data = {"user": self.user.id, "status": "Pending"}

        # Test create order
        response1 = self.client.post("/shop/api/orders/", order_data, format="json")
        self.assertEqual(response1.status_code, status.HTTP_403_FORBIDDEN)

        # Test retrieve order
        response2 = self.client.get(f"/shop/api/orders/{self.order.id}/")
        self.assertEqual(response2.status_code, status.HTTP_403_FORBIDDEN)

        # Test update order
        updated_order_data = {
            "user": self.user.id,
            "status": "Dispatched",
        }
        response3 = self.client.put(
            f"/shop/api/orders/{self.order.id}/",
            updated_order_data,
            format="json",
        )
        self.assertEqual(response3.status_code, status.HTTP_403_FORBIDDEN)

        # Test delete order
        response4 = self.client.delete(f"/shop/api/orders/{self.order.id}/")
        self.assertEqual(response4.status_code, status.HTTP_403_FORBIDDEN)


class OrderItemViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create(username="testuser")
        self.category = Category.objects.create(name="Test Category")
        self.supplier = Supplier.objects.create(name="Test Supplier")
        self.product = Product.objects.create(
            name="Test Product",
            price=Decimal(10.99),
            barcode="1234567890",
            category=self.category,
            supplier=self.supplier,
        )
        self.order = Order.objects.create(user=self.user, status="Pending")
        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
        )

    def test_crud_without_auth(self):
        response1 = self.client.get("/shop/api/orderitems/")
        self.assertEqual(response1.status_code, status.HTTP_401_UNAUTHORIZED)

        response2 = self.client.get(f"/shop/api/orderitems/{self.order_item.id}/")
        self.assertEqual(response2.status_code, status.HTTP_401_UNAUTHORIZED)

        order_item_data = {
            "order": self.order.id,
            "product": self.product.id,
            "quantity": 2,
            "base_total": "21.98",
        }
        response3 = self.client.post(
            "/shop/api/orderitems/", order_item_data, format="json"
        )
        self.assertEqual(response3.status_code, status.HTTP_401_UNAUTHORIZED)

        new_order_item_data = {
            "order": self.order.id,
            "product": self.product.id,
            "quantity": 3,
            "base_total": "32.97",
        }
        response4 = self.client.put(
            f"/shop/api/orderitems/{self.order.id}/", new_order_item_data, format="json"
        )
        self.assertEqual(response4.status_code, status.HTTP_401_UNAUTHORIZED)

        response5 = self.client.delete(f"/shop/api/orderitems/{self.order.id}/")
        self.assertEqual(response5.status_code, status.HTTP_401_UNAUTHORIZED)


class CartViewSetTests(APITestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Test Category")
        self.supplier = Supplier.objects.create(name="Test Supplier")
        self.product1 = Product.objects.create(
            name="Test Product",
            price=Decimal(10.99),
            barcode="1234567890",
            category=self.category,
            supplier=self.supplier,
        )
        self.product2 = Product.objects.create(
            name="Test Product2",
            price=Decimal(12.99),
            barcode="123456120",
            category=self.category,
            supplier=self.supplier,
        )

        self.user = User.objects.create(email="testuser@gmail.com")
        self.userprofile = UserProfile.objects.create(
            user=self.user, fullname="Test User", user_type="general customer"
        )
        self.cart = Cart.objects.create(user=self.user)
        refresh = RefreshToken.for_user(user=self.user)
        self.access_token = str(refresh.access_token)
        self.refresh_token = str(refresh)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_crud_without_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid_token")
        response1 = self.client.get("/shop/api/carts/")
        self.assertEqual(response1.status_code, status.HTTP_401_UNAUTHORIZED)

        response2 = self.client.get(f"/shop/api/carts/{self.cart.id}/")
        self.assertEqual(response2.status_code, status.HTTP_401_UNAUTHORIZED)

        # we can't use the same user as in setUp because one user can have only one cart
        new_user = User.objects.create(username="newtestuser")
        cart_data = {"user": new_user.id}
        response3 = self.client.post("/shop/api/carts/", cart_data, format="json")
        self.assertEqual(response3.status_code, status.HTTP_401_UNAUTHORIZED)

        new_cart_data = {"user": self.user.id}
        response4 = self.client.put(
            f"/shop/api/carts/{self.user.id}/", new_cart_data, format="json"
        )
        self.assertEqual(response4.status_code, status.HTTP_401_UNAUTHORIZED)

        response5 = self.client.delete(f"/shop/api/carts/{self.user.id}/")
        self.assertEqual(response5.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_add_item_to_cart(self):
        # cart quantities are limited to available stock
        Product.objects.filter(pk=self.product1.pk).update(stock_quantity=10)
        # intially the cart total_amount should be zero since there are no cart_items in it
        self.assertEqual(self.cart.total_amount, 0.00)
        data = {
            "cart_id": self.cart.cart_id,
            "product_id": self.product1.product_id,
            "quantity": 2,
        }
        response = self.client.post(
            "/shop/api/carts/add-item-to-cart/", data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("cart_items", response.data)
        self.assertEqual(len(response.data["cart_items"]), 1)
        self.assertEqual(response.data["total_amount"], "21.98")

        # if the same product is added again, the quantity should add up
        response = self.client.post(
            "/shop/api/carts/add-item-to-cart/", data, format="json"
        )
        self.assertEqual(len(response.data["cart_items"]), 1)
        self.assertEqual(response.data["cart_items"][0]["quantity"], 4)
        self.assertEqual(response.data["total_amount"], "43.96")

        self.product1.is_active = False
        self.product1.save()
        self.product1.refresh_from_db()
        response2 = self.client.post(
            "/shop/api/carts/add-item-to-cart/", data, format="json"
        )
        self.assertEqual(response2.status_code, 400)
        self.assertEqual(
            response2.data["error"],
            "Product is no longer available. Please remove it from your cart",
        )

    def test_remove_item_from_cart(self):
        CartItem.objects.create(cart=self.cart, product=self.product1, quantity=2)

        self.cart.save()

        data = {
            "cart_id": self.cart.cart_id,
            "product_id": self.product1.product_id,
            "quantity": 1,
        }
        response = self.client.post(
            "/shop/api/carts/remove-item-from-cart/", data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # the decimal fields are serialised as strings in django by default to maintain precision
        # we can parse the value as float on the frontend side
        # however when the decimal fields are accessed direclty using the object reference, it appears as a float value
        self.assertEqual(response.data["total_amount"], "10.99")
        self.assertIn("cart_items", response.data)
        self.assertEqual(len(response.data["cart_items"]), 1)
        self.assertEqual(response.data["cart_items"][0]["quantity"], 1)

        # try to remove more than what is in the cart
        data["quantity"] = 2
        response = self.client.post(
            "/shop/api/carts/remove-item-from-cart/", data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["error"],
            "Can't remove more than what is available in the cart",
        )

        # try to remove the deactivated product, this should be allowed
        self.product1.is_active = False
        data["quantity"] = 1
        response = self.client.post(
            "/shop/api/carts/remove-item-from-cart/", data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # try to set the cart total amount value to negative
        with self.assertRaises(Exception):
            self.cart.total_amount = -10.99
            self.cart.full_clean()
            self.cart.save()

    def test_cart_by_user_profile_id(self):
        data = {"user_profile_id": self.userprofile.user_profile_id}
        response = self.client.post(
            "/shop/api/carts/cart-by-user-profile-id/", data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("cart_items", response.data)
        # No items should be present in a new cart
        self.assertEqual(len(response.data["cart_items"]), 0)

        # create new user and set the new tokens in the client
        # try to create the cart for the original user with this new user tokens
        new_user = User.objects.create(username="New test user")
        UserProfile.objects.create(
            user=new_user, user_type="general customer", fullname="New user"
        )

        refresh = RefreshToken.for_user(user=new_user)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}"
        )
        # try to access the carts of original user
        response2 = self.client.post(
            "/shop/api/carts/cart-by-user-profile-id/", data, format="json"
        )
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_payment_checkout_session(self):
        Product.objects.filter(
            pk__in=[self.product1.pk, self.product2.pk]
        ).update(stock_quantity=10)
        CartItem.objects.create(cart=self.cart, product=self.product1, quantity=2)
        CartItem.objects.create(cart=self.cart, product=self.product2, quantity=1)

        # Mocking stripe checkout session creation
        with patch("stripe.checkout.Session.create") as create_session_mock:
            # Set up mock response from Stripe
            client_secret = "client_secret"
            id = "id"
            create_session_mock.return_value = MagicMock(
                client_secret=client_secret, id=id
            )

            # Send a POST request to create a payment checkout session
            data = {
                "user_profile_id": str(self.userprofile.user_profile_id),
                "cart_id": str(self.cart.cart_id),
            }
            response = self.client.post(
                "/shop/api/carts/create-payment-checkout-session/", data
            )

            # Check if the response is successful and contains the client secret
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn("clientSecret", response.data)
            self.assertIn("sessionId", response.data)
            self.assertEqual(response.data["clientSecret"], client_secret)
            self.assertEqual(response.data["sessionId"], id)

    def test_session_status(self):
        # Mocking stripe checkout session retrieval
        with patch("stripe.checkout.Session.retrieve") as retrieve_session_mock:
            # Set up mock response from Stripe
            session_id = "session_id"
            mock_session = MagicMock()
            mock_session.status = "completed"
            mock_customer_details = MagicMock()
            mock_customer_details.email = "test@example.com"
            mock_session.customer_details = mock_customer_details
            retrieve_session_mock.return_value = mock_session

            # Send a GET request to retrieve session status
            response = self.client.get(
                f"/shop/api/carts/session-status/?session_id={session_id}"
            )

            # Check if the response is successful and contains the session status and customer email
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn("status", response.data)
            self.assertEqual(response.data["status"], "completed")
            self.assertIn("customer_email", response.data)
            self.assertEqual(response.data["customer_email"], "test@example.com")


class CartItemViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create(username="testuser")
        self.category = Category.objects.create(name="Test Category")
        self.supplier = Supplier.objects.create(name="Test Supplier")
        self.product = Product.objects.create(
            name="Test Product",
            price=Decimal(10.99),
            barcode="1234567890",
            category=self.category,
            supplier=self.supplier,
        )
        self.cart = Cart.objects.create(user=self.user)
        self.cart_item = CartItem.objects.create(
            cart=self.cart, product=self.product, quantity=2
        )

    def test_crud_without_auth(self):
        response1 = self.client.get("/shop/api/cartitems/")
        self.assertEqual(response1.status_code, status.HTTP_401_UNAUTHORIZED)

        response2 = self.client.get(f"/shop/api/cartitems/{self.cart_item.id}/")
        self.assertEqual(response2.status_code, status.HTTP_401_UNAUTHORIZED)

        cart_item_data = {
            "cart": self.cart.id,
            "product": self.product.id,
            "quantity": 2,
        }
        response3 = self.client.post(
            "/shop/api/cartitems/", cart_item_data, format="json"
        )
        self.assertEqual(response3.status_code, status.HTTP_401_UNAUTHORIZED)

        new_cart_item_data = {
            "cart": self.cart.id,
            "product": self.product.id,
            "quantity": 3,
        }
        response4 = self.client.put(
            f"/shop/api/cartitems/{self.cart.id}/", new_cart_item_data, format="json"
        )
        self.assertEqual(response4.status_code, status.HTTP_401_UNAUTHORIZED)

        response5 = self.client.delete(f"/shop/api/cartitems/{self.cart.id}/")
        self.assertEqual(response5.status_code, status.HTTP_401_UNAUTHORIZED)


class PromotionViewSetTest(APITestCase):
    def setUp(self):
        now = timezone.now()

        # Create some sample promotions
        self.active_promotion = Promotion.objects.create(
            name="Active Promo",
            description="A currently active promotion",
            start_date=now - timedelta(days=5),
            end_date=now + timedelta(days=5),
            active=True,
            discount_percentage=20.00,
            minimum_quantity=1,
        )

        self.inactive_promotion = Promotion.objects.create(
            name="Inactive Promo",
            description="An expired promotion",
            start_date=now - timedelta(days=10),
            end_date=now - timedelta(days=5),
            active=True,
            discount_percentage=15.00,
            minimum_quantity=1,
        )

        self.future_promotion = Promotion.objects.create(
            name="Future Promo",
            description="A promotion that starts in the future",
            start_date=now + timedelta(days=5),
            end_date=now + timedelta(days=10),
            active=True,
            discount_percentage=10.00,
            minimum_quantity=1,
        )

        self.staff_user = User.objects.create(
            username="staffuser", password="password", is_staff=True
        )
        self.staff_access_token = str(
            RefreshToken.for_user(user=self.staff_user).access_token
        )

        self.superuser = User.objects.create(
            username="superuser", password="superuserpassword", is_superuser=True
        )
        self.superuser_access_token = str(
            RefreshToken.for_user(user=self.superuser).access_token
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.staff_access_token}")

    def test_crud_with_auth(self):
        # Create a promotion
        valid_data = {
            "name": "Test promotion",
            "start_date": "2023-01-01T00:00:00Z",
            "end_date": "2023-01-31T23:59:59Z",
            "discount_percentage": "10.00",
            "minimum_quantity": "1",
        }
        response = self.client.post("/shop/api/promotions/", valid_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Retrieve the created promotion
        promotion_id = response.data["id"]
        response = self.client.get(f"/shop/api/promotions/{promotion_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Update the promotion
        updated_data = {
            "name": "New promotion",
            "start_date": "2023-01-01T00:00:00Z",
            "end_date": "2023-01-31T23:59:59Z",
            "discount_percentage": "15.00",
            "minimum_quantity": "1",
        }
        response = self.client.put(
            f"/shop/api/promotions/{promotion_id}/", updated_data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Try deleting the promotion with staff user
        response = self.client.delete(f"/shop/api/promotions/{promotion_id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Try deleting the promotion with superuser
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.superuser_access_token}"
        )
        response = self.client.delete(f"/shop/api/promotions/{promotion_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_get_active_promotion(self):
        # Make a GET request to the action URL
        response = self.client.get("/shop/api/promotions/get-active-promotion/")

        # Assert that the response status is 200
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Parse response data
        response_data = response.json()

        # Assert that only active promotions are returned
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data[0]["name"], "Active Promo")

    def test_no_active_promotions(self):
        # Deactivate all promotions
        Promotion.objects.all().update(active=False)

        # Make a GET request to the action URL
        response = self.client.get("/shop/api/promotions/get-active-promotion/")

        # Assert that the response status is 200
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Parse response data
        response_data = response.json()

        # Assert that no promotions are returned
        self.assertEqual(len(response_data), 0)


class TestMiscViews(TestCase):
    def setUp(self):
        self.client = Client()

        # Creating a regular user
        self.user = User.objects.create_user(
            username="regular_user",
            email="regular@example.com",
            password="testpassword",
        )

        # Creating a userprofile for regular user
        self.user_profile = UserProfile.objects.create(
            user=self.user, marketing_preference=True
        )

        # Creating a staff user
        self.staff_user = User.objects.create_user(
            username="staff_user",
            email="staff@example.com",
            password="testpassword",
            is_staff=True,
        )

        self.category = Category.objects.create(name="Test Category")
        self.location_in_store = LocationInStore.objects.create(name="Aisle 6A")
        self.subcategory = SubCategory.objects.create(
            name="Test Subcategory", associated_category=self.category
        )
        self.supplier = Supplier.objects.create(name="Test Supplier")
        self.product = Product.objects.create(
            name="Test Product",
            price=Decimal(10.00),
            barcode="1234567890",
            category=self.category,
            supplier=self.supplier,
            sub_category=self.subcategory,
            cost_price=12.00,
            profit_margin=20,
            description="Test description here",
            stock_quantity="10",
            ingredients="Test ingredients here",
            allergens="Test allergens here",
            net_contents="100g",
            preparation_and_usage="Test prep here",
            location_in_store=self.location_in_store,
            product_image_url="https://example.com",
            extra_info="Extra info here",
        )

        self.box_product = Product.objects.create(
            name="Box Test Product",
            price=Decimal(120.00),
            barcode="1234567899",
            category=self.category,
            supplier=self.supplier,
            sub_category=self.subcategory,
            cost_price=100.00,
            profit_margin=20,
            description="Box Test description here",
            stock_quantity="10",
            ingredients="Test ingredients here",
            allergens="Test allergens here",
            net_contents="1000g",
            preparation_and_usage="Test prep here",
            location_in_store=self.location_in_store,
            product_image_url="https://example.com",
            extra_info="Extra info here",
        )
        self.delivery_option = DeliveryOption.objects.create(
            name="delivery option 1", max_weight_allowed_in_kg=Decimal("2")
        )
        self.order = Order.objects.create(
            user=self.user, status="Pending", delivery_type=self.delivery_option.name
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
        )

        self.notifications = Notification.objects.create(
            order=self.order, message="test notification"
        )

    def test_dashboard_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "shop/dashboard.html")

    def test_dashboard_view_not_logged_in(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_order_management_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(reverse("order_management"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "shop/order_management.html")

    def test_order_management_view_not_logged_in(self):
        response = self.client.get(reverse("order_management"))
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_product_management_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(reverse("product_management"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "shop/product_management.html")

    def test_product_management_view_not_logged_in(self):
        response = self.client.get(reverse("product_management"))
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_order_details_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(
            reverse("order_details", kwargs={"order_id": self.order.order_id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "shop/order_details.html")

    def test_order_details_view_not_logged_in(self):
        response = self.client.get(
            reverse("order_details", kwargs={"order_id": self.order.order_id})
        )
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_update_product_by_product_id_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(
            reverse(
                "update_product_by_product_id",
                kwargs={"product_id": self.product.product_id},
            )
        )
        # Redirect since it's a POST view
        self.assertEqual(response.status_code, 302)

        self.new_category = Category.objects.create(name="Test Category 2")
        self.new_subcategory = SubCategory.objects.create(
            name="Test Subcategory 2", associated_category=self.new_category
        )
        self.new_supplier = Supplier.objects.create(name="Test Supplier 2")

        # Prepare POST data
        post_data = {
            "is_frozen": "on",
            "is_chilled": "on",
            "price": "1.99",
            "category": self.new_category.id,
            "sub_category": self.new_subcategory.id,
            "supplier": self.new_supplier.id,
        }

        # Get the update product URL
        url = reverse("update_product_by_product_id", args=[self.product.product_id])

        # Make a POST request to update the product
        response = self.client.post(url, post_data, follow=True)

        # Check if the product is updated successfully
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_frozen)
        self.assertTrue(self.product.is_chilled)
        self.assertEqual(self.product.price, Decimal("1.99"))
        self.assertEqual(self.product.category, self.new_category)
        self.assertEqual(self.product.sub_category, self.new_subcategory)
        self.assertEqual(self.product.supplier, self.new_supplier)

    def test_update_product_by_product_id_view_not_logged_in(self):
        response = self.client.get(
            reverse(
                "update_product_by_product_id",
                kwargs={"product_id": self.product.product_id},
            )
        )
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_add_product_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(reverse("add_product"))
        # Redirect since it's a POST view
        self.assertEqual(response.status_code, 302)

    def test_add_product_view_not_logged_in(self):
        response = self.client.get(reverse("add_product"))
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_complete_order_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.post(
            reverse("complete_order", kwargs={"order_id": self.order.order_id})
        )
        # Redirect since it's a POST view
        self.assertEqual(response.status_code, 302)

    def test_complete_order_view_not_logged_in(self):
        response = self.client.post(
            reverse("complete_order", kwargs={"order_id": self.order.order_id})
        )
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_get_notifications_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(reverse("notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "notifications.html")

    def test_get_notifications_view_not_logged_in(self):
        response = self.client.get(reverse("notifications"))
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_notification_details_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(reverse("notification_details", kwargs={"id": 1}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "notification_details.html")

    def test_notification_details_view_not_logged_in(self):
        response = self.client.get(reverse("notification_details", kwargs={"id": 1}))
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    @patch("shop.views.openfoodfacts.API")
    def test_fetch_product_details_view_logged_in_staff(self, mock_api):
        mock_instance = mock_api.return_value
        mock_instance.product.get.return_value = {
            "product_name": "Test Product",
            "allergens": "Test Allergens",
            "ingredients_text_en": "Test Ingredients",
            "nutriscore": "A",
            "nutrition_data_per": "100g",
            "nutrition_data": {
                "energy": "200 kcal",
                "fat": "10g",
                "carbohydrates": "20g",
                "protein": "5g",
            },
        }
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(f"{reverse('fetch_product')}?barcode=12345")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "product_name": "Test Product",
                "allergens": "Test Allergens",
                "ingredients_text_en": "Test Ingredients",
                "nutriscore": "A",
                "nutrition_data_per": "100g",
                "nutrition_data": {
                    "energy": "200 kcal",
                    "fat": "10g",
                    "carbohydrates": "20g",
                    "protein": "5g",
                },
            },
        )

    @patch("shop.views.openfoodfacts.API")
    def test_fetch_product_details_view_not_logged_in(self, mock_api):
        mock_instance = mock_api.return_value
        mock_instance.product.get.return_value = {
            "product_name": "Test Product",
            "allergens": "Test Allergens",
            "ingredients_text_en": "Test Ingredients",
            "nutriscore": "A",
            "nutrition_data_per": "100g",
            "nutrition_data": {
                "energy": "200 kcal",
                "fat": "10g",
                "carbohydrates": "20g",
                "protein": "5g",
            },
        }
        response = self.client.get(f"{reverse('fetch_product')}?barcode=12345")
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_get_sub_categories_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(reverse("get_sub_categories"))
        self.assertEqual(response.status_code, 200)

    def test_get_sub_categories_view_not_logged_in(self):
        response = self.client.get(reverse("get_sub_categories"))
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_add_category_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(reverse("add_category"))
        # Redirect since it's a POST view
        self.assertEqual(response.status_code, 302)

    def test_add_category_view_not_logged_in(self):
        response = self.client.get(reverse("add_category"))
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_add_subcategory_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(reverse("add_subcategory"))
        # Redirect since it's a POST view
        self.assertEqual(response.status_code, 302)

    def test_add_subcategory_view_not_logged_in(self):
        response = self.client.get(reverse("add_subcategory"))
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_fetch_product_by_barcode_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(
            reverse("fetch_product_by_barcode") + "?barcode=1234567890"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Test Product")

    def test_fetch_product_by_barcode_view_not_logged_in(self):
        self.client.logout()
        response = self.client.get(
            reverse("fetch_product_by_barcode") + "?barcode=1234567890"
        )
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_link_product_with_box_product_view_logged_in_staff(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.post(
            reverse("link_product_with_box_product"),
            {"productBarcode": "1234567890", "boxProductBarcode": "1234567899"},
        )
        # Redirect to product management page
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Product.objects.get(barcode=self.product.barcode).box_product,
            self.box_product,
        )

    def test_link_product_with_box_product_view_not_logged_in(self):
        self.client.logout()
        response = self.client.post(
            reverse("link_product_with_box_product"),
            {"productBarcode": "1234567890", "boxProductBarcode": "1234567899"},
        )
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_update_order_status_success(self):
        self.client.login(username="staff_user", password="testpassword")
        post_data = {
            "order_id": self.order.order_id,
            "new_status": "Dispatched",
        }
        response = self.client.post(
            reverse("update_order_status"), post_data, format="json"
        )
        self.order.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.order.status, "Dispatched")
        self.assertEqual(response.json()["status"], "Dispatched")

    def test_update_order_status_same_status(self):
        self.client.login(username="staff_user", password="testpassword")
        post_data = {
            "order_id": self.order.order_id,
            "new_status": "Pending",
        }
        response = self.client.post(
            reverse("update_order_status"), post_data, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Order is already in Pending status", response.content.decode())

    def test_update_order_status_order_does_not_exist(self):
        self.client.login(username="staff_user", password="testpassword")
        order_id = (str(uuid.uuid4()),)  # Non-existent order ID
        post_data = {
            "order_id": order_id,
            "new_status": "Dispatched",
        }
        response = self.client.post(
            reverse("update_order_status"), post_data, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_update_order_status_missing_order_id(self):
        self.client.login(username="staff_user", password="testpassword")
        post_data = {
            "new_status": "Dispatched",
        }
        response = self.client.post(
            reverse("update_order_status"), post_data, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_update_order_status_missing_new_status(self):
        self.client.login(username="staff_user", password="testpassword")
        post_data = {
            "order_id": self.order.order_id,
        }
        response = self.client.post(
            reverse("update_order_status"), post_data, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_update_order_status_not_logged_in(self):
        post_data = {
            "order_id": self.order.order_id,
            "new_status": "Dispatched",
        }
        response = self.client.post(
            reverse("update_order_status"), post_data, format="json"
        )
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    @patch("shop.views.send_email", side_effect=mock_send_email)
    def test_dispatch_order_success(self, mock_send_email):
        self.client.login(username="staff_user", password="testpassword")
        url = reverse("dispatch_order", kwargs={"order_id": self.order.order_id})
        post_data = {"delivery_partner": "royalmail", "tracking_id": "123545"}
        response = self.client.post(url, post_data, format="json")
        self.order.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.order.status, OrderStatus.DISPATCHED.value)
        mock_send_email.assert_called_once()

    def test_dispatch_order_not_logged_in(self):
        url = reverse("dispatch_order", kwargs={"order_id": self.order.order_id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_dispatch_order_order_not_found(self):
        self.client.login(username="staff_user", password="testpassword")
        url = reverse(
            "dispatch_order", kwargs={"order_id": str(uuid.uuid4())}
        )  # Non-existent order ID
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)

    def test_dispatch_order_email_failure(self):
        self.client.login(username="staff_user", password="testpassword")
        url = reverse("dispatch_order", kwargs={"order_id": self.order.order_id})

        with patch("shop.views.send_email") as mock_send_email:
            mock_send_email.return_value = False
            response = self.client.post(url)
            # even if the email sending fails, the response should be 302 and the email sending failure will be dealt with separately
            self.assertEqual(response.status_code, 302)

    def test_add_product_stock_success(self):
        self.client.login(username="staff_user", password="testpassword")
        post_data = {
            "barcode": self.product.barcode,
            "quantity_to_add": 5,
        }
        response = self.client.post(reverse("add_product_stock"), post_data)

        self.product.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product.stock_quantity, 15)
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Product stock updated successfully")

    def test_add_product_stock_not_logged_in(self):
        post_data = {
            "barcode": self.product.barcode,
            "quantity_to_add": 5,
        }
        response = self.client.post(reverse("add_product_stock"), post_data)
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_add_product_stock_product_does_not_exist(self):
        self.client.login(username="staff_user", password="testpassword")
        post_data = {
            "barcode": "nonexistentbarcode",
            "quantity_to_add": 5,
        }
        response = self.client.post(reverse("add_product_stock"), post_data)
        self.assertRedirects(response, reverse("product_management"))
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Product doesnot exist")

    def test_add_product_stock_invalid_method(self):
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(reverse("add_product_stock"))
        self.assertRedirects(response, reverse("product_management"))
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertEqual(
            str(messages[0]), "Error adding stock. Request method not supported"
        )

    def test_fetch_marketing_opted_users(self):
        self.client.login(username="staff_user", password="testpassword")

        response = self.client.get(reverse("fetch_marketing_opted_users"))
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content, {"marketing_opted_users_email": "regular@example.com"}
        )

        # Set marketing preference to false and try again
        self.user_profile.marketing_preference = False
        self.user_profile.save()
        response = self.client.get(reverse("fetch_marketing_opted_users"))
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"marketing_opted_users_email": ""})


class StaffLoginViewTestCase(TestCase):
    def setUp(self):
        # Create a staff member
        self.staff_user = User.objects.create_user(
            username="staff_user", password="testpassword", is_staff=True
        )
        # Create a regular user
        self.regular_user = User.objects.create_user(
            username="regular_user", password="testpassword", is_staff=False
        )

    def test_access_allowed_for_staff_member(self):
        # Simulate login attempt by staff member
        self.client.login(username="staff_user", password="testpassword")
        response = self.client.get(reverse("login"), follow=True)  # Follow redirect
        # Assert that staff member is redirected to the main dashboard
        self.assertEqual(response.status_code, 200)
        # Verify whether the shop/dashboard.html template was the one that got used
        self.assertTemplateUsed(response, "shop/dashboard.html")

    def test_access_denied_for_regular_user(self):
        # Simulate login attempt by regular user
        self.client.login(username="regular_user", password="testpassword")
        response = self.client.get(reverse("login"))
        # Assert that regular user is denied access
        self.assertEqual(response.status_code, 403)


class StripeWebhookTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("stripe-webhook")
        self.endpoint_secret = settings.STRIPE_WEBHOOK_ENDPOINT_SECRET

        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpassword"
        )

        self.product = Product.objects.create(
            name="Test Product",
            price=Decimal(100.00),
            stock_quantity=100,
        )

        self.order = Order.objects.create(
            user=self.user,
            stripe_payment_session_id="cs_test_id",
            delivery_type="Standard",
            delivery_fee=10.00,
            voucher_amount=5.00,
        )

        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            base_total=Decimal(self.product.price * 2),
            discount_amount=self.product.price - self.product.discounted_price,
        )

    def generate_stripe_signature(self, payload):
        # Generate a valid signature for the payload
        # In practice, you might use stripe.Webhook.construct_event to generate the signature
        return "dummy_signature"

    # Mock the send_email function, and upload epos s3 dump
    @patch("stripe.Webhook.construct_event")
    @patch("stripe.checkout.Session.retrieve")
    def test_checkout_session_completed_successful_payment(
        self,
        mock_retrieve_session,
        mock_construct_event,
    ):
        UserProfile.objects.create(user=self.user)
        mock_construct_event.return_value = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_id", "payment_status": "paid"}},
        }

        mock_retrieve_session.return_value = Mock(
            id="cs_test_id", payment_status="paid"
        )

        payload = json.dumps(
            {
                "type": "checkout.session.completed",
                "data": {"object": {"id": "cs_test_id", "payment_status": "paid"}},
            }
        )
        signature = self.generate_stripe_signature(payload)

        response = self.client.post(
            self.url,
            data=payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(
            self.order.stripe_payment_status, OrderPaymentStatus.PAID.value
        )
        self.assertFalse(self.order.is_temporary)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 98)

        # Check if upload epos dump in s3 was called with the correct arguments, currently turned off
        # mock_upload_product_barcode_and_bought_quantity_for_backend_epos.assert_called_once()

    def _post_paid_event(self, mock_retrieve_session, mock_construct_event):
        event = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_id", "payment_status": "paid"}},
        }
        mock_construct_event.return_value = event
        mock_retrieve_session.return_value = Mock(
            id="cs_test_id", payment_status="paid"
        )
        return self.client.post(
            self.url,
            data=json.dumps(event),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="dummy_signature",
        )

    @patch("stripe.Webhook.construct_event")
    @patch("stripe.checkout.Session.retrieve")
    def test_paid_webhook_without_userprofile_still_commits(
        self, mock_retrieve_session, mock_construct_event
    ):
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())
        response = self._post_paid_event(mock_retrieve_session, mock_construct_event)
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(
            self.order.stripe_payment_status, OrderPaymentStatus.PAID.value
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 98)

    @patch("stripe.Webhook.construct_event")
    @patch("stripe.checkout.Session.retrieve")
    def test_duplicate_paid_webhook_is_idempotent(
        self, mock_retrieve_session, mock_construct_event
    ):
        from rewards.models import LoyaltyTransaction

        UserProfile.objects.create(user=self.user)
        first = self._post_paid_event(mock_retrieve_session, mock_construct_event)
        count_after_first = LoyaltyTransaction.objects.count()
        second = self._post_paid_event(mock_retrieve_session, mock_construct_event)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 98)
        self.assertEqual(count_after_first, 1)
        self.assertEqual(LoyaltyTransaction.objects.count(), 1)

    @patch("stripe.Webhook.construct_event")
    @patch("stripe.checkout.Session.retrieve")
    def test_multiple_orders_with_same_payment_session_id(
        self, mock_retrieve_session, mock_construct_event
    ):
        mock_construct_event.return_value = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_id", "payment_status": "paid"}},
        }

        mock_retrieve_session.return_value = Mock(
            id="cs_test_id", payment_status="paid"
        )

        # Creating a second order with the same payment session ID to simulate the conflict
        Order.objects.create(
            user=self.user,
            stripe_payment_session_id="cs_test_id",
            delivery_type="Express",
            delivery_fee=15.00,
            voucher_amount=5.00,
        )

        payload = json.dumps(
            {
                "type": "checkout.session.completed",
                "data": {"object": {"id": "cs_test_id", "payment_status": "paid"}},
            }
        )
        signature = self.generate_stripe_signature(payload)

        response = self.client.post(
            self.url,
            data=payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 500)

    @patch("stripe.Webhook.construct_event")
    @patch("stripe.checkout.Session.retrieve")
    def test_no_order_found_with_payment_session_id(
        self, mock_retrieve_session, mock_construct_event
    ):
        mock_construct_event.return_value = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_id", "payment_status": "paid"}},
        }

        mock_retrieve_session.return_value = Mock(
            id="cs_test_id", payment_status="paid"
        )

        # Delete the order to simulate no order found
        self.order.delete()

        payload = json.dumps(
            {
                "type": "checkout.session.completed",
                "data": {"object": {"id": "cs_test_id", "payment_status": "paid"}},
            }
        )
        signature = self.generate_stripe_signature(payload)

        response = self.client.post(
            self.url,
            data=payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 500)

    @patch(
        "stripe.Webhook.construct_event",
        side_effect=SignatureVerificationError(
            message="Invalid signature", sig_header="dummy_signature"
        ),
    )
    def test_invalid_signature(self, mock_construct_event):
        payload = json.dumps(
            {
                "type": "checkout.session.completed",
                "data": {"object": {"id": "cs_test_id", "payment_status": "paid"}},
            }
        )

        response = self.client.post(
            self.url,
            data=payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="invalid_signature",
        )

        self.assertEqual(response.status_code, 400)

    @patch("stripe.Webhook.construct_event", side_effect=ValueError("Invalid payload"))
    def test_invalid_payload(self, mock_construct_event):
        payload = json.dumps(
            {
                "type": "checkout.session.completed",
                "data": {"object": {"id": "cs_test_id", "payment_status": "paid"}},
            }
        )

        response = self.client.post(
            self.url,
            data=payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="dummy_signature",
        )

        self.assertEqual(response.status_code, 400)


class UploadEposDataDumpTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.api_key = settings.API_KEY
        self.client.defaults["HTTP_AUTHORIZATION"] = self.api_key
        self.upload_url = reverse("upload_epos_data_dump")

    def get_response_content(self, response):
        """Utility method to decode response content"""
        return response.content.decode("utf-8")

    def test_upload_success(self):
        """Test that a valid CSV file upload succeeds"""
        csv_file = SimpleUploadedFile(
            "test.csv", b"some,test,data", content_type="text/csv"
        )
        response = self.client.post(self.upload_url, {"file": csv_file})
        self.assertEqual(response.status_code, 200)
        self.assertIn("File uploaded successfully", self.get_response_content(response))

    def test_no_file_uploaded(self):
        """Test that no file upload returns a bad request"""
        response = self.client.post(self.upload_url)
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Please upload exactly one file", self.get_response_content(response)
        )

    def test_multiple_files_uploaded(self):
        """Test that uploading multiple files returns a bad request"""
        file1 = SimpleUploadedFile(
            "file1.csv", b"some,test,data", content_type="text/csv"
        )
        file2 = SimpleUploadedFile(
            "file2.csv", b"some,test,data", content_type="text/csv"
        )
        response = self.client.post(self.upload_url, {"file": [file1, file2]})
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Please upload exactly one file", self.get_response_content(response)
        )

    def test_file_size_exceeds_limit(self):
        """Test that file size exceeding the limit returns a bad request"""
        large_file = SimpleUploadedFile(
            "large_file.csv",
            b"a" * (settings.MAX_EPOS_FILE_SIZE + 1),
            content_type="text/csv",
        )
        response = self.client.post(self.upload_url, {"file": large_file})
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Uploaded file is too large. Maximum size is 5MB",
            self.get_response_content(response),
        )

    def test_incorrect_file_type(self):
        """Test that a non-CSV file type returns a bad request"""
        text_file = SimpleUploadedFile(
            "file.txt", b"some text data", content_type="text/plain"
        )
        response = self.client.post(self.upload_url, {"file": text_file})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only CSV files are allowed", self.get_response_content(response))

    @patch("shop.views.store_file_in_s3")
    def test_store_file_in_s3_exception(self, mock_store_file_in_s3):
        """Test that an exception in store_file_in_s3 is handled properly"""
        csv_file = SimpleUploadedFile(
            "test.csv", b"some,test,data", content_type="text/csv"
        )
        mock_store_file_in_s3.side_effect = Exception("Storage error")
        response = self.client.post(self.upload_url, {"file": csv_file})
        self.assertEqual(response.status_code, 500)
        self.assertIn(
            "An error occurred: Storage error", self.get_response_content(response)
        )


class DownloadOrderInfoDumpForEposTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.api_key = settings.API_KEY
        self.client.defaults["HTTP_AUTHORIZATION"] = self.api_key
        self.sqs_url = settings.AWS_SQS_URL_FOR_DATA_DUMP_TO_BE_USED_BY_EPOS
        # Initialize mock messages
        self.mock_messages = [
            {
                "MessageId": "1",
                "ReceiptHandle": "handle1",
                "Body": json.dumps(
                    {
                        "data_dump": [{"barcode": "123456789012", "quantity": 10}],
                        "data_type": "order_info_for_epos",
                    }
                ),
            },
            {
                "MessageId": "2",
                "ReceiptHandle": "handle2",
                "Body": json.dumps(
                    {
                        "data_dump": [{"barcode": "987654321098", "quantity": 5}],
                        "data_type": "order_info_for_epos",
                    }
                ),
            },
            {
                "MessageId": "3",
                "ReceiptHandle": "handle3",
                "Body": json.dumps(
                    {
                        "data_dump": [{"random_key": "random_value"}],
                        "data_type": "random_type",
                    }
                ),
            },
        ]

    @patch("shop.views.boto3.client")
    def test_successful_download(self, mock_boto_client):
        """Test that the view returns a CSV file with data from SQS."""
        # Mock SQS client
        mock_sqs_client = MagicMock()
        mock_boto_client.return_value = mock_sqs_client

        # Simulate the behavior of SQS
        def receive_message_side_effect(*args, **kwargs):
            if self.mock_messages:
                return {"Messages": self.mock_messages}
            return {}

        def delete_message_batch_side_effect(*args, **kwargs):
            # Simulate message deletion by clearing the mock_messages list
            self.mock_messages.clear()
            return {"Successful": [], "Failed": []}

        mock_sqs_client.receive_message.side_effect = receive_message_side_effect
        mock_sqs_client.delete_message_batch.side_effect = (
            delete_message_batch_side_effect
        )

        response = self.client.get(reverse("download_order_info_dump_for_epos"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="order_info_dump.csv"',
        )

        csv_content = response.content.decode("utf-8")
        expected_csv = io.StringIO()
        writer = csv.DictWriter(
            expected_csv, fieldnames=["barcode", "quantity"], lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(
            [
                {"barcode": "123456789012", "quantity": 10},
                {"barcode": "987654321098", "quantity": 5},
            ]
        )
        expected_csv.seek(0)
        self.assertEqual(csv_content, expected_csv.getvalue())

    @patch("shop.views.boto3.client")
    def test_empty_sqs_queue(self, mock_boto_client):
        """Test that the view handles an empty SQS queue correctly."""
        # Mock SQS client
        mock_sqs_client = MagicMock()
        mock_boto_client.return_value = mock_sqs_client

        # Mock receive_message response with no messages
        mock_sqs_client.receive_message.return_value = {}

        # Configure delete_message_batch to not affect the outcome
        mock_sqs_client.delete_message_batch.return_value = {
            "Successful": [],
            "Failed": [],
        }

        # Call the view function
        response = self.client.get(reverse("download_order_info_dump_for_epos"))

        # Check that the response is correct
        self.assertEqual(response.status_code, 204)

    @patch("shop.views.boto3.client")
    def test_sqs_error(self, mock_boto_client):
        """Test that the view handles SQS errors correctly."""
        # Mock SQS client
        mock_sqs_client = MagicMock()
        mock_boto_client.return_value = mock_sqs_client

        # Mock receive_message to raise an exception
        mock_sqs_client.receive_message.side_effect = Exception("SQS error")

        # Configure delete_message_batch to not affect the outcome
        mock_sqs_client.delete_message_batch.return_value = {
            "Successful": [],
            "Failed": [],
        }

        # Call the view function
        response = self.client.get(reverse("download_order_info_dump_for_epos"))

        # Check that the response is correct
        self.assertEqual(response.status_code, 500)
        self.assertIn("An error occurred: SQS error", response.content.decode("utf-8"))


class SyncDataWithEposTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("sync_data_with_epos")

        self.staff_user = User.objects.create_user(
            username="staff",
            password="pass",
            is_staff=True,
            is_superuser=False,
        )

        self.superuser = User.objects.create_user(
            username="admin",
            password="pass",
            is_staff=True,
            is_superuser=True,
        )

    def test_non_superuser_returns_403(self):
        self.client.login(username="staff", password="pass")
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 403)

    def test_missing_file_returns_400_json(self):
        self.client.login(username="admin", password="pass")

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Upload exactly one CSV file", response.content.decode())

    def test_non_csv_file_rejected(self):
        self.client.login(username="admin", password="pass")

        file = SimpleUploadedFile(
            "file.txt",
            b"invalid",
            content_type="text/plain",
        )

        response = self.client.post(self.url, {"epos_sync_file": file})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only CSV files allowed", response.content.decode())

    @patch("django.conf.settings.MAX_EPOS_FILE_SIZE", 5)
    def test_file_too_large_returns_400(self):
        self.client.login(username="admin", password="pass")

        big_file = SimpleUploadedFile(
            "big.csv",
            b"x" * 10,
            content_type="text/csv",
        )

        response = self.client.post(self.url, {"epos_sync_file": big_file})
        self.assertEqual(response.status_code, 400)
        self.assertIn("File too large", response.content.decode())

    @patch("django.conf.settings.WEBSITE_PROFIT_PERCENTAGE", 20)
    def test_preview_returns_price_changes(self):
        self.client.login(username="admin", password="pass")

        Product.objects.create(
            barcode="12345",
            name="Test Product",
            price=Decimal("1.00"),
        )

        df = pd.DataFrame({
            "PLU": ["12345"],
            "RetailPrice": [1.00],
        })

        csv_file = SimpleUploadedFile(
            "preview.csv",
            df.to_csv(index=False).encode(),
            content_type="text/csv",
        )

        response = self.client.post(
            f"{self.url}?preview=1",
            {"epos_sync_file": csv_file},
        )

        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertIn("data", payload)
        self.assertEqual(len(payload["data"]), 1)

        row = payload["data"][0]
        self.assertEqual(row["barcode"], "12345")
        self.assertEqual(Decimal(str(row["new_price"])), Decimal("1.29"))

    @patch("django.conf.settings.WEBSITE_PROFIT_PERCENTAGE", 20)
    def test_preview_no_changes_returns_empty_list(self):
        self.client.login(username="admin", password="pass")

        Product.objects.create(
            barcode="111",
            name="No Change",
            price=Decimal("1.29"),
        )

        df = pd.DataFrame({
            "PLU": ["111"],
            "RetailPrice": [1.00],
        })

        csv_file = SimpleUploadedFile(
            "preview.csv",
            df.to_csv(index=False).encode(),
            content_type="text/csv",
        )

        response = self.client.post(
            f"{self.url}?preview=1",
            {"epos_sync_file": csv_file},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], [])

    @patch("django.conf.settings.WEBSITE_PROFIT_PERCENTAGE", 20)
    def test_valid_sync_updates_product_price(self):
        self.client.login(username="admin", password="pass")

        Product.objects.create(
            barcode="12345",
            name="Test Product",
            price=Decimal("1.00"),
        )

        df = pd.DataFrame({
            "PLU": ["12345"],
            "RetailPrice": [1.00],
        })

        csv_file = SimpleUploadedFile(
            "sync.csv",
            df.to_csv(index=False).encode(),
            content_type="text/csv",
        )

        response = self.client.post(
            self.url,
            {"epos_sync_file": csv_file},
        )

        # Final sync redirects (success)
        self.assertEqual(response.status_code, 200)

        product = Product.objects.get(barcode="12345")
        self.assertEqual(product.price, Decimal("1.29"))

    def test_sync_skips_missing_products_safely(self):
        self.client.login(username="admin", password="pass")

        df = pd.DataFrame({
            "PLU": ["99999"],
            "RetailPrice": [2.00],
        })

        csv_file = SimpleUploadedFile(
            "sync.csv",
            df.to_csv(index=False).encode(),
            content_type="text/csv",
        )

        response = self.client.post(self.url, {"epos_sync_file": csv_file})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Product.objects.count(), 0)

    def test_non_post_method_redirects(self):
        self.client.login(username="admin", password="pass")

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)
