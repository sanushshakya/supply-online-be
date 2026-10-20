This is the backend application for m18 World Foods E-commerce web app (Django 5.2 LTS, Python 3.11).

## Tests and CI

`python manage.py test` runs the whole suite on SQLite; set `POSTGRESDB_NAME`/`POSTGRESDB_USER`/`POSTGRESDB_PASS`/`DB_HOST`/`DB_PORT`
to run it on Postgres (the user needs CREATEDB). GitHub Actions (`.github/workflows/ci.yml`) runs `check`, the missing-migration
check and the suite on Python 3.11 + Postgres 16, and builds `Dockerfile.local` on every push. Tests must not depend on
deployment settings (S3, staff emails, a collectstatic manifest): patch or `override_settings` them.

## Local Docker (with Supply Chain IQ)

`Dockerfile.local` is the image the workspace-level `docker-compose.yml` uses (production keeps `Dockerfile`).
Setting `POSTGRESDB_NAME` switches the database to Postgres in any `ENV` (`POSTGRESDB_*`, `DB_HOST`, `DB_PORT`).
`python manage.py seed --fixture <dumpdata.json>` loads a data snapshot into an empty database (skipped once
it has users; model signals are muted while it loads) and creates the superuser from
`DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` if missing; an existing
user is promoted and keeps its password.

## Supply Chain IQ integration

When a Stripe payment confirms an order, the shop records an `order.paid` event in an outbox (`shop.integration.IntegrationEvent`, same transaction as the stock commit) and Celery posts it to Supply Chain IQ straight after the commit. IQ takes the units from its batches (oldest expiry first), so its stock and demand include web sales.

- **Settings (env):** `IQ_WEBHOOK_URL` (IQ's `https://<iq-host>/sync/inbound/storefront/<connection id>/`) and `IQ_WEBHOOK_SECRET`. With `IQ_WEBHOOK_URL` empty, nothing is recorded or sent.
- **Workers:** a Celery worker delivers each event as soon as the transaction commits. Beat runs `shop.tasks.deliver_integration_events` every 30 s to retry failures, backing off `min(2**attempts, 3600)` s; after 20 attempts the event is `failed`. Check stuck events in the admin under *Integration events*.
- **Contract:** a JSON body `{"event_id", "event_type", "occurred_at", "data"}` with the header `X-Integration-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, "<t>." + raw body)>`. IQ refuses signatures more than 300 s old. `order.paid` data is `{"order_id", "items": [{"product_id", "quantity", "unit_price"}]}`, where `product_id` is the shop product's UUID (IQ stores it as `Product.external_id`). Delivery is at-least-once, and IQ ignores a repeated `event_id`. `shop/integration/signing.py` must stay in step with IQ's `sync/signing.py`.
- **One endpoint for IQ's events:** `POST /integration/events/` (`shop/integration/views.py`) takes every event IQ sends (`loyalty.award`, `loyalty.reverse`, `stock.changed`), signed like the rest; `/rewards/api/integration/events/` is the same view under its older path.
- **Stock from IQ:** IQ owns stock for the products it links. `stock.changed` carries `{"items": [{"product_id", "online_available", "version"}]}` about every 15 s after a change (`shop/integration/stock.py`). A product's first update marks it `iq_managed`; an item whose `version` is not newer than the product's `iq_stock_version` is skipped. `stock_quantity` becomes IQ's figure minus units held for unpaid checkouts (those are already deducted here and IQ only hears of an order once it is paid), never below 0. Unknown products come back in `unknown_products` and are not retried. For an `iq_managed` product, stock cannot be changed here (staff add-stock page, product forms and API, admin): change it in IQ. `POST /integration/stock/` returns every product's stock and price for IQ's nightly comparison.
- **Prices from IQ:** once IQ switches price pushing on, each `stock.changed` item also carries `"price": "12.99"` (IQ's approved price), under the same version. The first one marks the product `iq_price_managed`: its price can then not be changed here (product forms and API, price-by-barcode, admin), and the EPOS CSV sync skips it (reported as `skipped_iq_managed`). A price outside 0 < p ≤ 999.99 (the column's cap) or not a 2-dp string is refused for that item only: the stock still applies, and the product comes back in `price_rejected`.
- **Loyalty endpoints for the IQ till:** IQ calls these with the same signature and secret; there is no user login, and an empty `IQ_WEBHOOK_SECRET` refuses every call with 401.
  - `POST /rewards/api/integration/lookup/` with `{"barcode"}` returns only `{"first_name", "points_balance", "tier", "points_gbp_value"}`, or 404 `{"detail": "not_found"}` for an unknown or inactive card.
  - `POST /rewards/api/integration/events/` takes `loyalty.award` (`{"barcode", "amount", "order_reference"}`) and `loyalty.reverse` (`{"order_reference"}`) envelopes. A repeated `event_id` changes nothing, and an award is also de-duplicated on `order_reference`. A signed, well-formed envelope always gets 200 with `{"status": "applied" | "duplicate" | "unknown_account" | "nothing_to_reverse" | "ignored"}`, so IQ does not retry a refusal. Received events appear under *Integration events* with direction *Inbound*.
- **Rotating the secret:** generate one (`python -c "import secrets; print(secrets.token_hex(32))"`), set it on the IQ `StorefrontConnection` in the IQ admin, then set `IQ_WEBHOOK_SECRET` here and restart the web and worker processes. Events sent in between fail with 401 and the sweep redelivers them.
