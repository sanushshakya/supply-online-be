# CLAUDE.md

m18 storefront backend (supply-online-be): Django 5.2, DRF, Stripe. Tests: `python manage.py test` (or `docker compose exec m18-backend python manage.py test` from the workspace).

## Workspace rules
Shared rules live in the workspace CLAUDE.md (one folder up). m18 owns customers, orders, payments,
loyalty and presentation; IQ owns stock and (for linked products) price. Products with
`iq_price_managed` / IQ-managed stock must not be edited locally.

## Where things go in this repo
- IQ integration: `shop/integration/` (signing, events, stock, views). Keep the signing module
  byte-identical in behaviour with IQ's copy.
- Background work: `shop/tasks.py`. Queueing must never fail an order update.
- Emails: Django templates with autoescape only — no HTML built with f-strings.
- Tests: Django test runner; must pass on SQLite and Postgres.
