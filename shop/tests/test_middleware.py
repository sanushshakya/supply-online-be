import os
import threading
from rest_framework.test import APITestCase
from django.urls import reverse
from django.conf import settings


class TestRateLimitMiddleware(APITestCase):
    def setUp(self) -> None:
        return super().setUp()

    def test_rate_limit(self):
        if os.getenv("RUN_RATE_LIMIT_TEST", False):
            # Define the endpoint URL to test
            url = reverse('csrf-token')

            # Define the number of concurrent requests to simulate
            num_requests = 110

            # Define a function to send requests
            def send_request():
                response = self.client.get(url)
                return response

            # Create threads to send concurrent requests
            threads = []
            responses = []
            for _ in range(num_requests):
                thread = threading.Thread(
                    target=lambda: responses.append(send_request()))
                threads.append(thread)
                thread.start()

            # Wait for all threads to finish
            for thread in threads:
                thread.join()

            # Check if responses are within expected rate limit or forbidden
            allowed_requests = settings.ALLOWED_REQUEST_PER_IP_PER_HOUR
            count_of_denied_request = sum(
                [1 for response in responses if response.status_code == 429])
            self.assertEqual(count_of_denied_request,
                             num_requests-allowed_requests-1)

    def tearDown(self) -> None:
        return super().tearDown()
