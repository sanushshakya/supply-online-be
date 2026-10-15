import unittest
import json
from unittest.mock import MagicMock, patch
from shop.utils import store_image_in_s3
from django.test import override_settings
from django.test import TestCase
from django.http import HttpRequest
from shop.utils import generate_excel
from shop.utils import push_purchased_order_info_to_sqs_for_epos_backend, round_up_to_star_9
from django.test import TestCase
from unittest.mock import patch, MagicMock


class TestStoreImageInS3(unittest.TestCase):
    @patch("shop.utils.boto3.client")
    @override_settings(
        AWS_ACCESS_KEY_ID="fake_access_key_id",
        AWS_SECRET_ACCESS_KEY="fake_secret_access_key",
        AWS_S3_STORAGE_BUCKET_NAME="fake_bucket_name",
    )
    def test_store_image_in_s3(self, mock_boto3_client):
        # Mock image data
        image_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c\xec\xbd\t\x00\x00\x00\x03\x00\x01q\x00\x00\x00\x00IEND\xaeB`\x82"
        image = MagicMock()
        image.read.return_value = image_data

        # Mock boto3 client
        mock_s3_client = MagicMock()
        mock_boto3_client.return_value = mock_s3_client

        # Call the function
        s3_path = "test/image.png"
        product_image_url = store_image_in_s3(s3_path, image)

        # Assertions
        self.assertIsNotNone(product_image_url)
        self.assertTrue(mock_boto3_client.called)
        mock_s3_client.upload_fileobj.assert_called_once_with(
            image, "fake_bucket_name", s3_path
        )
        self.assertTrue("fake_bucket_name.s3.amazonaws.com" in product_image_url)
        self.assertTrue(s3_path in product_image_url)


class GenerateExcelTestCase(TestCase):
    def test_generate_excel(self):
        # Create a mock request object
        request = HttpRequest()

        # Call the generate_excel function
        response = generate_excel(request)

        # Check that the response is a HttpResponse object
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(
            response["Content-Disposition"], 'attachment; filename="products.xlsx"'
        )

        # Ensure that the response content is not empty
        self.assertTrue(response.content)


class PushToSqsTests(TestCase):
    def setUp(self):
        self.data_dict = {
            "data_dump": [
                {"barcode": "123456789012", "quantity": 10},
                {"barcode": "987654321098", "quantity": 5},
            ]
        }
        self.queue_url = (
            "https://sqs.eu-west-1.amazonaws.com/123456789012/dummy-queue-name"
        )

    @patch("shop.utils.boto3.client")
    @patch("shop.utils.logger")
    def test_push_to_sqs_success(self, mock_logger, mock_boto_client):
        """Test that the function returns True and logs success when the message is sent successfully."""
        # Mock the SQS client and its send_message method
        mock_sqs_client = MagicMock()
        mock_boto_client.return_value = mock_sqs_client
        mock_sqs_client.send_message.return_value = {"MessageId": "test-message-id"}

        # Call the function
        result = push_purchased_order_info_to_sqs_for_epos_backend(
            self.data_dict, self.queue_url
        )

        # Check that the function returned True
        self.assertTrue(result)

        # Check that send_message was called with the correct parameters
        mock_sqs_client.send_message.assert_called_once()


        # Check the logging (assuming logger is set up for INFO level)
        mock_logger.info.assert_called_once_with(
            f"Message sent to SQS queue {self.queue_url}"
        )

    @patch("shop.utils.boto3.client")
    @patch("shop.utils.logger")
    def test_push_to_sqs_failure(self, mock_logger, mock_boto_client):
        """Test that the function returns False and logs error when sending message fails."""
        # Mock the SQS client and its send_message method to raise an exception
        mock_sqs_client = MagicMock()
        mock_boto_client.return_value = mock_sqs_client
        mock_sqs_client.send_message.side_effect = Exception("SQS error")

        # Call the function
        result = push_purchased_order_info_to_sqs_for_epos_backend(
            self.data_dict, self.queue_url
        )

        # Check that the function returned False
        self.assertFalse(result)

        # Check that send_message was called with the correct parameters
        mock_sqs_client.send_message.assert_called_once()

        # Check the logging (assuming logger is set up for ERROR level)
        mock_logger.error.assert_called_once_with(
            "An error occurred while pushing data dict to sqs: SQS error"
        )


class RoundUpToStar9Tests(TestCase):
    def test_rounds_up_to_ending_in_9(self):
        self.assertEqual(round_up_to_star_9(1.21), 1.29)
        self.assertEqual(round_up_to_star_9(1.00), 1.09)
        self.assertEqual(round_up_to_star_9(2.33), 2.39)
        self.assertEqual(round_up_to_star_9(0.01), 0.09)
        self.assertEqual(round_up_to_star_9(2.90), 2.99)
        self.assertEqual(round_up_to_star_9(2.99), 2.99)

    def test_rounds_exact_x9_values_no_change(self):
        self.assertEqual(round_up_to_star_9(3.19), 3.19)
        self.assertEqual(round_up_to_star_9(4.49), 4.49)

    def test_rounds_zero(self):
        self.assertEqual(round_up_to_star_9(0), 0.09)

    def test_rounds_values_with_floating_point(self):
        self.assertEqual(round_up_to_star_9(1.2345), 1.29)
        self.assertEqual(round_up_to_star_9(5.876), 5.89)