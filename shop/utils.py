import json
from openpyxl import Workbook
import csv
import math
from io import BytesIO
from django.http import HttpResponse
from .models import Product, UserQRAuth
import qrcode
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from django.core.mail import EmailMultiAlternatives
import boto3
import logging
from django.conf import settings
from shop.serializers import ProductSerializerForExport
import uuid
import barcode
from barcode.writer import ImageWriter
import os
from django.core.signing import Signer
from pywebpush import webpush, WebPushException
from .models import PushSubscription
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

logger = logging.getLogger(__name__)

signer = Signer()

def build_qr_response(user):
    """
    Generate a QR code PNG response for a staff user.
    Always rotates the secret because the DB only stores a one-way hash.
    """
    qr_auth, created = UserQRAuth.objects.get_or_create(user=user)

    # FIX: Always generate a new raw secret.
    # We cannot retrieve the old raw secret from 'secret_hash'.
    raw_secret = uuid.uuid4().hex
    
    # Save the hash of the new secret to the DB
    qr_auth.set_secret(raw_secret)
    qr_auth.is_active = True
    qr_auth.save()

    # Sign the payload using the raw secret
    payload = signer.sign(f"{user.id}:{raw_secret}")

    # Generate QR code
    img = qrcode.make(payload)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    # Return as downloadable response
    response = HttpResponse(buffer, content_type="image/png")
    response["Content-Disposition"] = f'attachment; filename="staff_{user.id}_qr.png"'

    return response


def store_image_in_s3(s3_path, image):
    """Store the images in the given s3 path

    Args:
        s3_path (str): s3 path where the image will be stored
        image (object): image object to be stored

    Returns:
        str: s3 url path where the image is stored
    """

    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name="eu-west-1",
        )
        s3_client.upload_fileobj(image, settings.AWS_S3_STORAGE_BUCKET_NAME, s3_path)
        logger.info("Product Image uploaded to S3 successfully")
        product_image_url = (
            f"https://{settings.AWS_S3_STORAGE_BUCKET_NAME}.s3.amazonaws.com/{s3_path}"
        )
        return product_image_url
    except Exception as e:
        logger.error(f"Error while uploading image to s3: {e}")
        raise


def send_email(subject, text_content, recipient_list, html_content=None):
    """
    Utility function to send email using Django's send_mail function.

    Args:
        subject (str): The subject of the email.
        message (str): The content of the email.
        recipient_list (list): A list of recipient email addresses.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """

    try:
        if not recipient_list:
            raise Exception(
                "Error while sending emails because recipient_list is empty"
            )

        msg = EmailMultiAlternatives(
            subject,
            text_content,
            from_email=settings.EMAIL_HOST_USER,
            to=recipient_list,
        )
        if html_content:
            msg.attach_alternative(html_content, "text/html")
        msg.send()
        return True

    except Exception as e:
        logger.error(f"Error while sending mail: {e}")
        return False


def generate_pdf(request):
    # Get your model objects
    selected_fields = [
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
    my_objects = Product.objects.only(selected_fields)

    # Create a PDF document
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []

    # Create a table to display model objects
    data = [
        ["barcode", "name", "cost_price", "price", "stock", "location_in_store"]
    ]  # Add more fields as needed
    for obj in my_objects:
        # Add more fields as needed
        data.append(
            [
                obj.barcode,
                obj.name,
                obj.cost_price,
                obj.price,
                obj.stock_quantity,
                obj.location_in_store,
            ]
        )

    # Add table to PDF document
    table = Table(data)
    elements.append(table)

    # Apply styles to the table
    style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            # Enable word wrap for all cells
            ("WORDWRAP", (0, 0), (-1, -1), True),
        ]
    )

    table.setStyle(style)

    # Add elements to the document
    doc.build(elements)

    # Move the cursor to the beginning of the buffer
    buffer.seek(0)

    # Create a Django response object
    response = HttpResponse(content_type="application/pdf")
    # Display PDF in browser
    response["Content-Disposition"] = "inline; filename=untitled.pdf"

    # Write the buffer content to the response
    response.write(buffer.getvalue())

    return response


def generate_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="untitled.csv"'

    writer = csv.writer(response)
    writer.writerow(
        ["Barcode", "Name", "Cost Price", "Price", "Stock", "Location in Store"]
    )  # Header row

    selected_fields = [
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
    my_objects = Product.objects.only(selected_fields)
    for obj in my_objects:
        writer.writerow(
            [
                obj.barcode,
                obj.name,
                obj.cost_price,
                obj.price,
                obj.stock_quantity,
                obj.location_in_store,
            ]
        )

    return response


def generate_excel(request):
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="products.xlsx"'

    workbook = Workbook()
    sheet = workbook.active

    # Get all Product objects
    selected_fields = [
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
    my_objects = Product.objects.only(*selected_fields)

    # Serialize the Product objects
    serializer = ProductSerializerForExport(my_objects, many=True)
    serialized_data = serializer.data

    if serialized_data:
        # Use the keys of the first serialized object as headers and convert them to a list
        headers = list(serialized_data[0].keys())
        sheet.append(headers)

        # Write the serialized data to the sheet
        for item in serialized_data:
            sheet.append(list(item.values()))

    workbook.save(response)
    return response


def store_file_in_s3(s3_path, file):
    """Store the file in the given s3 path

    Args:
        s3_path (str): s3 path where the file will be stored
        file (object): file object to be stored

    Returns:
        str: s3 url path where the file is stored
    """

    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name="eu-west-1",
        )
        s3_client.upload_fileobj(file, settings.AWS_S3_STORAGE_BUCKET_NAME, s3_path)
        logger.info("File uploaded to S3 successfully")
        file_url = (
            f"https://{settings.AWS_S3_STORAGE_BUCKET_NAME}.s3.amazonaws.com/{s3_path}"
        )
        return file_url

    except Exception as e:
        logger.error(f"Error while uploading file to s3: {e}")
        raise e


def push_purchased_order_info_to_sqs_for_epos_backend(data_dict, queue_url):
    """Send data_dict to an SQS queue.

    Args:
        data_dict (list of dict): Data to be sent to the SQS queue.
        queue_url (str): URL of the SQS queue.
    """

    try:
        assert (
            "data_dump" in data_dict
        )  # data_dict is supposed to have a data_dump and a data_type

        # Convert the data dictionary to a JSON string
        message_body = json.dumps(data_dict)

        # Initialize the SQS client
        sqs_client = boto3.client(
            "sqs",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
        )
        # Send the JSON message to SQS
        response = sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=message_body,
            MessageGroupId=data_dict.get(
                "data_type", "default"
            ),  # REQUIRED for FIFO queues
            # Use if ContentBasedDeduplication is NOT enabled
            MessageDeduplicationId=str(
                uuid.uuid4()
            ),  # Unique deduplication ID (e.g., UUID)
        )
        logger.info(f"Message sent to SQS queue {queue_url}")
        return True
    except Exception as e:
        logger.error(f"An error occurred while pushing data dict to sqs: {e}")
        return False


def generate_barcode(order_id):
    # Function to generate barcode

    # Define the directory path
    directory = "generated_barcodes"
    # Check if the directory exists, if not, create it
    if not os.path.exists(directory):
        os.makedirs(directory)

    CODE128 = barcode.get_barcode_class("code128")  # Use Code128 format
    barcode_obj = CODE128(order_id, writer=ImageWriter())
    output_file = os.path.join(directory, f"{order_id}_barcode")
    barcode_obj.save(output_file)  # Save the barcode as an image
    return f"{output_file}.png"


def round_up_to_star_9(price):
    pence = int(math.ceil(price * 100))  # 1.23 -> 123
    # Move upward to next "*9"
    remainder = pence % 10  # 123 % 10 -> 3
    if remainder <= 9:
        pence = pence - remainder + 9  # 123 - 3 + 9 -> 129
    return pence / 100  # 129 -> 1.29

def send_push_to_user(user, title, body, url='/'):
    """Call this from anywhere in Django to send a push notification"""
    subscriptions = PushSubscription.objects.filter(user=user)

    for sub in subscriptions:
        try:
            webpush(
                subscription_info=json.loads(sub.subscription_json),
                data=json.dumps({
                    'title': title,
                    'body': body,
                    'url': url,
                    'icon': '/icons/icon-192x192.png',
                }),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims=settings.VAPID_CLAIMS,
            )
        except WebPushException as e:
            print(f"Push failed for {user.email}: {e}")
            # If subscription expired, delete it
            if e.response and e.response.status_code == 410:
                sub.delete()
                