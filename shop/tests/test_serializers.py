from django.test import TestCase
from django.core.exceptions import ValidationError
from shop.models import Product, User, Order, Cart, Category, Supplier
from shop.serializers import ProductSerializer, CategorySerializer, SupplierSerializer, LikeSerializer, ReviewSerializer, OrderSerializer, OrderItemSerializer, UserProfileSerializer, CartSerializer, CartItemSerializer, PromotionSerializer, CustomerFacingProductSerializer, ProductDepartmentSerializer


class ProductSerializerTests(TestCase):

    def setUp(self):
        self.category = Category.objects.create(name='Test Category')
        self.supplier = Supplier.objects.create(name='Test Supplier')

    def test_serializer_valid_data(self):
        product_data = {
            'name': 'Test Product',
            'price': '10',
            'cost_price': '5',
            'profit_margin': '100',
            'barcode': '1234567890',
            'description': 'Test description',
            'category': self.category.id,
            'supplier': self.supplier.id,
            'stock_quantity': 5,
        }
        serializer = ProductSerializer(data=product_data)
        self.assertTrue(serializer.is_valid())

    def test_serializer_invalid_data(self):
        data = {
            "name": "Test Product",
            "price": "Invalid Price",  # Price should be a valid decimal
            "barcode": "1234567890",
            'category': self.category.id,
            'supplier': self.supplier.id,
            'stock_quantity': 5
        }
        serializer = ProductSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('price', serializer.errors)

    def test_serializer_create_instance(self):
        """
        validated_data means the data after the valid product serialization,
        it represents the cleaned and validated data that is ready to be used 
        for creating an instance of the model
        """
        validated_data = {
            "name": "Test Product",
            "price": "10.99",
            "barcode": "1234567890",
            'category': self.category,
            'supplier': self.supplier,
            'stock_quantity': 5,
        }
        product_instance = ProductSerializer().create(validated_data)
        self.assertIsInstance(product_instance, Product)


class CustomerFacingProductSerializerTests(TestCase):

    def setUp(self):
        self.category = Category.objects.create(name='Test Category')
        self.supplier = Supplier.objects.create(name='Test Supplier')

    def test_serializer_valid_data(self):
        product_data = {
            'name': 'Test Product',
            'price': '10',
            'cost_price': '5',
            'profit_margin': '100',
            'barcode': '1234567890',
            'description': 'Test description',
            'category': self.category.id,
            'supplier': self.supplier.id,
            'stock_quantity': 5,
        }
        serializer = CustomerFacingProductSerializer(data=product_data)
        self.assertTrue(serializer.is_valid())
        self.assertTrue('cost_price' not in serializer.validated_data)
        self.assertTrue('profit_margin' not in serializer.validated_data)

    def test_serializer_invalid_data(self):
        data = {
            "name": "Test Product",
            "price": "Invalid Price",  # Price should be a valid decimal
            "barcode": "1234567890",
            'category': self.category.id,
            'supplier': self.supplier.id,
            'stock_quantity': 5
        }
        serializer = CustomerFacingProductSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('price', serializer.errors)

    def test_serializer_create_instance(self):
        """
        validated_data means the data after the valid product serialization,
        it represents the cleaned and validated data that is ready to be used 
        for creating an instance of the model
        """
        validated_data = {
            "name": "Test Product",
            "price": "10.99",
            "barcode": "1234567890",
            'category': self.category,
            'supplier': self.supplier,
            'stock_quantity': 5,
        }
        product_instance = CustomerFacingProductSerializer().create(validated_data)
        self.assertIsInstance(product_instance, Product)


class CategorySerializerTest(TestCase):
    def test_category_serializer(self):
        category_data = {'name': 'Test Category',
                         'description': 'Test description'}
        serializer = CategorySerializer(data=category_data)
        self.assertTrue(serializer.is_valid())


class ProductDepartmentSerializerTest(TestCase):
    def test_product_department_serializer(self):
        category_data = {'name': 'Test Product Department',
                         'description': 'Test description'}
        serializer = ProductDepartmentSerializer(data=category_data)
        self.assertTrue(serializer.is_valid())


class SupplierSerializerTest(TestCase):
    def test_supplier_serializer(self):
        supplier_data = {'name': 'Test Supplier', 'contact_person': 'John Doe',
                         'contact_email': 'test@example.com', 'contact_mobile_number': '1234567890'}
        serializer = SupplierSerializer(data=supplier_data)
        self.assertTrue(serializer.is_valid())

    def test_supplier_serializer_invalid_data(self):
        # Test serializer with invalid data
        invalid_data = {'name': 'Invalid Supplier',
                        'contact_person': 'John Doe', 'contact_email': 'invalid_email'}
        serializer = SupplierSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())


class LikeSerializerTest(TestCase):
    def test_like_serializer(self):
        user = User.objects.create(username='testuser')
        product = Product.objects.create(
            name='Test Product', price='10.99', barcode='1234567890')
        like_data = {'user': user.id, 'product': product.id}
        serializer = LikeSerializer(data=like_data)
        self.assertTrue(serializer.is_valid())

    def test_like_serializer_invalid_data(self):
        # Test serializer with invalid data
        # Non-existent user and product
        invalid_data = {'user': 1, 'product': 2}
        serializer = LikeSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())


class ReviewSerializerTest(TestCase):
    def test_review_serializer(self):
        user = User.objects.create(username='testuser')
        product = Product.objects.create(
            name='Test Product', price='10.99', barcode='1234567890')
        review_data = {'user': user.id,
                       'product': product.id, 'text': 'Test review text'}
        serializer = ReviewSerializer(data=review_data)
        self.assertTrue(serializer.is_valid())

    def test_review_serializer_invalid_data(self):
        # Test serializer with invalid data
        # Non-existent user and product, invalid text
        invalid_data = {'user': 1, 'product': 2, 'text': 123}
        serializer = ReviewSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())


class UserProfileSerializerTest(TestCase):
    def test_user_profile_serializer(self):
        user = User.objects.create(username='testuser')
        profile_data = {'user': user.id, 'street_address': 'Test Address',
                        'mobile_number': '1234567890', 'user_type': 'general customer'}
        serializer = UserProfileSerializer(data=profile_data)
        self.assertTrue(serializer.is_valid())

    def test_user_profile_serializer_invalid_data(self):
        # Test serializer with invalid data
        invalid_data = {'user': 1, 'street_address': 'Test Address',
                        'mobile_number': 'invalid_number', 'user_type': 'invalid_type'}
        serializer = UserProfileSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())


class OrderSerializerTest(TestCase):
    def test_order_serializer(self):
        user = User.objects.create(username='testuser')
        order_data = {'user': user.id,
                      'status': 'Pending',
                      'delivery_type': 'Standard',
                      'delivery_fee': '2.99'}
        serializer = OrderSerializer(data=order_data)
        self.assertTrue(serializer.is_valid())

    def test_order_serializer_invalid_data(self):
        # Test serializer with invalid data
        invalid_data = {'user': 1, 'status': 'Invalid Status'}
        serializer = OrderSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())


class OrderItemSerializerTest(TestCase):
    def test_order_item_serializer(self):
        user = User.objects.create(username='testuser')
        product = Product.objects.create(
            name='Test Product', price='10.99', barcode='1234567890')
        order = Order.objects.create(
            user=user, status='Pending')
        order_item_data = {'order': order.id, 'product': product.id,
                           'quantity': 2, 'unit_price': '10.99'}
        serializer = OrderItemSerializer(data=order_item_data)
        self.assertTrue(serializer.is_valid())

    def test_order_item_serializer_invalid_data(self):
        # Test serializer with invalid data
        invalid_data = {'order': 1, 'product': 2, 'quantity': -1}
        serializer = OrderItemSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())


class CartSerializerTest(TestCase):
    def test_cart_serializer(self):
        user = User.objects.create(username='testuser')
        cart_data = {'user': user.id}
        serializer = CartSerializer(data=cart_data)
        self.assertTrue(serializer.is_valid())

    def test_cart_serializer_invalid_data(self):
        # Test serializer with invalid data
        invalid_data = {'user': 1}  # Non-existent user
        serializer = CartSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())


class CartItemSerializerTest(TestCase):
    def test_cart_item_serializer(self):
        user = User.objects.create(username='testuser')
        product = Product.objects.create(
            name='Test Product', price='10.99', barcode='1234567890')
        cart = Cart.objects.create(user=user)
        cart_item_data = {'cart': cart.id,
                          'product': product.id, 'quantity': 2}
        serializer = CartItemSerializer(data=cart_item_data)
        self.assertTrue(serializer.is_valid())

    def test_cart_item_serializer_invalid_data(self):
        # Test serializer with invalid data
        invalid_data = {'cart': 1, 'product': 2, 'quantity': -1}
        serializer = CartItemSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())


class PromotionSerializerTest(TestCase):
    def test_valid_data_serialization(self):
        valid_data = {
            'name': 'Test promotion',
            'start_date': '2023-01-01T00:00:00Z',
            'end_date': '2023-01-31T23:59:59Z',
            'discount_percentage': '10.00',
            'minimum_quantity': '1'
        }
        serializer = PromotionSerializer(data=valid_data)
        self.assertTrue(serializer.is_valid())

    def test_invalid_data_serialization(self):
        invalid_data = {
            'name': 'Test promotion',
            'start_date': '2023-01-01T00:00:00Z',
            'end_date': '2022-12-31T23:59:59Z',  # End date before start date
            'discount_percentage': 'abc',  # Invalid discount value
            'minimum_quantity': '1'
        }
        serializer = PromotionSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())
