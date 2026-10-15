from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
from django.conf import settings
from django.http import JsonResponse
from .models import FeatureFlag

import logging

logger = logging.getLogger(__name__)


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        # Use the first IP in the list
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


class RateLimitMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # Check if the request exceeds the rate limit
        # Limit each IP address to 100 requests per hour for all methods
        ip_address = get_client_ip(request)
        request_count_key = f"request_count:{ip_address}"
        request_count = cache.get(request_count_key, 0)
        if request_count > settings.ALLOWED_REQUEST_PER_IP_PER_HOUR:
            logger.error(f"Too many request from IP address: {request_count_key}")
            return JsonResponse({"error": "Rate limit exceeded"}, status=429)
        else:
            # Increment the request count
            cache.set(request_count_key, request_count + 1, timeout=3600)
        return None


class OrderFeatureFlagMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        # Check if the requested view is an instance of OrderViewSet
        if hasattr(view_func, "cls") and view_func.cls.__name__ == "OrderViewSet":
            # Check if the feature flag is enabled
            if not FeatureFlag.objects.filter(
                name="is_ordering_enabled", enabled=True
            ).exists():
                return JsonResponse({"error": "Ordering is disabled"}, status=403)
        return None
