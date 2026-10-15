from django.db import migrations
from decimal import Decimal


def set_default_tax_category(apps, schema_editor):
    Product = apps.get_model("shop", "Product")
    TaxCategory = apps.get_model("shop", "TaxCategory")

    try:
        default_tax_category = TaxCategory.objects.get(name="VAT@20")
    except Exception:
        default_tax_category = None
        
    if not default_tax_category:
        default_tax_category = TaxCategory.objects.create(
            name="VAT@20",
            description="Value Added Tax at 20 percent",
            tax_rate=Decimal("20.00"),
        )
    for product in Product.objects.all():
        product.tax_category = default_tax_category
        product.save()


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0071_remove_orderitem_total_amount_and_more"),
    ]

    operations = [
        migrations.RunPython(set_default_tax_category),
    ]
