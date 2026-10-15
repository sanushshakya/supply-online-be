# forms.py
from .models import OrderStatus
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.admin.helpers import ActionForm

class CustomAuthenticationForm(AuthenticationForm):
    # Add any additional customization if needed
    pass


class OrderStatusFilterForm(forms.Form):
    status = forms.ChoiceField(
        choices=[(status.value, status.name) for status in OrderStatus], required=False)



class CartItemExportActionForm(ActionForm):
    """
    Extends ActionForm so the required 'action' field exists.
    """
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="From date"
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="To date"
    )
    include_headers = forms.BooleanField(
        required=False,
        initial=True,
        label="Include CSV header row"
    )

