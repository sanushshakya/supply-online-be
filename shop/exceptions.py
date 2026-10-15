from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status


class ExpiredSignatureError(Exception):
    pass


class InvalidTokenError(Exception):
    pass


class BadRequestError(Exception):
    pass


class InsufficientStockError(Exception):
    """Raised when requested quantities exceed available stock.

    `items` is a list of {"product_id", "name", "requested", "available"} dicts.
    """

    def __init__(self, items):
        self.items = items
        super().__init__("Insufficient stock")

    def to_response_data(self):
        names = ", ".join(item["name"] for item in self.items)
        return {
            "error": f"Not enough stock for: {names}",
            "code": "INSUFFICIENT_STOCK",
            "items": self.items,
        }


def custom_exception_handler(exc, context):
    """
    Custom exception handler to catch token-related exceptions.
    """
    response = exception_handler(exc, context)

    if isinstance(exc, InsufficientStockError):
        return Response(exc.to_response_data(), status=status.HTTP_409_CONFLICT)

    if isinstance(exc, BadRequestError):
        return Response({"error": "Bad request"}, status=status.HTTP_400_BAD_REQUEST)

    return response
