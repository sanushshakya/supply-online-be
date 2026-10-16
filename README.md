This is the backend application for m18 World Foods E-commerce web app.

## Supply Chain IQ integration

When a Stripe payment confirms an order, the shop records an `order.paid` event in an outbox (`shop.integration.IntegrationEvent`, same transaction as the stock commit) and Celery posts it to Supply Chain IQ straight after the commit. IQ takes the units from its batches (oldest expiry first), so its stock and demand include web sales.

- **Settings (env):** `IQ_WEBHOOK_URL` (IQ's `https://<iq-host>/sync/inbound/storefront/<connection id>/`) and `IQ_WEBHOOK_SECRET`. With `IQ_WEBHOOK_URL` empty, nothing is recorded or sent.
- **Workers:** a Celery worker delivers each event as soon as the transaction commits. Beat runs `shop.tasks.deliver_integration_events` every 30 s to retry failures, backing off `min(2**attempts, 3600)` s; after 20 attempts the event is `failed`. Check stuck events in the admin under *Integration events*.
- **Contract:** a JSON body `{"event_id", "event_type", "occurred_at", "data"}` with the header `X-Integration-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, "<t>." + raw body)>`. IQ refuses signatures more than 300 s old. `order.paid` data is `{"order_id", "items": [{"product_id", "quantity", "unit_price"}]}`, where `product_id` is the shop product's UUID (IQ stores it as `Product.external_id`). Delivery is at-least-once, and IQ ignores a repeated `event_id`. `shop/integration/signing.py` must stay in step with IQ's `sync/signing.py`.
- **Rotating the secret:** generate one (`python -c "import secrets; print(secrets.token_hex(32))"`), set it on the IQ `StorefrontConnection` in the IQ admin, then set `IQ_WEBHOOK_SECRET` here and restart the web and worker processes. Events sent in between fail with 401 and the sweep redelivers them.
