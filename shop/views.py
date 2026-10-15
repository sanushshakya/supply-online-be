from __future__ import annotations
import io
from decimal import Decimal, ROUND_UP, InvalidOperation
from django.db.models import Q
import json
import uuid

from django.views.decorators.http import require_http_methods
import boto3
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
import csv
import pandas as pd
from shop.decorators import api_key_required
from shop.exceptions import InvalidTokenError, ExpiredSignatureError
from .utils import (
    store_image_in_s3,
    generate_csv,
    generate_excel,
    store_file_in_s3,
    round_up_to_star_9,
)
import jwt
import datetime
from django.views.decorators.csrf import csrf_exempt
import stripe
from django.middleware.csrf import get_token
from django.conf import settings
from .utils import send_email
from .exceptions import InsufficientStockError
from .integration.models import emit
from .stock import (
    assert_cart_stock,
    commit_paid_order_stock,
    lock_products,
    shortfall,
)
from .utils import generate_pdf
from .forms import OrderStatusFilterForm
from django.urls import reverse
from django.contrib.auth.forms import AuthenticationForm
from django.http import HttpResponseForbidden
from django.http import JsonResponse, HttpResponseServerError
from django.db.models import Prefetch
from django.db.models import Q
import openfoodfacts
import logging
from decimal import Decimal

from django.db import transaction
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from .models import OrderStatus
from django.contrib.auth.views import LogoutView
from django.shortcuts import HttpResponseRedirect
from django.contrib.auth.views import LoginView
from .forms import CustomAuthenticationForm
from datetime import timedelta
from django.contrib import messages
from textwrap import dedent

from django.http import Http404
from django.utils import timezone
from django.shortcuts import redirect
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, logout
from django.contrib.auth.models import update_last_login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils.html import format_html
from django.core.exceptions import PermissionDenied


from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
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
    OrderPaymentStatus,
    Banner,
    MiniAd,
    ProductDepartment,
    DeliveryOption,
    TaxCategory,
    LocationInStore,
    Voucher,
    UserQRAuth,
    PushSubscription,
)
from .serializers import (
    ProductSerializer,
    CategorySerializer,
    SupplierSerializer,
    UserProfileSerializer,
    OrderSerializer,
    OrderItemSerializer,
    CartItemSerializer,
    CartSerializer,
    LikeSerializer,
    ReviewSerializer,
    CustomerFacingUserProfileSerializer,
    PartialUserSerializer,
    CustomerFacingCartSerializer,
    CustomerFacingOrderSerializer,
    CustomerFacingPromotionSerializer,
    SubCategorySerializer,
    UserProfileUpdateSerializer,
    CustomerFacingProductSerializer,
    BannerSerializer,
    MiniAdSerializer,
    ProductDepartmentSerializer,
    DeliveryOptionSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework import permissions
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from shop.exceptions import BadRequestError
from rest_framework.pagination import LimitOffsetPagination

from shop.utils import generate_barcode
from reportlab.platypus import Image
import os
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from django.shortcuts import get_object_or_404
from django.contrib.auth import login
from django.core.signing import Signer, BadSignature

from .utils import send_push_to_user

# Create your views here.
# ModelViewSet provides default CRUD operations

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_API_KEY
client_contact_email = "contactus@m18foods.co.uk"
client_name = "M18 Foods"
client_address = (
    "Unit 6, St James Centre East Rd, Temple Fields, Harlow CM20 2SX, United Kingdom"
)
link_to_client_privacy_policy = f"{settings.DOMAIN_BASE_URL}/policy"
link_to_client_tnc = f"{settings.DOMAIN_BASE_URL}/terms-of-service"
currency = "£"
html_email_footer = f"<a href={link_to_client_privacy_policy}>Privacy Policy</a> | <a href={link_to_client_tnc}>Terms of Service</a>"


# qr login view
# please give me code to add a limit rate to api hits to prevent brute force attacks
@csrf_exempt
def qr_login(request):
    if request.method == "POST":
        try:
            # 1. FIX: Parse JSON body instead of request.POST
            data = json.loads(request.body)
            token = data.get("qr_token")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if not token:
            return JsonResponse({"error": "Token missing"}, status=400)

        signer = Signer()
        try:
            # 2. Unsign and Split
            # This will no longer crash because token is not None
            decoded_val = signer.unsign(token)
            
            # Expecting format "user_id:raw_secret"
            user_id, raw_secret = decoded_val.split(":", 1)
            
        except BadSignature:
            return JsonResponse({"error": "Invalid QR Signature"}, status=403)
        except ValueError:
             return JsonResponse({"error": "Invalid QR Format"}, status=403)

        # 3. Verify User and Secret
        try:
            user = User.objects.get(id=user_id, is_staff=True)
            qr_auth = user.qr_auth
        except (User.DoesNotExist, UserQRAuth.DoesNotExist):
            return JsonResponse({"error": "Unauthorized - No QR Setup"}, status=403)

        if not qr_auth.is_active or not qr_auth.check_secret(raw_secret):
            return JsonResponse({"error": "Invalid QR Secret"}, status=403)

        # 4. Success
        login(request, user)
        return JsonResponse({"success": True})

    return JsonResponse({"error": "Method not allowed"}, status=405)


class ShopJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        # Perform token-based authentication
        return super().authenticate(request)


class IsOwner(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to access it.
    """

    def has_object_permission(self, request, view, obj):
        # Only allow the owner of the object to access it
        return obj.user == request.user


class IsStaffOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow staff to CRUD operations while the general users can only perform read operations
    """

    def has_permission(self, request, view):
        # Allow GET, HEAD, and OPTIONS requests to pass through
        if request.method in permissions.SAFE_METHODS:
            return True

        if request.method == "DELETE":
            # only super_user should be allowed to delete backend model objects such as products, category, departments, etc.
            return request.user and request.user.is_superuser
        else:
            return request.user and request.user.is_staff


class IsUserProfileIdValid(permissions.BasePermission):
    """
    Custom permission to check whether the user profile id sent in the request is valid or not according to the authenticated user

    User A should not be allowed to access the resources associated to User B when accessed according to user_profile_id
    """

    def has_permission(self, request, view):
        if request.method in ["GET", "DELETE"]:
            user_profile_id = request.query_params.get("user_profile_id")
        else:
            user_profile_id = request.data.get("user_profile_id")
        if not user_profile_id:
            raise BadRequestError("User profile id missing in the request body")

        if str(request.user.userprofile.user_profile_id) == user_profile_id:
            return True
        else:
            raise BadRequestError("Invalid user_profile_id")


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsStaffOrReadOnly]


class SubCategoryViewSet(viewsets.ModelViewSet):
    queryset = SubCategory.objects.all()
    serializer_class = SubCategorySerializer
    permission_classes = [IsStaffOrReadOnly]


class ProductDepartmentViewSet(viewsets.ModelViewSet):
    queryset = ProductDepartment.objects.all()
    serializer_class = ProductDepartmentSerializer
    permission_classes = [IsStaffOrReadOnly]


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    authentication_classes = [ShopJWTAuthentication]
    permission_classes = [IsAdminUser, IsStaffOrReadOnly]


class CustomLimitOffsetPagination(LimitOffsetPagination):
    default_limit = 20  # You can adjust the default limit (page size)
    max_limit = (
        100  # You can adjust the max limit (maximum number of items per request)
    )

    def get_paginated_response(self, data):
        """
        This method customizes the pagination response to match the expected output for infinite scroll.
        """
        return Response(
            {
                "count": self.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = CustomerFacingProductSerializer
    permission_classes = [IsStaffOrReadOnly]
    pagination_class = CustomLimitOffsetPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        # Filter by category
        category = params.get("category")
        if category:
            queryset = queryset.filter(category=category)

        # Filter by categories
        categories = params.get("categories")
        if categories:
            categories_int = [int(x) for x in categories.split(",")]
            queryset = queryset.filter(category__in=categories_int)

        # Filter by subcategory
        sub_category = params.get("subcategory")
        if sub_category:
            queryset = queryset.filter(sub_category=sub_category)

        # Filter by subcategories
        subcategories = params.get(
            "subcategories"
        )  # if available it is a comma seperated str
        if subcategories:
            subcategories_int = [int(x) for x in subcategories.split(",")]
            queryset = queryset.filter(sub_category__in=subcategories_int)

        # Filter by department
        department = params.get("department")
        if department:
            queryset = queryset.filter(product_department=department)

        # Filter by departments
        departments = params.get(
            "departments"
        )  # if available it is a comma seperated str
        if departments:
            departments_int = [int(x) for x in departments.split(",")]
            queryset = queryset.filter(product_department__in=departments_int)

        # Filter by availability
        availability_options = params.get(
            "availability"
        )  # if available it is a comma seperated str
        if availability_options:
            availability_options = availability_options.split(",")
            if len(availability_options) == 1:
                if availability_options[0] == "In Stock":
                    queryset = queryset.filter(stock_quantity__gte=1)
                elif availability_options[0] == "Out of Stock":
                    queryset = queryset.filter(stock_quantity__exact=0)

        # Filter by is_available_for_catering
        catering = params.get("catering")
        if catering:
            if catering.lower() == "true":
                queryset = queryset.filter(is_available_for_catering=True)
            elif catering.lower() == "false":
                queryset = queryset.filter(is_available_for_catering=False)

        # Filter by price range
        min_price = params.get("minPrice")
        if min_price:
            queryset = queryset.filter(price__gte=min_price)

        max_price = params.get("maxPrice")
        if max_price:
            queryset = queryset.filter(price__lte=max_price)

        # Sort by
        sortby = params.get("sortby")
        if sortby:
            if sortby == "LTH":
                queryset = queryset.order_by("price")
            elif sortby == "HTL":
                queryset = queryset.order_by("-price")
            elif sortby == "NA":
                queryset = queryset.order_by("-created_at")
            elif sortby == "BS":
                pass
        else:
            queryset = queryset.order_by("id")

        search_query = params.get("q")
        if search_query:
            queryset = queryset.filter(Q(name__icontains=search_query))

        barcode = params.get("barcode")
        if barcode:
            queryset = queryset.filter(Q(barcode__icontains=barcode))

        # Product with offers
        current_time = timezone.now()
        if params.get("offers"):
            queryset = queryset.filter(
                Q(
                    product_promotion__start_date__lte=current_time,
                    product_promotion__end_date__gte=current_time,
                    product_promotion__active=True,
                )
                | Q(
                    category__category_promotion__start_date__lte=current_time,
                    category__category_promotion__end_date__gte=current_time,
                    category__category_promotion__active=True,
                )
                | Q(
                    sub_category__subcategory_promotion__start_date__lte=current_time,
                    sub_category__subcategory_promotion__end_date__gte=current_time,
                    sub_category__subcategory_promotion__active=True,
                )
            )
        queryset = queryset.distinct()
        return queryset

    @action(detail=False, methods=["GET"], url_path="get-product-by-productid")
    def get_product_by_productid(self, request):
        try:
            product_id = request.query_params.get("product_id")
            if product_id:
                product = Product.objects.get(product_id=product_id)
                serializer = CustomerFacingProductSerializer(product)
                return Response(serializer.data, status=status.HTTP_200_OK)

            else:
                logger.error("Exception occured: Missing product_id")
                return Response(
                    {"error": "Missing product_id param"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"Exception: Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="get-product-by-category")
    def get_product_by_category(self, request):
        try:
            category_name = request.query_params.get("category_name")
            if category_name:
                if not Category.objects.filter(name__iexact=category_name).exists():
                    return Response(
                        {"error": "Category doesn't exist"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Filter products by category name
                products = Product.objects.filter(category__name__iexact=category_name)
                serializer = CustomerFacingProductSerializer(products, many=True)
                return Response(serializer.data, status=status.HTTP_200_OK)

            else:
                logger.error("Exception occured: Missing category_name param")
                return Response(
                    {"error": "Missing category_name param"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"Exception: Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="get-best-seller-products")
    def get_best_seller_products(self, request):
        """Get the list of top 10 best selling products"""

        total_products_to_return = 20
        try:
            # Group by 'product', annotate with instance count, and order by count descending
            # product_ids = (
            #     OrderItem.objects.values("product")  # Select the 'product' field
            #     .annotate(
            #         product_count=Count("product")
            #     )  # Count occurrences of each product
            #     .order_by("-product_count")  # Order by count in descending order
            #     .values_list("product", flat=True)  # Extract only the product IDs
            # )
            # best_selling_products = Product.objects.filter(id__in=product_ids)

            best_selling_products = Product.objects.none()
            product_ids = []

            # Fallback: If fewer than total_products_to_return products are found, add trending products
            if best_selling_products.count() < total_products_to_return:
                remaining_slots = (
                    total_products_to_return - best_selling_products.count()
                )
                trending_products = Product.objects.filter(is_trending=True).exclude(
                    id__in=product_ids
                )[:remaining_slots]
                best_selling_products = (
                    best_selling_products | trending_products
                )  # Merge QuerySets

            # Fallback: If still <total_products_to_return, add random products (efficient alternative)
            if best_selling_products.count() < total_products_to_return:
                remaining_slots = (
                    total_products_to_return - best_selling_products.count()
                )
                random_products = Product.objects.exclude(
                    id__in=best_selling_products.values_list("id", flat=True)
                ).order_by("?")[:remaining_slots]
                best_selling_products = best_selling_products | random_products

            serializer = CustomerFacingProductSerializer(
                best_selling_products, many=True
            )
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"detail": f"Exception: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="get-newly-arrived-products")
    def get_newly_arrived_products(self, request):
        """Get the list of products added in the last 30 days"""

        total_products_to_return = 20
        try:
            one_month_ago = timezone.now() - timedelta(days=30)
            new_products = Product.objects.filter(created_at__gte=one_month_ago)
            if len(new_products) < total_products_to_return:
                new_products = Product.objects.order_by("-created_at")[
                    :total_products_to_return
                ]
            else:
                new_products = new_products.order_by("?")[:total_products_to_return]
            serializer = CustomerFacingProductSerializer(new_products, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"detail": f"Exception: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="get-trending-products")
    def get_trending_products(self, request):
        """Get the list of top 10 (trending) products"""

        try:
            # Fetch trending products first
            trending_products = Product.objects.filter(is_trending=True).order_by(
                "-created_at"
            )[:10]

            # Fallback: If fewer than 10 trending products, add random products
            if trending_products.count() < 10:
                remaining_slots = 10 - trending_products.count()
                random_products = Product.objects.exclude(
                    id__in=trending_products.values_list("id", flat=True)
                ).order_by("?")[:remaining_slots]
                trending_products = trending_products | random_products

            # Serialize and return response
            serializer = CustomerFacingProductSerializer(trending_products, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"detail": f"Exception: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="get-product-by-department")
    def get_product_by_department(self, request):
        try:
            product_department_name = request.query_params.get(
                "product_department_name"
            )
            if product_department_name:
                if not ProductDepartment.objects.filter(
                    name__iexact=product_department_name
                ).exists():
                    return Response(
                        {"error": "Product Department doesn't exist"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Filter products by category name
                products = Product.objects.filter(
                    product_department__name__iexact=product_department_name
                )
                serializer = CustomerFacingProductSerializer(products, many=True)
                return Response(serializer.data, status=status.HTTP_200_OK)

            else:
                logger.error(
                    "Exception occured: product_department_name parameter not found"
                )
                return Response(
                    {"error": "Missing product_department_name param"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"Exception: Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="get-all-product-names-with-id")
    def get_all_product_names_with_id(self, request):
        try:
            all_product_names_with_id = {
                str(item.product_id): item.name for item in Product.objects.all()
            }
            return JsonResponse(all_product_names_with_id)

        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"Exception: Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="get-all-wholesale-products")
    def get_all_wholesale_products(self, request):
        try:
            wholesale_products = Product.objects.filter(
                unit_products__isnull=False
            ).distinct()
            serializer = CustomerFacingProductSerializer(wholesale_products, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"Exception: Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="get-category-to-department-list")
    def get_category_to_department_list(self, request):
        try:
            # Use Prefetch to optimize related queries
            products = Product.objects.values_list(
                "category", "product_department"
            ).distinct()

            # Create the mapping in Python
            category_to_department_list_map = {}
            for category_id, department_id in products:
                if category_id and department_id:
                    if category_id not in category_to_department_list_map:
                        category_to_department_list_map[category_id] = []
                    category_to_department_list_map[category_id].append(department_id)

            return JsonResponse(
                category_to_department_list_map, status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Exception occurred: {e}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="get-department-to-category-list")
    def get_department_to_category_list(self, request):
        try:
            # Use Prefetch to optimize related queries
            products = Product.objects.values_list(
                "category", "product_department"
            ).distinct()

            # Create the mapping in Python
            department_to_category_list_map = {}
            for category_id, department_id in products:
                if department_id and category_id:
                    if department_id not in department_to_category_list_map:
                        department_to_category_list_map[department_id] = []
                    department_to_category_list_map[department_id].append(category_id)

            return JsonResponse(
                department_to_category_list_map, status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Exception occurred: {e}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class UserProfileViewSet(viewsets.ModelViewSet):
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer

    @action(detail=False, methods=["POST"])
    def register(self, request, *args, **kwargs):
        try:
            """
            Since our UserProfile points to a User instance as a one-to-one field, first we need
            to create the User instance and then use it to create the UserProfile instance

            Steps:
            - Serialize the data according to UserSerializer
            - Create the User instance
            - Add the user.id to the request data
            - Serialize the data according to UserProfileSerializer
            - Create the UserProfile instance and save it
            - Update the last login
            - Get the auth token
            - Use CustomerFacingUserProfileSerializer to only serialize required user fields in response
            """

            # serializing the full request_data is unsafe as the bad users might try to gain admin privileges
            # we will only pick the username, email, password
            request_data = request.data.copy()
            user = None
            user_profile = None

            if "is_superuser" in request_data or "is_staff" in request_data:
                # these fields are not allowed in the api call
                return Response(
                    {
                        "detail": "Bad request. You are not allowed to register as a superuser or a staff"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            password = request_data.get("password")
            email = request_data.get("email")
            fullname = request_data.get("fullname")
            # marketing_preference = request_data.get("marketing_preference")
            first_name, last_name = fullname.split(" ")

            # Check if the user already exists
            if User.objects.filter(username=email).exists():
                return Response(
                    {"error": "User with this email already exists"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            with transaction.atomic():
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )
                request_data["user"] = user.id

                user_profile_serializer = UserProfileSerializer(data=request_data)
                if user_profile_serializer.is_valid():
                    # Create a UserProfile instance linked to the user
                    user_profile = UserProfile(**user_profile_serializer.validated_data)
                    user_profile.save()

                    update_last_login(None, user_profile.user)

                    # Generate access and refresh tokens
                    refresh = RefreshToken.for_user(user)

                    # Serialize the user profile
                    user_profile_serializer = CustomerFacingUserProfileSerializer(
                        user.userprofile
                    )
                    user_serializer = PartialUserSerializer(user)

                    # create user profile info to be returned back in the response
                    user_profile_info = {
                        **user_profile_serializer.data,
                        **user_serializer.data,
                    }

                    user_profile_info["access_token"] = str(refresh.access_token)
                    user_profile_info["refresh_token"] = str(refresh)

                    # Send activation email
                    if self.send_activation_email(user, email):
                        return Response(
                            "{'detail': 'Account created and activation email sent'}",
                            status=status.HTTP_201_CREATED,
                        )
                    else:
                        return Response(
                            "{'detail': 'Account created but sending activation email failed'}",
                            status=status.HTTP_201_CREATED,
                        )

                else:
                    logger.error(
                        "Exception occured: Failed user profile serializer validation"
                    )
                    user.delete()
                    if user_profile:
                        user_profile.delete()
                    return Response(
                        {"error": "Bad request"}, status=status.HTTP_400_BAD_REQUEST
                    )

        except Exception as e:
            # may need to delete user instance if it was created
            logger.error(f"Exception occured: {e}")
            if user:
                user.delete()
            if user_profile:
                user_profile.delete()
            return Response(
                {"error": "Exception occured: Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["POST"], url_path="register-driver")
    def register_driver(self, request, *args, **kwargs):
        try:
            """
            Since our UserProfile points to a User instance as a one-to-one field, first we need
            to create the User instance and then use it to create the UserProfile instance

            Steps:
            - Serialize the data according to UserSerializer
            - Create the User instance
            - Add the user.id to the request data
            - Serialize the data according to UserProfileSerializer
            - Create the UserProfile instance and save it
            """

            # serializing the full request_data is unsafe as the bad users might try to gain admin privileges
            # we will only pick the username, email, password

            request_data = request.data.copy()
            user = None
            user_profile = None

            are_all_required_fields_present = all(
                [
                    field in request_data
                    for field in [
                        "email",
                        "nationality",
                        "fullname",
                        "mobile_number",
                        "right_to_work",
                    ]
                ]
            )
            if not are_all_required_fields_present:
                return Response(
                    {"detail": "Bad request. All the required fields are not present"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if "is_superuser" in request_data or "is_staff" in request_data:
                # these fields are not allowed in the api call
                return Response(
                    {
                        "detail": "Bad request. You are not allowed to register as a superuser or a staff"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            email = request_data.get("email")
            fullname = request_data.get("fullname")
            first_name, last_name = fullname.split(" ")

            # Check if the user already exists
            if User.objects.filter(username=email).exists():
                return Response(
                    {"error": "User with this email already exists"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            with transaction.atomic():
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                )
                request_data["user"] = user.id

                request_data["user_type"] = "driver"

                user_profile_serializer = UserProfileSerializer(data=request_data)
                if user_profile_serializer.is_valid():
                    # Create a UserProfile instance linked to the user
                    user_profile = UserProfile(**user_profile_serializer.validated_data)
                    user_profile.save()

                    return Response(
                        "{'detail': 'Driver account created'}",
                        status=status.HTTP_201_CREATED,
                    )

                else:
                    logger.error(
                        "Exception occured: Failed user profile serializer validation"
                    )
                    user.delete()
                    if user_profile:
                        user_profile.delete()
                    return Response(
                        {"error": "Bad request"}, status=status.HTTP_400_BAD_REQUEST
                    )

        except Exception as e:
            # may need to delete user instance if it was created
            logger.error(f"Exception occured: {e}")
            if user:
                user.delete()
            if user_profile:
                user_profile.delete()
            return Response(
                {"error": "Exception occured: Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["POST"])
    def login(self, request, *args, **kwargs):
        try:
            email = request.data.get("email")
            password = request.data.get("password")
            user = authenticate(request, username=email, email=email, password=password)

            if user:
                if not user.userprofile.is_account_activated:
                    return Response(
                        {
                            "error": "Account not activated yet. Please click on the activation link sent to your email"
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                with transaction.atomic():
                    # Log in the user and update last login time
                    update_last_login(None, user)

                    # Generate access and refresh tokens
                    refresh = RefreshToken.for_user(user)

                    # Serialize the desired partial fields user profile and user
                    # This includes only those fields that we want to send back in the response
                    user_profile_serializer = CustomerFacingUserProfileSerializer(
                        user.userprofile
                    )
                    user_serializer = PartialUserSerializer(user)

                    # create user profile info to be returned back in the response
                    user_profile_info = {
                        **user_profile_serializer.data,
                        **user_serializer.data,
                    }
                    user_profile_info["access_token"] = str(refresh.access_token)
                    user_profile_info["refresh_token"] = str(refresh)

                    # include the user_profile information in the response
                    return Response(user_profile_info, status=status.HTTP_200_OK)

            else:
                # may be we can return the HTTP_401_UNAUTHORIZED from here directly
                return Response(
                    {"error": "Invalid credentials"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
        except Exception as e:
            return Response(
                {"error": f"Exception occured: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["POST"], url_path="refresh-token")
    def refresh_token(self, request, *args, **kwargs):
        try:
            refresh_token = request.data.get("refresh_token")
            # how to validate if the refresh_token is valid or not ??
            if not refresh_token:
                raise Exception("refresh_token param missing")
            token = RefreshToken(refresh_token)
            access_token = str(token.access_token)
            return Response({"access_token": access_token}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Failed to refresh token"}, status=status.HTTP_400_BAD_REQUEST
            )

    @action(
        detail=False,
        methods=["PUT"],
        url_path="update-profile",
        authentication_classes=[ShopJWTAuthentication],
        permission_classes=[IsAuthenticated, IsUserProfileIdValid],
    )
    # Require authentication for updating the profile
    def update_profile(self, request):
        """
        Method to update the user profile with the provided data.
        """
        try:
            request_data = request.data
            if "is_superuser" in request_data or "is_staff" in request_data:
                # these fields are not allowed in the api call
                return Response(
                    {
                        "detail": "Bad request. You are not allowed to register as a superuser or a staff"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # remove email field if present in the request_data because users aren't allowed to update their email address
            if "email" in request_data:
                del request_data["email"]

            with transaction.atomic():
                user_profile_id = request_data.get("user_profile_id")
                associated_userprofile = UserProfile.objects.get(
                    user_profile_id=user_profile_id
                )
                user_profile_update_serializer = UserProfileUpdateSerializer(
                    associated_userprofile, data=request_data, partial=True
                )
                if user_profile_update_serializer.is_valid():
                    user_profile_update_serializer.save()
                    userprofile_serializer = CustomerFacingUserProfileSerializer(
                        associated_userprofile
                    )
                    return Response(
                        userprofile_serializer.data, status=status.HTTP_200_OK
                    )
                else:
                    logger.error(f"Error: {user_profile_update_serializer.errors}")
                    return Response(
                        {"error": "Bad request"}, status=status.HTTP_400_BAD_REQUEST
                    )
        except UserProfile.DoesNotExist:
            logger.error(f"User profile with id {user_profile_id} doesn't exist")
            return Response(
                {"error": "Userprofile doesn't exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Error occured while updating profile: {e}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["POST"], url_path="activate-account")
    def activate_account(self, request):
        try:
            # Extract activation token from request data
            activation_token = request.data.get("token")

            # Decode activation token
            activation_payload = jwt.decode(
                activation_token, settings.SECRET_KEY, algorithms="HS256"
            )

            if "exp" in activation_payload and datetime.datetime.fromtimestamp(
                activation_payload["exp"], datetime.timezone.utc
            ) < datetime.datetime.now(datetime.UTC):
                raise ExpiredSignatureError("Activation link has expired")

            with transaction.atomic():
                # Extract user email and ID from activation payload
                email = activation_payload.get("email")
                user_profile_id = activation_payload.get("user_profile_id")

                # Activate user account based on user ID
                user_profile = UserProfile.objects.get(user_profile_id=user_profile_id)
                user_profile.is_account_activated = True
                user_profile.full_clean()
                user_profile.save()

                # Return success response
                return Response(
                    {"detail": f"Account with email {email} activated successfully"},
                    status=status.HTTP_200_OK,
                )

        except UserProfile.DoesNotExist as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Account doesn't exist"}, status=status.HTTP_400_BAD_REQUEST
            )
        except ExpiredSignatureError as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Activation link has expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InvalidTokenError as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Invalid activation token"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Exception occurred: Internal server occured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["POST"], url_path="resend-activation")
    def resend_activation(self, request):
        try:
            email = request.data.get("email")
            password = request.data.get("password")
            user = authenticate(request, username=email, email=email, password=password)
            if user:
                if self.send_activation_email(user, email):
                    return Response(
                        {"detail": "Activation email sent successfully"},
                        status=status.HTTP_200_OK,
                    )
                else:
                    return Response(
                        {
                            "error": "Error while sending activation email. Please try again."
                        },
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
            else:
                return Response(
                    {"error": "Invalid email or password"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Something went wrong. Please try again later"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["POST"], url_path="request-password-reset-link")
    def request_password_reset_link(self, request):
        try:
            email = request.data.get("email")
            user = User.objects.get(username=email)
            expiration_time = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
                hours=2
            )

            # Generate JWT token for password reset
            payload = {
                "email": email,
                "user_profile_id": str(user.userprofile.user_profile_id),
                "exp": expiration_time,
            }
            password_reset_token = jwt.encode(
                payload, settings.SECRET_KEY, algorithm="HS256"
            )

            # Construct activation link with activation token
            password_reset_link = f"{settings.DOMAIN_BASE_URL}/account/requestpasswordreset/update-password?token={password_reset_token}"

            # Compose activation email
            subject = f"Reset {client_name} Account password"
            text_email_message = dedent(f"""
                    Hi {user.first_name},

                    We received a request to reset your password for your {client_name} account. If you made this request, you can reset your password by clicking the link below:

                    {password_reset_link}

                    If the button above doesn’t work, copy and paste the following link into your browser. For your security, this password reset link will expire in 2 hours.
                    To keep your account secure, remember to choose a strong, unique password that you don't use for any other accounts.

                    If you need any assistance or did not request a password reset, contact us immediately at {client_contact_email}.

                    Regards,
                    {client_name} Team

                    {client_name}, {client_address}
                    """)
            html_email_message = format_html(
                dedent(
                    f"""
                    Hi {user.first_name}, <br><br>

                    We received a request to reset your password for your {client_name} account. If you made this request, you can reset your password by clicking the link below: <br><br>

                    {password_reset_link}<br><br>

                    If the button above doesn’t work, copy and paste the following link into your browser. For your security, this password reset link will expire in 2 hours. <br>
                    To keep your account secure, remember to choose a strong, unique password that you don't use for any other accounts.<br><br>

                    If you need any assistance or did not request a password reset, contact us immediately at {client_contact_email}.<br><br>

                    Regards,<br>
                    {client_name} Team<br><br>

                    {client_name}, {client_address}<br>
                    {html_email_footer}
                    """
                )
            )
            recipient_list = [email]

            if send_email(
                subject, text_email_message, recipient_list, html_email_message
            ):
                return Response(
                    {"detail": "Password reset email sent"}, status=status.HTTP_200_OK
                )
            else:
                raise Exception("Error while sending password reset email")

        except User.DoesNotExist:
            logger.error("User doesn't exist")
            return Response(
                {"error": "User with that email doesn't exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Internal server error while sending password reset email"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["PUT"], url_path="update-password")
    def update_password(self, request):  # should this be a protected view?
        try:
            # Extract password reset token from request data
            password_reset_token = request.data.get("token")
            new_password = request.data.get("new_password")

            # Decode reset token
            payload = jwt.decode(
                password_reset_token, settings.SECRET_KEY, algorithms="HS256"
            )

            if "exp" in payload and datetime.datetime.fromtimestamp(
                payload["exp"], datetime.timezone.utc
            ) < datetime.datetime.now(datetime.UTC):
                raise ExpiredSignatureError("Activation link has expired")

            # Extract user email and ID from activation payload
            email = payload.get("email")
            user_profile_id = payload.get("user_profile_id")

            with transaction.atomic():
                # Update the password
                user_profile = UserProfile.objects.get(user_profile_id=user_profile_id)
                user_profile.user.set_password(new_password)
                user_profile.user.save()

                # Invalidate current refresh token
                # It is very tricky to invalidate the access token as it record is not stored as an Outstanding token object in the db
                for outstanding_token in OutstandingToken.objects.filter(
                    user=user_profile.user
                ).all():
                    if not BlacklistedToken.objects.filter(
                        token=outstanding_token
                    ).exists():
                        # Create a new BlacklistedToken record for this outstanding token
                        BlacklistedToken.objects.create(token=outstanding_token)

                # Return success response
                return Response(
                    {
                        "detail": f"Password for the account with email {email} reset successfully"
                    },
                    status=status.HTTP_201_CREATED,
                )

        except UserProfile.DoesNotExist as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Account doesn't exist"}, status=status.HTTP_400_BAD_REQUEST
            )
        except ExpiredSignatureError as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Reset link has expired"}, status=status.HTTP_400_BAD_REQUEST
            )
        except InvalidTokenError as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Invalid reset token"}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": f"Exception occurred: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["PUT"],
        url_path="update-password-while-logged-in",
        authentication_classes=[ShopJWTAuthentication],
        permission_classes=[IsAuthenticated, IsUserProfileIdValid],
    )
    def update_password_while_logged_in(self, request):
        try:
            old_password = request.data.get("old_password")
            new_password = request.data.get("new_password")
            user_profile_id = request.data.get("user_profile_id")

            with transaction.atomic():
                # Retrieve the UserProfile object
                user_profile = UserProfile.objects.get(user_profile_id=user_profile_id)

                # Check if old password matches
                if user_profile.user.check_password(old_password):
                    # Update the password
                    user_profile.user.set_password(new_password)
                    user_profile.user.save()

                    # Invalidate current refresh token
                    # It is very tricky to invalidate the access token as it record is not stored as an Outstanding token object in the db
                    for outstanding_token in OutstandingToken.objects.filter(
                        user=user_profile.user
                    ).all():
                        if not BlacklistedToken.objects.filter(
                            token=outstanding_token
                        ).exists():
                            # Create a new BlacklistedToken record for this outstanding token
                            BlacklistedToken.objects.create(token=outstanding_token)
                    # Refresh tokens
                    refresh = RefreshToken.for_user(user_profile.user)

                    # update the last login
                    update_last_login(None, user_profile.user)

                    # Return success response with new tokens
                    return Response(
                        {
                            "detail": "Password updated successfully",
                            "access_token": str(refresh.access_token),
                            "refresh_token": str(refresh),
                        },
                        status=status.HTTP_200_OK,
                    )
                else:
                    return Response(
                        {"error": "Your old password doesn't match"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        except UserProfile.DoesNotExist as e:
            logger.error(f"Exception occurred: {e}")
            return Response(
                {"error": "Account doesn't exist"}, status=status.HTTP_400_BAD_REQUEST
            )
        except TokenError as e:
            logger.error(f"Token error occurred: {e}")
            return Response(
                {"error": "Failed to revoke existing tokens"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as e:
            logger.error(f"Exception occurred: {e}")
            return Response(
                {"error": f"Exception occurred: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["GET"],
        url_path="get-product-recommendation-for-user",
        authentication_classes=[ShopJWTAuthentication],
        permission_classes=[IsAuthenticated, IsUserProfileIdValid],
    )
    def get_product_recommendation_for_user(self, request):
        try:
            user_profile_id = request.query_params.get("user_profile_id")

            # Get the associated user
            associated_user = UserProfile.objects.get(
                user_profile_id=user_profile_id
            ).user

            # Get the latest 10 orders for the user
            latest_orders = Order.objects.filter(user=associated_user).order_by(
                "created_at"
            )[:10]

            # Prefetch related order items and products to minimize database queries
            latest_orders = latest_orders.prefetch_related(
                Prefetch(
                    "order_items_from_order",
                    queryset=OrderItem.objects.select_related("product"),
                )
            )

            # Extract previously ordered products and categories from the order items
            previously_ordered_products_id = set()
            previously_ordered_categories = set()
            for order in latest_orders:
                for order_item in order.order_items_from_order.all():
                    previously_ordered_categories.add(order_item.product.category)
                    previously_ordered_products_id.add(order_item.product.product_id)

            # Filter five products that belong to the same categories but not in previously ordered products
            recommended_products = Product.objects.filter(
                category__in=previously_ordered_categories
            ).exclude(product_id__in=previously_ordered_products_id)[:5]

            if recommended_products:
                # Serialize the products
                product_serializer = CustomerFacingProductSerializer(
                    recommended_products, many=True
                )

                if product_serializer.data:
                    return Response(product_serializer.data, status=status.HTTP_200_OK)
                else:
                    logger.error("Error: Product serializer error")
                    return Response(
                        {"error": "No product data found"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                return Response([], status=status.HTTP_200_OK)
        except UserProfile.DoesNotExist:
            logger.error(f"User profile with id {user_profile_id} doesn't exist")
            return Response(
                {"error": "User profile doesn't exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Error occurred while getting product recommendations: {e}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["POST"])
    def logout(self, request, *args, **kwargs):
        try:
            refresh_token = request.data.get("refresh_token")
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response(
                {"detail": "Successfully logged out"}, status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Failed to logout"}, status=status.HTTP_400_BAD_REQUEST
            )

    @action(
        detail=False,
        methods=["GET"],
        url_path="get-user-profile",
        authentication_classes=[ShopJWTAuthentication],
        permission_classes=[IsAuthenticated, IsUserProfileIdValid],
    )
    def get_user_profile(self, request, *args, **kwargs):
        try:
            user_profile_id = request.query_params.get("user_profile_id")
            user_profile = UserProfile.objects.get(user_profile_id=user_profile_id)
            serializer = CustomerFacingUserProfileSerializer(user_profile)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Failed to fetch user profile"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def send_activation_email(self, user, email):
        expiration_time = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            hours=2
        )

        # Generate JWT token for account activation
        activation_payload = {
            "email": email,
            "user_profile_id": str(user.userprofile.user_profile_id),
            "exp": expiration_time,
        }
        activation_token = jwt.encode(
            activation_payload, settings.SECRET_KEY, algorithm="HS256"
        )

        # Construct activation link with activation token
        activation_link = f"{settings.DOMAIN_BASE_URL}/account/activate-account?token={activation_token}"

        # Compose activation email
        subject = f"Activate Your {client_name} Account"
        text_email_message = dedent(f"""
        Hi {user.first_name or ""},

        Welcome to {client_name}! We're excited to have you on board.

        To get started, please activate your account by clicking the link below:

        {activation_link}

        The activation link is valid for 2 hours after which you will have to request a new activation link again.
        If the button above doesn’t work, copy and paste the following link into your browser. Once your account is activated, you’ll be able to:

        - Place your orders and track them
        - Get notified about latest products and offers
        - Get alerts for out of stock products as soon as they become available
        - Manage your product likes and reviews

        If you have any questions or need assistance, feel free to reach out to our support team at {client_contact_email}.

        Thank you for choosing {client_name}. We look forward to providing you with the best world foods experience possible.

        Regards,
        {client_name} Team

        {client_name}, {client_address}
        {html_email_footer}
        """)

        html_email_message = format_html(
            dedent(f"""
        Hi {user.first_name or ""}, <br><br>

        Welcome to {client_name}! We're excited to have you on board. <br><br>

        To get started, please activate your account by clicking the link below: <br><br>

        {activation_link} <br><br>

        The activation link is valid for 2 hours after which you will have to request a new activation link again. <br>
        If the button above doesn’t work, copy and paste the following link into your browser. Once your account is activated, you’ll be able to: <br><br>

        - Place your orders and track them<br>
        - Get notified about latest products and offers<br>
        - Get alerts for out of stock products as soon as they become available<br>
        - Manage your product likes and reviews<br><br>

        If you have any questions or need assistance, feel free to reach out to our support team at {client_contact_email}.<br><br>

        Thank you for choosing {client_name}. We look forward to providing you with the best world foods experience possible. <br><br>

        Regards,<br>
        {client_name} Team <br><br>

        {client_name}, {client_address} <br>
        {html_email_footer}
        """)
        )
        recipient_list = [email]

        if send_email(subject, text_email_message, recipient_list, html_email_message):
            return True
        else:
            return False


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    authentication_classes = [ShopJWTAuthentication]
    permission_classes = [IsAuthenticated, IsOwner]

    @action(
        detail=False,
        methods=["GET"],
        url_path="orders-by-user-profile-id",
        permission_classes=[IsUserProfileIdValid],
    )
    def orders_by_user_profile_id(self, request):
        # Fetch all the non temporary orders associated with the user
        try:
            user_profile_id = request.query_params.get("user_profile_id")
            if not user_profile_id:
                return Response(
                    {"error": "user_profile_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not UserProfile.objects.filter(
                user_profile_id__iexact=user_profile_id
            ).exists():
                return Response(
                    {"error": "User profile doesn't exist"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            orders = Order.objects.filter(
                user__userprofile__user_profile_id=user_profile_id, is_temporary=False
            )
            serializer = CustomerFacingOrderSerializer(orders, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Exception occured: Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["POST"],
        url_path="create-order-from-cart",
        permission_classes=[IsUserProfileIdValid],
    )
    def create_order_from_cart(self, request):
        """Create order using the cart

        Request format:
        {
            "user_profile_id": "",
            "cart_id": ""
        }
        """
        try:
            created_order = None
            request_data = request.data.copy()
            user_profile_id = request_data.get("user_profile_id")
            cart_id = request_data.get("cart_id")
            dispatch_method = request_data.get("dispatch_method")
            stripe_payment_session_id = request.data.get("stripe_payment_session_id")

            # Lookup user based on user_profile_id
            user = UserProfile.objects.get(user_profile_id=user_profile_id).user
            associated_cart = Cart.objects.get(cart_id=cart_id)

            # Check if the cart has cart items
            if (
                not hasattr(associated_cart, "cart_items")
                or not associated_cart.cart_items.exists()
            ):
                return Response(
                    {"error": "The cart has no items associated with it"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            """
            Step1: Use OrderSerializer to create order
            Step2: Loop through product in the order and create OrderItem object for each
            Step3: Create a notification object with the order details
            Step4: Send email to the staff
            """
            with transaction.atomic():
                """Lock the user's orders for update, Using select_for_update() locks the selected rows for the duration of the transaction.
                This prevents other transactions from modifying these rows, thereby avoiding race conditions"""
                user_orders = Order.objects.select_for_update().filter(user=user)

                # Delete any existing temporary orders for the user
                user_orders.filter(is_temporary=True).delete()

                # sanity check the delivery option
                assert (
                    associated_cart.delivery_option.max_weight_allowed_in_kg
                    >= associated_cart.total_weight
                )
                assert associated_cart.delivery_option.minimum_purchase_required <= (
                    associated_cart.sub_total_after_discount
                    - associated_cart.applied_voucher_discount_amount
                )

                order_serializer = OrderSerializer(
                    data={
                        "user": user.id,
                        "dispatch_method": dispatch_method,
                        "delivery_type": associated_cart.delivery_option.name,
                        "delivery_fee": associated_cart.delivery_option.delivery_fee,
                        "stripe_payment_session_id": stripe_payment_session_id,
                        "voucher_code": associated_cart.voucher.code
                        if associated_cart.voucher
                        else None,
                        "voucher_type": associated_cart.voucher.condition_type
                        if associated_cart.voucher
                        else None,
                        "voucher_amount": associated_cart.voucher.calculate_discount(
                            associated_cart.sub_total_after_discount,
                            associated_cart.user,
                        )
                        if associated_cart.voucher
                        else Decimal("0.00"),
                    }
                )
                if order_serializer.is_valid():
                    order_serializer.save()
                    created_order = order_serializer.instance
                    order_items_resp_data = []
                    if associated_cart.cart_items.all():
                        for item_details in associated_cart.cart_items.all():
                            product_id = item_details.product.product_id
                            quantity = item_details.quantity

                            # Get the related product
                            product = Product.objects.get(product_id=product_id)

                            if quantity > product.stock_quantity:
                                raise ValueError(
                                    "requested quantity of the product not available"
                                )

                            # Create the order item object
                            order_item = OrderItem.objects.create(
                                order=created_order,
                                product=product,
                                quantity=quantity,
                                base_total=item_details.base_total,
                                discount_category=(
                                    product.linked_promotion.promotion_type
                                    if product.linked_promotion
                                    else None
                                ),
                                discount_amount=item_details.total_discount_amount,
                                tax_rate=product.tax_rate,
                                tax_category=product.tax_category,
                                product_image_url=product.product_image_url,
                            )

                            # Optionally, you can serialize and return the order item in the response
                            order_item_serializer = OrderItemSerializer(order_item)
                            order_item_data = order_item_serializer.data
                            order_items_resp_data.append(order_item_data)

                        url_to_view_order_details = settings.BACKEND_BASE_URL + reverse(
                            "order_details",
                            kwargs={"order_id": created_order.order_id},
                        )
                        if send_email(
                            subject=f"New Order Received [OrderId: {created_order.order_id}]",
                            text_content=dedent(
                                f"""
                                Hi team,

                                A temporary order has been created for amount {created_order.total_amount} from {created_order.user.username}.
                                If the user successfully makes the checkout payment, then the order will be marked as permanent and the fulfillment
                                process can be started. The order details can be view here {url_to_view_order_details}.

                                Best regards,
                                {client_name} Admin
                                """
                            ),
                            recipient_list=settings.STAFF_EMAIL_ADDRESSES,
                        ):
                            logger.info(
                                f"Sent email successfully for order_id {created_order.order_id}"
                            )
                        try:
                            send_push_to_user(
                                user=user,  # ← user object not user.id
                                title='Order Confirmed! 🎉',
                                body=f'Your M18 Foods order #{created_order.order_id} is being prepared.',
                                url=f'/account/order-history/{created_order.order_id}'
                            )
                            
                        except Exception as push_error:
                            logger.error(f"Push failed for order {created_order.order_id}: {push_error}")

                        return Response(
                            {
                                "order": OrderSerializer(created_order).data,
                                "order_items": order_items_resp_data,
                            },
                            status=status.HTTP_201_CREATED,
                        )
                    else:
                        if created_order:
                            created_order.delete()
                        logger.error(
                            f"Cart doesn't have any cart items {associated_cart.cart_id}"
                        )
                        return Response(
                            {"error": "The cart has no items associated with it"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                else:
                    if created_order:
                        created_order.delete()
                    return Response(
                        {"error": "Error during serialization"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        except UserProfile.DoesNotExist:
            if created_order:
                created_order.delete()
            logger.error(
                "Error occured while creating order. UserProfile doesn't exist"
            )
            return Response(
                {"error": "User profile not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Product.DoesNotExist:
            if created_order:
                created_order.delete()
            logger.error("Error occured while creating order. Product doesn't exist")
            return Response(
                {"error": "One or more products not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            if created_order:
                created_order.delete()
            logger.error(f"Error occured while creating order. Exception: {e}")
            return Response(
                {"error": "An error occurred while processing the request"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def group_order_items_by_tax(self, order_items: OrderItem):
        from collections import defaultdict

        tax_groups = defaultdict(lambda: {"items_subtotal": 0, "tax_subtotal": 0})

        for item in order_items:
            tax_rate = item.tax_rate
            subtotal = item.order_item_total_amount
            tax_amount = item.tax_amount

            tax_groups[tax_rate]["items_subtotal"] += subtotal
            tax_groups[tax_rate]["tax_subtotal"] += tax_amount

        return tax_groups

    @action(
        detail=False,
        methods=["GET"],
        url_path="get-full-order-receipt",
        permission_classes=[IsUserProfileIdValid],
    )
    def get_full_order_receipt(self, request):
        try:
            user_profile_id = request.query_params.get("user_profile_id")
            order_id = request.query_params.get("order_id")
            if not user_profile_id:
                return Response(
                    {"error": "user_profile_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not UserProfile.objects.filter(
                user_profile_id__iexact=user_profile_id
            ).exists():
                return Response(
                    {"error": "User profile doesn't exist"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            order = Order.objects.get(
                user__userprofile__user_profile_id=user_profile_id, order_id=order_id
            )

            # Create the PDF
            response = HttpResponse(content_type="application/pdf")
            response["Content-Disposition"] = f'inline; filename="order_{order_id}.pdf"'

            # Use SimpleDocTemplate to create the PDF
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import (
                SimpleDocTemplate,
                Table,
                TableStyle,
                Paragraph,
                Spacer,
            )

            doc = SimpleDocTemplate(response, pagesize=letter)
            elements = []

            # Styles for the document
            styles = getSampleStyleSheet()
            title_style = styles["Title"]
            title_style.alignment = TA_CENTER
            normal_style = styles["Normal"]

            # Create a centered style
            centered_style = ParagraphStyle(
                name="Centered",
                parent=normal_style,  # Base it on your existing style
                alignment=TA_CENTER,  # Align text to the center
            )

            # Title
            elements.append(Paragraph(f"{client_name}", title_style))

            # Address
            elements.append(Paragraph(f"{client_address}", centered_style))

            # Add a spacer for new line
            elements.append(
                Spacer(1, 60)
            )  # 12 points is approximately equivalent to one line

            # Order details
            elements.append(Paragraph(f"Order Id - {order.order_id}", normal_style))

            elements.append(
                Paragraph(f"Customer: {order.user.get_full_name()}", normal_style)
            )
            elements.append(
                Paragraph(f"Order Date: {order.created_at.date()}", normal_style)
            )

            # Add a spacer for new line
            elements.append(Spacer(1, 24))

            # Order items table
            data = [
                [
                    "Product Name",
                    "Bar Code",
                    "Quantity",
                    "VAT (%)",
                    "Item subtotal",
                ]
            ]
            for item in order.order_items_from_order.all():
                data.append(
                    [
                        item.product.name,
                        item.product.barcode,
                        item.quantity,
                        item.tax_rate,
                        item.order_item_subtotal,
                    ]
                )
            data.append(["", "", "", "Subtotal:", order.sub_total])
            if order.total_discount:
                data.append(["", "", "", "Discount:", order.total_discount])
            if order.voucher_amount:
                data.append(["", "", "", "Voucher:", order.voucher_amount])
            data.append(["", "", "", "Delivery Fee:", order.delivery_fee])
            data.append(["", "", "", "Total:", order.total_amount])

            # Create table with style
            table = Table(data)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                        ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                        ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ]
                )
            )
            elements.append(table)

            # add vertical space
            elements.append(Spacer(1, 36))

            # Tax items table
            data = [["VAT rate", "Item subtotal", "VAT subtotal"]]
            tax_groups = self.group_order_items_by_tax(
                order.order_items_from_order.all()
            )
            for tax_rate, agg in tax_groups.items():
                data.append([tax_rate, agg["items_subtotal"], agg["tax_subtotal"]])

            # Create table with style
            table = Table(data)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                        ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                        ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ]
                )
            )
            elements.append(table)

            # Add 5 new lines
            elements.append(Spacer(1, 36))  # typical height of one line is 12 points

            barcode_directory = "generate_barcodes"
            barcode_filename = f"{str(order.order_id)}_barcode"

            # Check if barcode exists
            barcode_path = os.path.join(barcode_directory, f"{barcode_filename}.png")
            if not os.path.exists(barcode_path):
                barcode_path = generate_barcode(str(order.order_id))

            barcode_image = Image(barcode_path, width=200, height=100)
            elements.append(barcode_image)

            # Add 5 new lines
            elements.append(Spacer(1, 36))  # typical height of one line is 12 points
            # Footer
            elements.append(
                Paragraph(
                    f"This digital receipt is for your records only. Please verify all details upon receipt. Taxes are collected as required by law. This receipt serves as proof of purchase and may be required for refunds, exchanges, or warranty claims. By accepting this receipt, you agree to our terms and policies, available at www.m18foods.co.uk. Thank you for choosing {client_name}.",
                    normal_style,
                )
            )

            # Build the PDF
            doc.build(elements)

            return response

        except Order.DoesNotExist:
            logger.error("Order doesn't exist")
            return Response(
                {"error": "Order doesn't exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except UserProfile.DoesNotExist:
            logger.error("UserProfile doesn't exist")
            return Response(
                {"error": "UserProfile doesn't exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class OrderItemViewSet(viewsets.ModelViewSet):
    queryset = OrderItem.objects.all()
    serializer_class = OrderItemSerializer
    authentication_classes = [ShopJWTAuthentication]
    permission_classes = [IsAuthenticated, IsOwner]


class CartViewSet(viewsets.ModelViewSet):
    queryset = Cart.objects.all()
    serializer_class = CartSerializer
    authentication_classes = [ShopJWTAuthentication]
    permission_classes = [IsAuthenticated, IsOwner]

    @action(
        detail=False,
        methods=["POST"],
        url_path="cart-by-user-profile-id",
        permission_classes=[IsUserProfileIdValid],
    )
    def cart_by_user_profile_id(self, request, pk=None):
        try:
            user_profile_id = request.data.get("user_profile_id")
            user = UserProfile.objects.get(user_profile_id=user_profile_id).user
            if user != request.user:
                return Response("Request Forbidden", status=status.HTTP_403_FORBIDDEN)

            if not user_profile_id:
                return Response(
                    {"error": "user_profile_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            with transaction.atomic():
                cart = Cart.objects.filter(
                    user__userprofile__user_profile_id__iexact=user_profile_id
                )

                # if the cart doesn't exist, create a new object
                if cart.count() == 0:
                    user = UserProfile.objects.get(user_profile_id=user_profile_id).user
                    cart = Cart.objects.create(user=user)
                    logger.info("Created a new cart for the user")

                # there should be only one cart associated with the user
                elif cart.count() > 1:
                    logger.error("Found more than one cart associated with the user")
                    return Response(
                        {"error": "Found more than one cart associated with the user"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
                else:
                    cart = cart.first()

                serializer = CustomerFacingCartSerializer(cart)
                return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"detail": f"Exception occured: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["POST"], url_path="create-payment-checkout-session")
    def create_payment_checkout_session(self, request):
        """Steps
        1. Extract the cart id from the request
        2. Find the associated cart and the cart-items
        3. Create the line items to be passed to stripe checkout session
        4. Create the stripe checkout session with ui_mode=embedded
        5. Return the client session secret
        """

        try:
            user_profile_id = request.data.get("user_profile_id")
            cart_id = request.data.get("cart_id")
            cart = Cart.objects.get(cart_id=cart_id)

            if str(cart.user.userprofile.user_profile_id) != user_profile_id:
                raise Exception(
                    "User profile id doesn't match with profile id associated with the cart"
                )

            cart_items = cart.cart_items.all()
            if not cart_items:
                return Response(
                    {"error": "Cart is empty"}, status=status.HTTP_400_BAD_REQUEST
                )

            # Re-check stock against the database before any payment can start
            assert_cart_stock(cart)

            # Create a cart checkout payment session
            session = stripe.checkout.Session.create(
                ui_mode="embedded",
                payment_method_types=["card"],
                line_items=[
                    {
                        "price_data": {
                            "currency": "GBP",
                            "unit_amount": int((cart.total_amount) * 100),
                            "product_data": {"name": "Total"},
                        },
                        "quantity": 1,
                    }
                ],
                mode="payment",
                redirect_on_completion="never",
                # return_url="http://localhost:5173/payment-success?session_id={CHECKOUT_SESSION_ID}"
            )
            return Response(
                {"clientSecret": session.client_secret, "sessionId": session.id},
                status=status.HTTP_200_OK,
            )

        except InsufficientStockError as e:
            return Response(e.to_response_data(), status=status.HTTP_409_CONFLICT)

        except Cart.DoesNotExist:
            return Response(
                {"error": "Cart doesn't exist"}, status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["GET"], url_path="session-status")
    def session_status(self, request):
        session = stripe.checkout.Session.retrieve(
            request.query_params.get("session_id")
        )

        return Response(
            {
                "status": session.status,
                "customer_email": session.customer_details.email,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["POST"], url_path="add-item-to-cart")
    def add_item_to_cart(self, request):
        try:
            cart_id = request.data.get("cart_id")
            if not cart_id:
                return Response(
                    {"error": "cart_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            with transaction.atomic():
                associated_cart = Cart.objects.get(cart_id=cart_id)
                if associated_cart.user != request.user:
                    logger.error("Exception: Forbidden request")
                    return Response(
                        {"error": "Forbidden request"}, status=status.HTTP_403_FORBIDDEN
                    )

                product_id = request.data.get("product_id")
                if not product_id:
                    return Response(
                        {"error": "product_id parameter is required"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                associated_product = Product.objects.get(
                    product_id=product_id, is_active=True
                )

                quantity = request.data.get("quantity")
                if not quantity:
                    return Response(
                        {"error": "quantity parameter is required"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                quantity = int(quantity)
                if quantity < 1:
                    return Response(
                        {"error": "quantity should be at least 1"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Reject quantities above stock, counting what is already in the cart
                locked_product = lock_products([associated_product.product_id]).get(
                    str(associated_product.product_id), associated_product
                )
                quantity_already_in_cart = (
                    CartItem.objects.filter(
                        cart=associated_cart, product=associated_product
                    )
                    .values_list("quantity", flat=True)
                    .first()
                    or 0
                )
                stock_shortfall = shortfall(
                    locked_product, quantity_already_in_cart + quantity
                )
                if stock_shortfall:
                    raise InsufficientStockError([stock_shortfall])

                # Check if the item already exists in the cart
                cart_item, created = CartItem.objects.get_or_create(
                    cart=associated_cart,
                    product=associated_product,
                    defaults={
                        "quantity": quantity,
                    },
                )

                if not created:
                    # If the product already exists, update the quantity
                    cart_item.quantity += quantity
                    cart_item.full_clean()
                    cart_item.save()

                else:
                    # If the product is new to the cart, just save it
                    cart_item.full_clean()
                    cart_item.save()

                serializer = CustomerFacingCartSerializer(associated_cart)
                return Response(serializer.data, status=status.HTTP_200_OK)

        except Cart.DoesNotExist:
            return Response(
                {"error": "Cart does not exist"}, status=status.HTTP_400_BAD_REQUEST
            )

        except InsufficientStockError as e:
            return Response(e.to_response_data(), status=status.HTTP_409_CONFLICT)

        except Product.DoesNotExist:
            return Response(
                {
                    "error": "Product is no longer available. Please remove it from your cart"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["POST"], url_path="add-multiple-items-to-cart")
    def add_multiple_items_to_cart(self, request):
        try:
            cart_id = request.data.get("cart_id")
            items = request.data.get(
                "items"
            )  # List of { "product_id": ..., "quantity": ... }

            if not cart_id:
                return Response(
                    {"error": "cart_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not items or not isinstance(items, list):
                return Response(
                    {"error": "items parameter must be a list"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            failed_products = []
            success_products = []
            for item in items:
                try:
                    product_id = item.get("product_id")
                    quantity = item.get("quantity")

                    if not product_id or quantity is None:
                        raise Exception("Each item must have product_id and quantity")

                    quantity = int(quantity)
                    if quantity < 1:
                        raise Exception(f"Invalid quantity for product {product_id}")

                    associated_product = Product.objects.get(
                        product_id=product_id, is_active=True
                    )
                    success_products.append((product_id, quantity, associated_product))
                except Exception:
                    failed_products.append(product_id)
                    continue

            with transaction.atomic():
                associated_cart = Cart.objects.get(cart_id=cart_id)

                if associated_cart.user != request.user:
                    return Response(
                        {"error": "Forbidden request"},
                        status=status.HTTP_403_FORBIDDEN,
                    )

                for item in success_products:
                    product_id = item[0]
                    quantity = item[1]
                    associated_product = item[2]
                    locked_product = lock_products([associated_product.product_id]).get(
                        str(associated_product.product_id), associated_product
                    )
                    quantity_already_in_cart = (
                        CartItem.objects.filter(
                            cart=associated_cart, product=associated_product
                        )
                        .values_list("quantity", flat=True)
                        .first()
                        or 0
                    )
                    if shortfall(locked_product, quantity_already_in_cart + quantity):
                        failed_products.append(str(product_id))
                        continue
                    cart_item, created = CartItem.objects.get_or_create(
                        cart=associated_cart,
                        product=associated_product,
                        defaults={"quantity": quantity},
                    )

                    if not created:
                        cart_item.quantity += quantity
                        cart_item.full_clean()
                        cart_item.save()
                    else:
                        cart_item.full_clean()
                        cart_item.save()

                serializer = CustomerFacingCartSerializer(associated_cart)

                response_data = serializer.data
                if failed_products:
                    response_data["warning"] = (
                        f"Some products were not added: {', '.join(failed_products)}"
                    )

                return Response(response_data, status=status.HTTP_200_OK)

        except Cart.DoesNotExist:
            return Response(
                {"error": "Cart does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["POST"], url_path="remove-item-from-cart")
    def remove_item_from_cart(self, request):
        try:
            cart_id = request.data.get("cart_id")
            if not cart_id:
                return Response(
                    {"error": "cart_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            with transaction.atomic():
                associated_cart = Cart.objects.get(cart_id=cart_id)
                if associated_cart.user != request.user:
                    logger.error("Exception: Forbidden request")
                    return Response(
                        {"error": "Forbidden request"}, status=status.HTTP_403_FORBIDDEN
                    )
                product_id = request.data.get("product_id")
                if not product_id:
                    return Response(
                        {"error": "product_id parameter is required"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                # associated_product = Product.objects.get(product_id=product_id)

                quantity_to_remove = request.data.get("quantity")
                if not quantity_to_remove:
                    return Response(
                        {"error": "quantity parameter is required"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                quantity_to_remove = int(quantity_to_remove)

                # Check if the item exists in the cart
                cart_item = (
                    CartItem.objects.filter(
                        cart=associated_cart, product__product_id=product_id
                    )
                    .select_related("product")
                    .first()
                )

                if cart_item:
                    # If the quantity to remove exceeds the quantity in the cart item, return error
                    if quantity_to_remove > cart_item.quantity:
                        return Response(
                            {
                                "error": "Can't remove more than what is available in the cart"
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    elif quantity_to_remove == cart_item.quantity:
                        # If the quantity to remove is equal to the quantity in the cart item, delete the cart item
                        cart_item.delete()

                    else:
                        # If the quantity to remove is less than the quantity in the cart item, update the quantity
                        cart_item.quantity -= quantity_to_remove
                        cart_item.full_clean()
                        cart_item.save()
                else:
                    return Response(
                        {"error": "Product doesn't exist in the cart"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                serializer = CustomerFacingCartSerializer(associated_cart)
                return Response(serializer.data, status=status.HTTP_200_OK)

        except Cart.DoesNotExist:
            return Response(
                {"error": "Cart does not exist"}, status=status.HTTP_400_BAD_REQUEST
            )

        except Product.DoesNotExist:
            return Response(
                {"error": "Product does not exist"}, status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["POST"], url_path="reset-cart")
    def reset_cart(self, request):
        try:
            cart_id = request.data.get("cart_id")
            with transaction.atomic():
                associated_cart = Cart.objects.get(cart_id=cart_id)
                if associated_cart.user != request.user:
                    logger.error("Exception: Forbidden request")
                    return Response(
                        {"error": "Forbidden request"}, status=status.HTTP_403_FORBIDDEN
                    )
                associated_cart_items = CartItem.objects.filter(cart=associated_cart)
                for item in associated_cart_items.all():
                    item.delete()

                # reset the delivery option and voucher associated with the cart
                associated_cart.delivery_option = None
                associated_cart.voucher = None
                associated_cart.full_clean()
                associated_cart.save()

                serializer = CustomerFacingCartSerializer(associated_cart)
                return Response(serializer.data, status=status.HTTP_200_OK)

        except Cart.DoesNotExist:
            return Response(
                {"error": "Cart does not exist"}, status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            return Response({"error": e}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=["PUT"], url_path="update-delivery")
    def update_delivery(self, request):
        try:
            cart_id = request.data.get("cart_id")
            delivery_option_id = request.data.get("delivery_option_id")
            with transaction.atomic():
                associated_cart = Cart.objects.get(cart_id=cart_id)
                if associated_cart.user != request.user:
                    logger.error("Exception: Forbidden request")
                    return Response(
                        {"error": "Forbidden request"}, status=status.HTTP_403_FORBIDDEN
                    )

                associated_cart.delivery_option = DeliveryOption.objects.get(
                    id=delivery_option_id
                )
                associated_cart.save()
                serializer = CustomerFacingCartSerializer(associated_cart)
                return Response(serializer.data, status=status.HTTP_200_OK)

        except Cart.DoesNotExist:
            return Response(
                {"error": "Cart does not exist"}, status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            return Response({"error": e}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=["POST"], url_path="apply-voucher-to-cart")
    def apply_voucher_to_cart(self, request):
        try:
            cart_id = request.data.get("cart_id")
            voucher_code = request.data.get("voucher_code")
            if not cart_id or not voucher_code:
                return Response(
                    {"error": "Both cart_id and voucher code parameter are required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            with transaction.atomic():
                associated_cart = Cart.objects.get(cart_id=cart_id)
                associated_voucher = Voucher.objects.get(code=voucher_code)
                if associated_cart.user != request.user:
                    logger.error("Exception: Forbidden request")
                    return Response(
                        {"error": "Forbidden request"}, status=status.HTTP_403_FORBIDDEN
                    )

                if (
                    associated_cart.voucher
                    and associated_voucher.id == associated_cart.voucher.id
                ):
                    logger.info("Voucher already applied")
                    serializer = CustomerFacingCartSerializer(associated_cart)
                    return Response(
                        {
                            "error": "Voucher has already been applied",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if associated_cart.voucher:
                    logger.error(
                        "Exception: Bad request. An order can have only one voucher applied to it"
                    )
                    return Response(
                        {
                            "error": "Only single voucher is allowed per order",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if not associated_voucher.is_valid(
                    associated_cart.user, associated_cart.sub_total
                ):
                    return Response(
                        {
                            "error": "Voucher is invalid",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                associated_cart.voucher = associated_voucher
                associated_cart.full_clean()
                associated_cart.save()

                serializer = CustomerFacingCartSerializer(associated_cart)
                return Response(
                    serializer.data,
                    status=status.HTTP_200_OK,
                )

        except Cart.DoesNotExist:
            logger.error("Exception: Cart doesn't exist")
            return Response(
                {"error": "Cart does not exist"}, status=status.HTTP_400_BAD_REQUEST
            )
        except Voucher.DoesNotExist:
            logger.error("Exception: Voucher doesn't exist")
            return Response(
                {"error": "Voucher does not exist"}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Exception: {e}")
            return Response(
                {"error": "Internal server error. Please contact us for help"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["POST"], url_path="validate-cart-items")
    def validate_cart_items(self, request):
        try:
            cart_id = request.data.get("cart_id")
            if not cart_id:
                return Response(
                    {"error": "cart_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            cart = Cart.objects.get(cart_id=cart_id)

            if cart.user != request.user:
                return Response(
                    {"error": "Forbidden request"}, status=status.HTTP_403_FORBIDDEN
                )

            cart_items = CartItem.objects.filter(cart=cart).select_related("product")
            inactive_products = [
                {"product_id": item.product.product_id, "name": item.product.name}
                for item in cart_items
                if not item.product.is_active
            ]

            return Response(
                {"inactive_products": inactive_products}, status=status.HTTP_200_OK
            )

        except Cart.DoesNotExist:
            return Response(
                {"error": "Cart does not exist"}, status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            logger.exception("Error validating cart items")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CartItemViewSet(viewsets.ModelViewSet):
    queryset = CartItem.objects.all()
    serializer_class = CartItemSerializer
    authentication_classes = [ShopJWTAuthentication]
    permission_classes = [IsAuthenticated, IsOwner]


class LikeViewSet(viewsets.ModelViewSet):
    queryset = Like.objects.all()
    serializer_class = LikeSerializer
    authentication_classes = [ShopJWTAuthentication]
    permission_classes = [IsAuthenticated, IsOwner]

    @action(
        detail=False,
        methods=["GET"],
        url_path="liked-products-by-user-profile-id",
        permission_classes=[IsUserProfileIdValid],
    )
    def liked_products_by_user_profile_id(self, request, pk=None):
        try:
            user_profile_id = request.query_params.get("user_profile_id")
            if not user_profile_id:
                return Response(
                    {"error": "user_profile_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            user = UserProfile.objects.get(user_profile_id=user_profile_id).user
            likes = Like.objects.filter(user=user)
            serializer = LikeSerializer(likes, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except UserProfile.DoesNotExist:
            return Response(
                {"error": "UserProfile not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            return Response(
                {"detail": f"Exception occured: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["POST"],
        url_path="like-product-by-user-profile-id",
        authentication_classes=[ShopJWTAuthentication],
        permission_classes=[IsUserProfileIdValid, IsAuthenticated],
    )
    def like_product_by_user_profile_id(self, request, pk=None):
        # Add like on a given product by a given user
        try:
            user_profile_id = request.data.get("user_profile_id")
            product_id = request.data.get("product_id")

            if not user_profile_id:
                return Response(
                    {"error": "user_profile_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not product_id:
                return Response(
                    {"error": "product_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user = UserProfile.objects.get(user_profile_id=user_profile_id).user
            product = Product.objects.get(product_id=product_id)

            serializer = LikeSerializer(data={"user": user.id, "product": product.id})
            if serializer.is_valid():
                serializer.save()
                return Response(
                    {"detail": "like created successfully"},
                    status=status.HTTP_201_CREATED,
                )
            else:
                logger.error("Exception occured: Failed like serializer validation")
                return Response(
                    {"error": "Bad request"}, status=status.HTTP_400_BAD_REQUEST
                )

        except UserProfile.DoesNotExist:
            return Response(
                {"error": "UserProfile not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Product.DoesNotExist:
            return Response(
                {"error": "Product not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            logger.error("Exception occured: {e}")
            return Response(
                {"detail": f"Exception occured: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ReviewViewSet(viewsets.ModelViewSet):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer
    authentication_classes = [ShopJWTAuthentication]
    permission_classes = [IsAuthenticated, IsOwner]

    @action(
        detail=False,
        methods=["GET"],
        url_path="reviewed-products-by-user-profile-id",
        permission_classes=[IsUserProfileIdValid],
    )
    def reviewed_products_by_user_profile_id(self, request, pk=None):
        try:
            user_profile_id = request.query_params.get("user_profile_id")
            if not user_profile_id:
                return Response(
                    {"error": "user_profile_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            user = UserProfile.objects.get(user_profile_id=user_profile_id).user
            reviews = Review.objects.filter(user=user)
            serializer = ReviewSerializer(reviews, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except UserProfile.DoesNotExist:
            return Response(
                {"error": "UserProfile not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Product.DoesNotExist:
            return Response(
                {"error": "Product not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response(
                {"detail": f"Exception occured: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["POST"],
        url_path="submit-review-by-user-profile-id",
        authentication_classes=[ShopJWTAuthentication],
        permission_classes=[IsUserProfileIdValid, IsAuthenticated],
    )
    def submit_review_by_user_profile_id(self, request, pk=None):
        # Submit a review on a given product by a given user
        try:
            user_profile_id = request.data.get("user_profile_id")
            product_id = request.data.get("product_id")
            review = request.data.get("review")

            if not user_profile_id:
                return Response(
                    {"error": "user_profile_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not product_id:
                return Response(
                    {"error": "product_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not review:
                return Response(
                    {"error": "review parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user = UserProfile.objects.get(user_profile_id=user_profile_id).user
            product = Product.objects.get(product_id=product_id)

            serializer = ReviewSerializer(
                data={"user": user.id, "product": product.id, "text": review}
            )
            if serializer.is_valid():
                serializer.save()
                return Response(
                    {"detail": "review created successfully"},
                    status=status.HTTP_201_CREATED,
                )
            else:
                logger.error("Exception occured: Failed review serializer validation")
                return Response(
                    {"error": "Bad request"}, status=status.HTTP_400_BAD_REQUEST
                )

        except UserProfile.DoesNotExist:
            return Response(
                {"error": "UserProfile not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Product.DoesNotExist:
            return Response(
                {"error": "Product not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            logger.error("Exception occured: {e}")
            return Response(
                {"detail": f"Exception occured: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PromotionViewSet(viewsets.ModelViewSet):
    queryset = Promotion.objects.all()
    serializer_class = CustomerFacingPromotionSerializer
    permission_classes = [IsStaffOrReadOnly]

    @action(detail=False, methods=["GET"], url_path="get-active-promotion")
    def get_active_promotion(self, request):
        try:
            now = timezone.now()
            active_promotions = Promotion.objects.filter(
                active=True, start_date__lte=now, end_date__gte=now
            )
            serializer = self.get_serializer(active_promotions, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error occured at get active promotion: {e}")
            return Response(
                {"error": "Internal Server Error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class BannerViewSet(viewsets.ModelViewSet):
    queryset = Banner.objects.all()
    serializer_class = BannerSerializer
    permission_classes = [IsStaffOrReadOnly]

    @action(detail=False, methods=["GET"], url_path="get-banners-by-location")
    def get_banners_by_location(self, request):
        try:
            location = request.query_params.get("location")
            banners = Banner.objects.filter(banner_location=location)
            serializer = BannerSerializer(banners, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Banner.DoesNotExist:
            logger.error("Banners don't exist")
            return Response(
                {"error": "Banners don't exist"}, status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            logger.error(f"Error occured at get banner by location: {e}")
            return Response(
                {"error": "Internal Server Error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MiniAdViewSet(viewsets.ModelViewSet):
    queryset = MiniAd.objects.all()
    serializer_class = MiniAdSerializer
    permission_classes = [IsStaffOrReadOnly]

    @action(detail=False, methods=["GET"], url_path="get-miniads-by-location")
    def get_miniads_by_location(self, request):
        try:
            location = request.query_params.get("location")
            miniads = MiniAd.objects.filter(ad_location=location)
            serializer = MiniAdSerializer(miniads, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except MiniAd.DoesNotExist:
            logger.error("Mini Ads don't exist")
            return Response(
                {"error": "Mini Ads don't exist"}, status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            logger.error(f"Error occured at get miniads by location: {e}")
            return Response(
                {"error": "Internal Server Error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DeliveryOptionViewSet(viewsets.ModelViewSet):
    queryset = DeliveryOption.objects.all()
    serializer_class = DeliveryOptionSerializer


def csrf_token_view(request):
    # Get the CSRF token
    csrf_token = get_token(request)
    return JsonResponse({"csrfToken": csrf_token})


@csrf_exempt
def stripe_webhook(request):
    endpoint_secret = settings.STRIPE_WEBHOOK_ENDPOINT_SECRET
    payload = request.body
    sig_header = request.headers["Stripe-Signature"]

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)

        # Handle the event
        if event["type"] == "checkout.session.completed":
            logger.info("Received webhook event for checkout session completed")
            session = event["data"]["object"]
            # Retrieve the Checkout Session from Stripe
            checkout_session = stripe.checkout.Session.retrieve(session["id"])
            # Check if the Checkout Session is successfully paid
            if checkout_session.payment_status == "paid":
                # Proceed with placing the order in your database
                # Your order placement logic goes here
                associated_orders = Order.objects.filter(
                    stripe_payment_session_id=session["id"]
                )

                if associated_orders.count() > 1:
                    raise Exception(
                        "Multiple orders found with same payment session id"
                    )
                elif associated_orders.count() == 0:
                    # No order found with the given payment session ID
                    raise Order.DoesNotExist(
                        "No order found with the given payment session id"
                    )

                else:
                    associated_order = associated_orders.first()
                    already_paid = False
                    with transaction.atomic():
                        # re-fetch under a row lock so duplicate deliveries of this
                        # event cannot both pass the paid check
                        associated_order = Order.objects.select_for_update().get(
                            pk=associated_order.pk
                        )
                        if (
                            associated_order.stripe_payment_status
                            == OrderPaymentStatus.PAID.value
                        ):
                            already_paid = True
                        else:
                            associated_order.stripe_payment_status = (
                                OrderPaymentStatus.PAID.value
                            )
                            associated_order.is_temporary = (
                                False  # the order is no longer temporary
                            )
                            associated_order.full_clean()
                            associated_order.save()
                            logger.info("Payment successful. Order details updated")

                            # loyalty points awarding logic; in a savepoint so a
                            # failure here can never block the paid/stock commit
                            try:
                                with transaction.atomic():
                                    from rewards.signals import order_paid

                                    order_paid.send(
                                        sender=Order,
                                        order_reference=str(associated_order.order_id),
                                        user_profile=associated_order.user.userprofile,
                                        order_amount=associated_order.total_amount,
                                    )
                            except Exception:
                                logger.warning(
                                    "Loyalty award failed for paid order %s",
                                    associated_order.order_id,
                                    exc_info=True,
                                )

                            # reduce the product stock once the user has paid; locks
                            # rows and never raises on a shortfall (logged instead)
                            commit_paid_order_stock(associated_order)

                            # outbox event for Supply Chain IQ; same transaction, and
                            # only on the first (not already-paid) delivery
                            emit(
                                "order.paid",
                                {
                                    "order_id": str(associated_order.order_id),
                                    "items": [
                                        {
                                            "product_id": str(item.product.product_id),
                                            "quantity": item.quantity,
                                            "unit_price": str(item.order_item_unit_price),
                                        }
                                        for item in associated_order.order_items_from_order.select_related(
                                            "product"
                                        )
                                    ],
                                },
                            )

                    if already_paid:
                        logger.info(
                            "Duplicate paid webhook ignored for order %s",
                            associated_order.order_id,
                        )
                        return JsonResponse(
                            {"status": "success"}, status=status.HTTP_200_OK
                        )

                    email_subject = "Order Confirmation"
                    text_email_message = dedent(f"""
                                    Hi {associated_order.user.first_name},

                                    Thank you for your order!

                                    We are excited to let you know that your order has been successfully placed. Here are the details of your order:

                                    Order Summary:

                                    Order Number: {associated_order.order_id}
                                    Order Date: {associated_order.created_at.date()}
                                    Order Amount: {currency}{associated_order.total_amount}

                                    We will send you another email once your order has been dispatched.

                                    If you have any questions, please feel free to contact our customer service team at {client_contact_email}

                                    Thank you for choosing {client_name}. We hope you enjoy your purchase!<br>

                                    Best regards,
                                    {client_name} Team

                                    {client_name}, {client_address}
                                """)
                    html_email_message = format_html(
                        dedent(f"""
                                    Hi {associated_order.user.first_name},<br><br>

                                    Thank you for your order!<br><br>

                                    We are excited to let you know that your order has been successfully placed. Here are the details of your order:<br><br>

                                    <b><u>Order Summary</u>:</b><br>

                                    <b>Order Number:</b> {associated_order.order_id}<br>
                                    <b>Order Date:</b> {associated_order.created_at.date()}<br>
                                    <b>Order Amount:</b> {currency}{associated_order.total_amount}<br><br>

                                    We will send you another email once your order has been dispatched.<br>

                                    If you have any questions, please feel free to contact our customer service team at {client_contact_email}<br>

                                    Thank you for choosing {client_name}. We hope you enjoy your purchase!<br><br>

                                    Best regards,<br>
                                    {client_name} Team<br><br>

                                    {client_name}, {client_address} <br>
                                    {html_email_footer}
                                """)
                    )
                    if send_email(
                        subject=email_subject,
                        text_content=text_email_message,
                        recipient_list=[associated_order.user.email],
                        html_content=html_email_message,
                    ):
                        logger.info("Email sent to the customer successfully")

                    """Create the notification since the order has been paid for"""
                    Notification.objects.create(
                        order=associated_order,
                        message=f"New Order Received [OrderId: {associated_order.order_id}]",
                    )

                    logger.info(
                        f"Created new notification successfully for order_id {associated_order.order_id}"
                    )
                    # upload the csv file in sqs for epos backend to consume
                    # sqs_data_dump_dict = {
                    #     "data_dump": [
                    #         {
                    #             "product_barcode": str(item.product.barcode),
                    #             "product_id": str(item.product.product_id),
                    #             "quantity": item.quantity,
                    #         }
                    #         for item in associated_order.order_items_from_order.all()
                    #     ],
                    #     "data_type": "order_info_for_epos",
                    # }
                    # if push_purchased_order_info_to_sqs_for_epos_backend(
                    #     data_dict=sqs_data_dump_dict,
                    #     queue_url=settings.AWS_SQS_URL_FOR_DATA_DUMP_TO_BE_USED_BY_EPOS,
                    # ):
                    #     logger.info(
                    #         "Data dump successfully pushed for SQS epos backend to consume"
                    #     )
        return JsonResponse({"status": "success"}, status=status.HTTP_200_OK)

    except ValueError as e:
        # Invalid payload
        return JsonResponse({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return JsonResponse({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        return JsonResponse(
            {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


"""All the views below this are for the backend control panel"""


def is_staff_user(user):
    return user.is_authenticated and user.is_staff


def is_super_staff_user(user):
    return user.is_authenticated and user.is_superuser


def get_unread_notifications():
    return Notification.objects.filter(is_read=False).order_by("-created_at")


@login_required
@user_passes_test(is_staff_user)
def fetch_notifications(request):
    notifications = get_unread_notifications()
    data = [
        {
            "id": notification.id,
            "message": notification.message,
            "created_at": notification.created_at.strftime("%Y-%m-%d %H:%M"),
            "url": f"/shop/notification-details/{notification.id}/",
        }
        for notification in notifications
    ]
    return JsonResponse({"notifications": data})


@login_required
@user_passes_test(is_staff_user)
def dashboard(request):
    return render(
        request, "shop/dashboard.html", {"notifications": get_unread_notifications()}
    )


def homepage(request):
    return render(request, "homepage.html")


@login_required
@user_passes_test(is_staff_user)
def order_management(request):
    # Fetch orders from the Order model
    orders = Order.objects.all().order_by("-created_at")

    filter_form = OrderStatusFilterForm(request.GET)
    order_id = request.GET.get("search")
    if filter_form.is_valid():
        status = filter_form.cleaned_data.get("status")
        if status:
            orders = orders.filter(status=status)

    if order_id:
        orders = orders.filter(order_id__icontains=order_id)

    paginator = Paginator(orders, 10)  # Show 10 orders per page
    page_number = request.GET.get("page")
    try:
        orders = paginator.page(page_number)
    except PageNotAnInteger:
        orders = paginator.page(1)
    except EmptyPage:
        orders = paginator.page(paginator.num_pages)

    return render(
        request,
        "shop/order_management.html",
        {
            "orders": orders,
            "notifications": get_unread_notifications(),
            "filter_form": filter_form,
        },
    )


@login_required
@user_passes_test(is_staff_user)
def product_management(request, category_slug=None):
    # Fetch the orders, products, categories and suppliers

    categories = Category.objects.all().order_by("name")
    suppliers = Supplier.objects.all().order_by("name")
    tax_categories = TaxCategory.objects.all()
    product_departments = ProductDepartment.objects.all().order_by("name")
    locations_in_store = LocationInStore.objects.all().order_by("name")

    # Extract the barcode filter parameter from the query string
    barcode = request.GET.get("barcode")
    search_query = request.GET.get(
        "search", ""
    ).strip()  # Search query from the search bar
    filter_type = request.GET.get("filter_type")  # filtery type parameter

    # Fetch all products or apply filters if provided
    products = Product.objects.all().order_by("id")

    if barcode:  # Filter by barcode
        products = products.filter(barcode__icontains=barcode)

    if search_query:  # Filter by search query
        products = products.filter(name__icontains=search_query)

    if category_slug:
        products = products.filter(category__slug__icontains=category_slug)

    # Apply quick filters
    if filter_type:
        if filter_type == "no-image":
            products = products.filter(
                Q(product_image_url__isnull=True) | Q(product_image_url="")
            )
            messages.success(request, "Filtered by no image")
        elif filter_type == "no-department":
            products = products.filter(product_department__isnull=True)
            messages.success(request, "Filtered by no department")
        elif filter_type == "no-brand":
            products = products.filter(Q(brand__isnull=True) | Q(brand=""))
            messages.success(request, "Filtered by no brand")
        elif filter_type == "no-price":
            products = products.filter(Q(price__isnull=True) | Q(price=0.00))
            messages.success(request, "Filtered by no price")
        elif filter_type == "no-netcontents":
            products = products.filter(
                Q(net_contents__isnull=True) | Q(net_contents="")
            )
            messages.success(request, "Filtered by no net contents")
        elif filter_type == "no-stock":
            products = products.filter(
                Q(stock_quantity=0) | Q(stock_quantity__isnull=True)
            )
            messages.success(request, "Filtered by no stock")
        elif filter_type == "no-approval":
            products = products.filter(is_admin_approved=False)
            messages.success(request, "Filtered by no approval")

    paginator = Paginator(products, 10)  # Show 10 products per page

    page_number = request.GET.get("page")
    try:
        products = paginator.page(page_number)
    except PageNotAnInteger:
        products = paginator.page(1)
    except EmptyPage:
        products = paginator.page(paginator.num_pages)

    return render(
        request,
        "shop/product_management.html",
        {
            "user": request.user,
            "products": products,
            "categories": categories,
            "suppliers": suppliers,
            "tax_categories": tax_categories,
            "product_departments": product_departments,
            "locations_in_store": locations_in_store,
            "notifications": get_unread_notifications(),
        },
    )


def enum_to_dict(enum_class):
    return {item.name: item.value for item in enum_class}


@login_required
@user_passes_test(is_staff_user)
def order_details(request, order_id):
    try:
        # Fetch the order based on order_id
        order = Order.objects.get(order_id=order_id)

        # Serialize the order data
        serialized_order = OrderSerializer(order).data

        if order.status == OrderStatus.PENDING.value:
            # template for orders that have not been completed yet
            template_name = "shop/order_details.html"

        else:
            # template for orders that have been completed already
            template_name = "shop/completed_order_details.html"

        return render(
            request,
            template_name,
            {
                "order": serialized_order,
                "notifications": get_unread_notifications,
                "order_status_types": enum_to_dict(OrderStatus),
                "staff_users": [
                    a.username for a in User.objects.filter(is_staff=True).all()
                ],
            },
        )
    except Order.DoesNotExist:
        raise Http404("Order does not exist")


@login_required
@user_passes_test(is_staff_user)
def update_product_by_product_id(request, product_id):
    product = Product.objects.get(product_id=product_id)
    if not product:
        # Handle the case where the product is not found
        messages.error(request, "Product not found.")
        # Redirect to product_management page
        return redirect("product_management")

    # create a mutable copy for request.POST QueryDict
    mutable_post_data = request.POST.copy()

    # unchecked checkboxes don't get submitted with the form data
    # Get the value of the is_frozen checkbox from the POST data
    is_frozen = mutable_post_data.get("is_frozen", False)

    # Convert the checkbox value to a boolean
    is_frozen = is_frozen == "on"

    # Update the product instance with the new value of is_frozen
    mutable_post_data["is_frozen"] = is_frozen

    # Get the value of the is_chilled checkbox from the POST data
    is_chilled = mutable_post_data.get("is_chilled", False)

    # Convert the checkbox value to a boolean
    is_chilled = is_chilled == "on"

    # Update the product instance with the new value of is_frozen
    mutable_post_data["is_chilled"] = is_chilled

    # Get the new uploaded product image
    uploaded_image = request.FILES.get("product_image")
    if uploaded_image:
        # Generate a unique filename using uuid
        ext = os.path.splitext(uploaded_image.name)[1]  # Get the file extension
        unique_filename = (
            f"{uuid.uuid4()}{ext}"  # e.g., 'f47ac10b-58cc-4372-a567-0e02b2c3d479.jpg'
        )
        s3_path = f"product_images/{unique_filename}"

        # Store the image and update the mutable_post_data
        mutable_post_data["product_image_url"] = store_image_in_s3(
            s3_path, uploaded_image
        )

    serializer = ProductSerializer(product, data=mutable_post_data, partial=True)
    if serializer.is_valid():
        serializer.save()
        messages.success(request, "Product updated successfully.")
    else:
        messages.error(
            request, "Error updating product. Error while serializer validation"
        )
        return HttpResponseBadRequest(str(serializer.errors))

    # Redirect to product_management page
    return redirect("product_management")


@login_required
@user_passes_test(is_staff_user)
def add_product(request):
    # if the request is not POST, return the error message
    if request.method == "POST":
        # create a mutable copy for request.POST QueryDict
        mutable_post_data = request.POST.copy()

        # unchecked checkboxes don't get submitted with the form data
        # Get the value of the is_frozen checkbox from the POST data
        is_frozen = mutable_post_data.get("is_frozen", False)

        # Convert the checkbox value to a boolean
        is_frozen = is_frozen == "on"

        # Update the product instance with the new value of is_frozen
        mutable_post_data["is_frozen"] = is_frozen

        # Get the uploaded product image
        # TODO: will have to resize it
        uploaded_image = request.FILES.get("product_image")
        if uploaded_image:
            # Generate a unique filename using uuid
            ext = os.path.splitext(uploaded_image.name)[1]  # Get the file extension
            unique_filename = f"{uuid.uuid4()}{ext}"  # e.g., 'f47ac10b-58cc-4372-a567-0e02b2c3d479.jpg'
            s3_path = f"product_images/{unique_filename}"

            # Store the image and update the mutable_post_data
            mutable_post_data["product_image_url"] = store_image_in_s3(
                s3_path, uploaded_image
            )

        serializer = ProductSerializer(data=mutable_post_data)
        if serializer.is_valid():
            serializer.save()
            # Assuming you have a success message
            messages.success(request, "Product added successfully!")
            return redirect("product_management")
        else:
            # Assuming you have an error message
            messages.error(
                request,
                "Error adding product. Please check the form. Error during serializer validation",
            )
            return HttpResponseBadRequest(str(serializer.errors))
    else:
        # Adjust the path accordingly
        messages.error(request, "Error adding product. Request method not supported")
        return redirect("product_management")


@login_required
@user_passes_test(is_staff_user)
def add_product_stock(request):
    # if the request is not POST, return the error message
    if request.method == "POST":
        try:
            with transaction.atomic():
                product_barcode = request.POST.get("barcode")
                quantity_to_add = request.POST.get("quantity_to_add")

                product = Product.objects.get(barcode=product_barcode)
                new_stock = product.stock_quantity + int(quantity_to_add)
                if new_stock < 0:
                    raise Exception("Stock can't be negative")
                product.stock_quantity = new_stock
                product.save()
                messages.success(request, "Product stock updated successfully")
                return redirect("product_management")

        except Product.DoesNotExist:
            messages.error(request, "Product doesnot exist")
            return redirect("product_management")
        except Exception as e:
            messages.error(request, f"Error: {e}")
            return redirect("product_management")
    else:
        # Adjust the path accordingly
        messages.error(request, "Error adding stock. Request method not supported")
        return redirect("product_management")


@login_required
@user_passes_test(is_staff_user)
def complete_order(request, order_id):
    order = Order.objects.get(order_id=order_id)
    if not order:
        # Handle the case where the order is not found
        messages.error(request, "Order not found.")
        # Redirect to order)_management page
        return redirect("order_management")

    order.status = OrderStatus.READY_FOR_DISPATCH.value

    # need to reduce the stock quantity after the order is complete
    order.full_clean()
    order.save()
    messages.success(request, "Order completed successfully.")

    # Redirect to product_management page
    return redirect("order_management")


@login_required
@user_passes_test(is_staff_user)
def get_notifications(request):
    recent_notifications = Notification.objects.all().order_by("-created_at")
    # Show 10 notifications per page
    paginator = Paginator(recent_notifications, 10)

    page_number = request.GET.get("page")
    try:
        recent_notifications = paginator.page(page_number)
    except PageNotAnInteger:
        recent_notifications = paginator.page(1)
    except EmptyPage:
        recent_notifications = paginator.page(paginator.num_pages)
    return render(
        request, "notifications.html", {"notifications": recent_notifications}
    )


@login_required
@user_passes_test(is_staff_user)
def notification_details(request, id):
    notification = Notification.objects.get(id=id)
    if not notification:
        messages.error(request, "Notification not found")

    notification.is_read = True
    notification.full_clean()
    notification.save()
    messages.success(request, "Notification read")

    return render(request, "notification_details.html", {"notification": notification})


@login_required
@user_passes_test(is_staff_user)
def fetch_product_details(request):
    try:
        api = openfoodfacts.API()
        barcode = request.GET.get("barcode")
        product_data = api.product.get(
            barcode,
            fields=[
                "product_name",
                "allergens",
                "ingredients_text_en",
                "nutriscore",
                "nutrition_data_per",
                "nutrition_data",
            ],
        )
        return JsonResponse(product_data)
    except Exception as e:
        # return HttpErrorResponse here
        logger.error(f"Exception occured while fetching product details: {e}")
        return HttpResponseServerError({"error": "Internal Server Error"})


@login_required
@user_passes_test(is_staff_user)
def get_sub_categories(request):
    try:
        category_id = request.GET.get("category_id")
        sub_categories = SubCategory.objects.filter(
            associated_category=category_id
        ).values("id", "name")
        return JsonResponse(list(sub_categories), safe=False)
    except Exception as e:
        # return HttpErrorResponse here
        logger.error(f"Exception occured while getting sub categories: {e}")


@login_required
@user_passes_test(is_staff_user)
def add_category(request):
    # if the request is not POST, return the error message
    if request.method == "POST":
        mutable_post_data = request.POST.copy()

        # Get the uploaded category image
        # TODO: will have to resize it
        uploaded_image = request.FILES.get("category_image")
        if uploaded_image:
            uploaded_image_name = uploaded_image.name.replace(" ", "_")
            s3_path = f"category_images/{uploaded_image_name}"
            mutable_post_data["image_url"] = store_image_in_s3(s3_path, uploaded_image)

        serializer = CategorySerializer(data=mutable_post_data)
        if serializer.is_valid():
            serializer.save()
            messages.success(request, "Category added successfully!")
            return redirect("product_management")
        else:
            messages.error(
                request,
                "Error adding category. Please check the form. Error during serialization",
            )
            return HttpResponseBadRequest(str(serializer.errors))
    else:
        messages.error(request, "Error adding category. Request method not supported")
        return redirect("product_management")


@login_required
@user_passes_test(is_staff_user)
def add_product_department(request):
    # if the request is not POST, return the error message
    if request.method == "POST":
        serializer = ProductDepartmentSerializer(data=request.POST)
        if serializer.is_valid():
            serializer.save()
            messages.success(request, "Product Department added successfully!")
            return redirect("product_management")
        else:
            messages.error(
                request,
                "Error adding product department. Please check the form. Error during serialization",
            )
            return HttpResponseBadRequest(str(serializer.errors))
    else:
        messages.error(
            request, "Error adding product department. Request method not supported"
        )
        return redirect("product_management")


@login_required
@user_passes_test(is_staff_user)
def add_subcategory(request):
    # if the request is not POST, return the error message
    if request.method == "POST":
        serializer = SubCategorySerializer(data=request.POST)
        if serializer.is_valid():
            serializer.save()
            messages.success(request, "Sub Category added successfully!")
            return redirect("product_management")
        else:
            messages.error(
                request,
                "Error adding sub category. Please check the form. Error during serialization",
            )
            return HttpResponseBadRequest(str(serializer.errors))
    else:
        messages.error(
            request, "Error adding sub category. Request method not supported"
        )
        return redirect("product_management")


@login_required
@user_passes_test(is_staff_user)
def fetch_product_by_barcode(request):
    try:
        barcode = request.GET.get("barcode")
        product = Product.objects.get(barcode=barcode)
        serializer = ProductSerializer(product)
        return JsonResponse(serializer.data)
    except Product.DoesNotExist:
        logger.error(f"Product with {barcode} doesn't exist")
        return HttpResponseBadRequest(f"Product with {barcode} doesn't exist")
    except Exception as e:
        logger.error(f"Exception occurred while fetching product by barcode: {e}")
        return HttpResponseServerError(f"Internal Server error: {e}")


@login_required
@user_passes_test(is_staff_user)
def link_product_with_box_product(request):
    if request.method == "POST":
        try:
            product_barcode = request.POST.get("productBarcode")
            box_product_barcode = request.POST.get("boxProductBarcode")

            product = Product.objects.get(barcode=product_barcode)
            box_product = Product.objects.get(barcode=box_product_barcode)

            serializer = ProductSerializer(
                instance=product, data={"box_product": box_product.id}, partial=True
            )

            if serializer.is_valid():
                serializer.save()
                messages.success(request, "Products linked Successfully!")
                return redirect("product_management")
            else:
                messages.error(
                    request,
                    "Error linking product. Please check the form. Error during serialization",
                )
                return HttpResponseBadRequest(str(serializer.errors))

        except Product.DoesNotExist:
            logger.error("Product doesn't exist")
            return HttpResponseBadRequest("Product doesn't exist")

        except Exception as e:
            logger.error(f"Exception occured: {e}")
            return HttpResponseServerError(f"Exception occurred: {e}")
    else:
        logger.error("Error linking products. Request method not supported")
        messages.error(request, "Error linking products. Request method not supported")
        return redirect("product_management")


class StaffLoginView(LoginView):
    form_class = CustomAuthenticationForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        # If there is a 'next' parameter in the URL, redirect to that.
        next_url = self.request.GET.get("next", "/shop/dashboard/")
        return next_url

    def dispatch(self, request, *args, **kwargs):
        # Check if the user is a staff member
        if request.user.is_authenticated and not request.user.is_staff:
            # If the user is not a staff member, return Forbidden response
            logout(request)
            return HttpResponseForbidden(
                "Access Denied: You are not authorized to login"
            )

        if (
            self.redirect_authenticated_user
            and request.user.is_authenticated
            and request.user.is_staff
        ):
            return HttpResponseRedirect(reverse("dashboard"))

        return super().dispatch(request, *args, **kwargs)

    def form_invalid(self, form):
        messages.error(self.request, "Invalid username or password. Please try again.")
        return super().form_invalid(form)

    def form_valid(self, form: AuthenticationForm) -> HttpResponse:
        messages.success(self.request, "Logged in successfully.")
        return super().form_valid(form)


class StaffLogoutView(LogoutView):
    next_page = "/shop/login/"  # Set the URL to redirect after logout

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        # Additional logic after logout if needed
        return response


@login_required
@user_passes_test(is_staff_user)
def export_products_pdf(request):
    if request.method == "GET":
        return generate_pdf(request)
    else:
        logger.error("Request method not supported")
        messages.error(request, "Error creating pdf. Request method not supported")
        return redirect("product_management")


@login_required
@user_passes_test(is_staff_user)
def export_products_csv(request):
    if request.method == "GET":
        return generate_csv(request)
    else:
        logger.error("Request method not supported")
        messages.error(request, "Error creating csv file. Request method not supported")
        return redirect("product_management")


@login_required
@user_passes_test(is_staff_user)
def export_products_excel(request):
    if request.method == "GET":
        return generate_excel(request)
    else:
        logger.error("Request method not supported")
        messages.error(request, "Error creating excel. Request method not supported")
        return redirect("product_management")


@login_required
@user_passes_test(is_staff_user)
def update_order_status(request):
    # Update the status of the order
    if request.method == "POST":
        try:
            with transaction.atomic():
                order_id = request.POST.get("order_id")
                new_status = request.POST.get("new_status")
                if not order_id:
                    return HttpResponseBadRequest("order_id parameter is missing")
                if not new_status:
                    return HttpResponseBadRequest("new_status parameter is missing")

                order = Order.objects.get(order_id=order_id)
                if new_status != order.status:
                    order.status = new_status
                    order.save()
                    # PWA: Fire Celery task — non-blocking ✅
                    from shop.tasks import notify_order_status_change
                    notify_order_status_change.apply_async(
                        args=[order_id, new_status],
                        countdown=0,
                    )
                    serializer = OrderSerializer(order)
                    return JsonResponse(serializer.data)
                else:
                    logger.error(f"Order is already in {new_status} status")
                    return HttpResponseBadRequest(
                        f"Order is already in {new_status} status"
                    )

        except Order.DoesNotExist:
            logger.error(f"Order with {order_id} doesn't exist")
            return HttpResponseBadRequest(f"Order with {order_id} doesn't exist")
        except Exception as e:
            logger.error(f"Exception occurred while updating order status: {e}")
            return HttpResponseServerError(f"Internal Server error: {e}")

    else:
        logger.error("Error updating the status of the order")
        messages.error(request, "Error updating the status of the order")
        return redirect("order_management")


@login_required
@user_passes_test(is_staff_user)
def dispatch_order(request, order_id):
    try:
        order = Order.objects.get(order_id=order_id)
        delivery_partner = request.POST.get("delivery_partner")
        tracking_id = request.POST.get("tracking_id")
        user = order.user

        if not delivery_partner:
            messages.error(request, "Delivery Partner field missing")
            return redirect("order_management")

        if not tracking_id:
            messages.error(request, "Tracking Id field missing")
            return redirect("tracking_id")

        if not order:
            # Handle the case where the order is not found
            messages.error(request, "Order not found.")
            # Redirect to order)_management page
            return redirect("order_management")

        order.status = OrderStatus.DISPATCHED.value
        order.full_clean()
        order.save()
        logger.info(
            f"Order status of order with order_id {order_id} updated to dispatched"
        )

        # send email to the user
        subject = f"Order {order_id} Dispatched"
        text_email_message = dedent(f""" 
                Hi {user.first_name},

                Your order with id {order_id} has been dispatched via {delivery_partner}. Here is your tracking id: {tracking_id}.
                If your tracking id is still not working within next 36 hours, please contact us at {client_contact_email}.

                Regards,
                {client_name} Team

                {client_name}, {client_address}
                """)
        html_email_message = format_html(
            dedent(
                f""" 
                Hi {user.first_name}, <br><br>

                Your order with id {order_id} has been dispatched via {delivery_partner}. Here is your tracking id: {tracking_id}.
                If your tracking id is still not working within next 36 hours, please contact us at {client_contact_email}.<br><br>

                Regards,<br>
                {client_name} Team<br><br>

                {client_name}, {client_address}<br>
                {html_email_footer}
                """
            )
        )
        recipient_list = [user.email]

        if send_email(subject, text_email_message, recipient_list, html_email_message):
            logger.info("Order dispatched email sent successfully to the customer")
            messages.success(request, "Order dispatched. Email sent to the customer")
        else:
            logger.error("Error while sending order dispatch email")
            messages.success(
                request, "Order dispatched. Email sending to the customer failed"
            )
            
        # PWA: Fire Celery task — non-blocking ✅
        from shop.tasks import notify_order_status_change
        notify_order_status_change.apply_async(
            args=[order_id, OrderStatus.DISPATCHED.value, delivery_partner],
            countdown=0,
        )

        # Redirect to order management page
        return redirect("order_management")

    except Order.DoesNotExist:
        logger.error(f"Order doesn't exist {order_id}")
        return HttpResponseBadRequest("Order doesn't exist")
    except Exception as e:
        logger.error(f"Exception occured while dispatching order {order_id}: {e}")
        return HttpResponseServerError("Internal server error")


@api_key_required
@require_http_methods(["POST"])
def upload_epos_data_dump(request):
    # Check if 'files' key exists and is a list with exactly one file
    files = request.FILES.getlist("file")
    if not files or len(files) != 1:
        return HttpResponseBadRequest("Please upload exactly one file")

    file = files[0]

    # Check if the file size exceeds the maximum allowed size
    if file.size > settings.MAX_EPOS_FILE_SIZE:
        return HttpResponseBadRequest("Uploaded file is too large. Maximum size is 5MB")

    # Validate the file type
    if not file.name.endswith(".csv"):
        return HttpResponseBadRequest("Only CSV files are allowed")

    try:
        # Define the S3 path where the file will be stored
        s3_path = f"epos_file_uploads/{file.name}"

        # Store the file in S3
        store_file_in_s3(s3_path, file)
        return HttpResponse("File uploaded successfully")

    except Exception as e:
        return HttpResponseServerError(f"An error occurred: {e}")


@api_key_required
@require_http_methods(["GET"])
def download_order_info_dump_for_epos(request):
    """Pull the first 10 messages from SQS, combine them into a CSV file, and return it."""
    try:
        sqs_url = settings.AWS_SQS_URL_FOR_DATA_DUMP_TO_BE_USED_BY_EPOS

        # Initialize the SQS client
        sqs_client = boto3.client(
            "sqs",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,  # Adjust as necessary
        )

        # Fetch 10 messages from the SQS queue
        messages = []
        response = sqs_client.receive_message(
            QueueUrl=sqs_url,
            MaxNumberOfMessages=2,  # Max allowed is 10
            WaitTimeSeconds=0,  # Short polling
        )
        sqs_entries_to_be_deleted = []

        if "Messages" in response:
            messages.extend(response["Messages"])

            # Filter messages to delete only those with data_type 'order_info_epos'
            for msg in response["Messages"]:
                message_body = json.loads(msg["Body"])
                if message_body.get("data_type") == "order_info_for_epos":
                    sqs_entries_to_be_deleted.append(
                        {"Id": msg["MessageId"], "ReceiptHandle": msg["ReceiptHandle"]}
                    )

        # Combine messages into a list of dictionaries
        data_dict_list = []
        for msg in messages:
            if json.loads(msg["Body"]).get("data_type") == "order_info_for_epos":
                data_dict_list += json.loads(msg["Body"]).get(
                    "data_dump"
                )  # data_dump is a list of dict [{'barcode':'123fa', 'quantity':2}]

        # Create an in-memory CSV file
        csv_buffer = io.StringIO()
        if data_dict_list:
            # Define fieldnames based on the keys of the first dictionary
            fieldnames = list(data_dict_list[0].keys())
            # Ensure consistent line endings
            writer = csv.DictWriter(
                csv_buffer, fieldnames=fieldnames, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(data_dict_list)

        else:
            return HttpResponse("No valid messages found.", status=204)

        # Reset buffer position to the beginning
        csv_buffer.seek(0)

        # Return CSV file as HTTP response
        response = HttpResponse(csv_buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="order_info_dump.csv"'
        if sqs_entries_to_be_deleted:
            sqs_client.delete_message_batch(
                QueueUrl=sqs_url, Entries=sqs_entries_to_be_deleted
            )
        return response

    except json.JSONDecodeError as json_err:
        logger.error(f"JSON decoding error: {json_err}")
        return HttpResponseServerError("Invalid message format.")

    except Exception as e:
        logger.error(f"Exception: {e}")
        return HttpResponseServerError(f"An error occurred: {e}")


@login_required
@user_passes_test(is_staff_user)
def update_products_in_batch_by_barcodes(request):
    try:
        post_data = request.POST
        product_barcodes = post_data.get("product_barcodes", "").split(",")
        new_supplier = post_data.get("new_supplier_for_batch", "")
        new_department = post_data.get("new_department_for_batch", "")
        new_location = post_data.get("new_location_for_batch", "")

        with transaction.atomic():
            for barcode in product_barcodes:
                product = Product.objects.get(barcode=barcode.strip())
                if new_supplier:
                    supplier = Supplier.objects.get(id=new_supplier)
                    product.supplier = supplier

                if new_department:
                    department = ProductDepartment.objects.get(id=new_department)
                    product.product_department = department

                if new_location:
                    location = LocationInStore.objects.get(id=new_location)
                    product.location_in_store = location
                product.save()
        messages.success(request, "Batch update successful")
        return redirect("product_management")

    except Exception as e:
        logger.error(f"Exception: {e}")
        messages.error(request, "Batch update failed")
        return HttpResponseServerError(f"An error occured: {e}")


@login_required
@user_passes_test(is_staff_user)
def update_product_price_by_barcode(request):
    try:
        post_data = request.POST
        barcode = post_data.get("price_update_product_barcode")
        new_price = post_data.get("price_update_new_price")
        with transaction.atomic():
            product = Product.objects.get(barcode=barcode.strip())
            if new_price:
                product.price = new_price
            else:
                raise Exception("New product price missing")
            product.save()
        messages.success(request, "Price update successful")
        return redirect("product_management")

    except Exception as e:
        logger.error(f"Exception: {e}")
        messages.error(request, "Price update failed")
        return HttpResponseServerError(f"An error occured: {e}")


@login_required
@user_passes_test(is_staff_user)
def fetch_marketing_opted_users(request):
    try:
        marketing_opted_users = list(
            UserProfile.objects.filter(marketing_preference=True).values_list(
                "user__email", flat=True
            )
        )
        return JsonResponse(
            {"marketing_opted_users_email": ",".join(marketing_opted_users)},
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error(f"Exception: {e}")
        messages.error(request, "Fetch failed")
        return HttpResponseServerError(f"An error occured: {e}")


@login_required
@csrf_exempt
@user_passes_test(is_super_staff_user)
def approve_product(request, product_id):
    if request.method == "POST":
        product = get_object_or_404(Product, product_id=product_id)
        product.is_admin_approved = True
        product.save()
        messages.success(request, "Product approved successfully")
        return JsonResponse(
            {"success": True, "message": f"Product {product_id} approved"}
        )
    else:
        messages.error(request, "Product approval failed")
        return JsonResponse(
            {"success": False, "error": "Invalid request method"}, status=405
        )


@login_required
def superadmin_authenticate(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            username = data.get("username")
            password = data.get("password")

            user = authenticate(request, username=username, password=password)

            if user and is_super_staff_user(user):
                return JsonResponse({"success": True})
            else:
                return JsonResponse(
                    {"success": False, "error": "Invalid credentials"}, status=401
                )

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=400)
    return JsonResponse(
        {"success": False, "error": "Invalid request method"}, status=405
    )


# Helper function to chunk large lists
BATCH_SIZE = 800


def chunked(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


@login_required
@user_passes_test(is_staff_user)
def sync_data_with_epos(request):
    if not request.user.is_superuser:
        raise PermissionDenied("You do not have permission to perform this operation.")

    preview = request.GET.get("preview") == "1"

    if request.method != "POST":
        return HttpResponseBadRequest("Invalid request method")

    try:
        files = request.FILES.getlist("epos_sync_file")
        if not files or len(files) != 1:
            return HttpResponseBadRequest("Upload exactly one CSV file")

        file = files[0]

        if file.size > settings.MAX_EPOS_FILE_SIZE:
            messages.error(request, "File too large")
            return HttpResponseBadRequest("File too large")

        if not file.name.lower().endswith(".csv"):
            messages.error(request, "Only CSV files allowed")
            return HttpResponseBadRequest("Only CSV files allowed")

        df = pd.read_csv(file, dtype=str)

        required_cols = {"PLU", "RetailPrice"}
        if not required_cols.issubset(df.columns):
            return HttpResponseBadRequest("CSV missing required columns")

        # Normalize CSV data
        df["PLU"] = df["PLU"].astype(str).str.strip()
        df["RetailPrice"] = df["RetailPrice"].apply(
            lambda x: Decimal(str(x)) if x and x != "nan" else None
        )

        barcode_to_price = {
            row["PLU"]: row["RetailPrice"]
            for _, row in df.iterrows()
            if row["RetailPrice"] is not None
        }

        if not barcode_to_price:
            return JsonResponse({"data": []})

        profit_multiplier = Decimal("1") + (
            Decimal(str(settings.WEBSITE_PROFIT_PERCENTAGE)) / Decimal("100")
        )

        results = []

        barcodes_from_file = set(barcode_to_price.keys())

        # take the intersection between the barcodes from file and barcodes in our system
        barcodes_in_db = set(Product.objects.values_list("barcode", flat=True))
        barcodes_to_process = list(barcodes_in_db.intersection(barcodes_from_file))

        for barcode_batch in chunked(barcodes_to_process, BATCH_SIZE):
            for barcode in barcode_batch:
                product = Product.objects.get(barcode=barcode)
                db_barcode = str(product.barcode).strip()
                epos_price = barcode_to_price.get(db_barcode)

                if epos_price is None:
                    continue

                new_price = Decimal(
                    str(round_up_to_star_9(float(epos_price * profit_multiplier)))
                )

                current_price = product.price or Decimal("0")

                if current_price != new_price:
                    results.append(
                        {
                            "product_id": product.id,
                            "name": product.name,
                            "barcode": db_barcode,
                            "current_price": float(current_price),
                            "epos_price": float(epos_price),
                            "new_price": float(new_price),
                            "difference": float(new_price - current_price),
                        }
                    )

                    if not preview:
                        product.cost_price = epos_price
                        product.profit_margin = settings.WEBSITE_PROFIT_PERCENTAGE
                        product.price = new_price
                        product.save(update_fields=["cost_price", "profit_margin", "price"])

        if preview:
            return JsonResponse(
                {
                    "count": len(results),
                    "data": results,
                }
            )

        return JsonResponse(
            {
                "success": True,
                "updated": len(results),
            }
        )

    except Exception as e:
        logger.exception("Error in EPOS sync/preview")
        return JsonResponse({"error": str(e)}, status=500)
    
@login_required
@user_passes_test(is_staff_user)
def export_orders_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="orders_export.csv"'

    writer = csv.writer(response)

    writer.writerow([
        "Order ID",
        "Product Name",
        "Barcode",
        "Quantity",
        "Discount Amount",
        "Unit Price",
        "Subtotal",
        "Order Created At",
        "Customer Email",
    ])

    # 🔹 Read date filters from query params
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    orders = (
        Order.objects
        .select_related("user")
        .prefetch_related(
            "order_items_from_order",
            "order_items_from_order__product",
            "order_items_from_order__product__location_in_store",
        )
        .order_by("-created_at")
    )

    # 🔹 Apply date filter only if both provided
    if start_date and end_date:
        try:
            start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")

            # include full end day
            end_dt = end_dt.replace(hour=23, minute=59, second=59)

            orders = orders.filter(created_at__range=(start_dt, end_dt))
        except ValueError:
            pass  # silently ignore bad dates and export all

    for order in orders:
        customer_email = (
            getattr(order, "customer_email", None)
            or getattr(order, "email", None)
            or (order.user.email if getattr(order, "user", None) else "")
        )

        for item in order.order_items_from_order.all():
            writer.writerow([
                order.order_id,
                item.product.name if item.product else "",
                getattr(item.product, "barcode", ""),
                item.quantity,
                item.discount_amount,
                item.order_item_unit_price,
                item.order_item_subtotal,
                order.created_at.strftime("%Y-%m-%d"),
                customer_email,
            ])

    return response


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_subscription(request):
    subscription_json = request.data.get('subscription')
    if not subscription_json:
        return Response({'error': 'No subscription provided'}, status=400)

    PushSubscription.objects.get_or_create(
        user=request.user,
        subscription_json=subscription_json
    )
    return Response({'message': 'Subscription saved'}, status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_subscription(request):
    subscription_json = request.data.get('subscription')
    PushSubscription.objects.filter(
        user=request.user,
        subscription_json=subscription_json
    ).delete()
    return Response({'message': 'Subscription deleted'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_notification(request):
    title = request.data.get('title', 'M18 Foods')
    body = request.data.get('body', '')
    url = request.data.get('url', '/')
    send_push_to_user(request.user, title, body, url)
    return Response({'message': 'Notification sent'})

@login_required
@user_passes_test(is_staff_user)
def instore_loyalty_award(request):
    """
    GET  → render the barcode-scan / amount-entry form
    POST → look up the loyalty account by barcode, award points, show result
    """
    context = {"notifications": get_unread_notifications()}
 
    if request.method == "POST":
        barcode_number  = request.POST.get("barcode_number", "").strip()
        order_amount_raw = request.POST.get("order_amount", "").strip()
        order_reference = request.POST.get("order_reference", "").strip() or None
 
        # ── Validate inputs ───────────────────────────────────────────────────
        if not barcode_number:
            context["error"] = "Please enter or scan a barcode."
            return render(request, "shop/instore_loyalty_award.html", context)
 
        try:
            order_amount = Decimal(order_amount_raw)
            if order_amount <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            context["error"] = "Please enter a valid purchase amount greater than £0."
            context["barcode_number"] = barcode_number
            return render(request, "shop/instore_loyalty_award.html", context)
 
        # ── Award points via existing service ─────────────────────────────────
        try:
            from rewards.services import award_points_for_instore
            tx = award_points_for_instore(
                barcode_number=barcode_number,
                order_amount=order_amount,
                order_reference=order_reference,
            )
            context["success"] = {
                "customer":      tx.loyalty_account.user_profile.fullname,
                "points_awarded": tx.points,
                "new_balance":   tx.balance_after,
                "amount":        order_amount,
                "transaction_id": str(tx.transaction_id),
                "order_reference": order_reference,
            }
        except ValueError as e:
            context["error"] = str(e)
            context["barcode_number"] = barcode_number
            context["order_amount"]   = order_amount_raw
 
        return render(request, "shop/instore_loyalty_award.html", context)
 
    return render(request, "shop/instore_loyalty_award.html", context)
 