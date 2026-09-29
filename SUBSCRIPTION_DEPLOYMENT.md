# Subscription hardening: deployment and verification

## Deployment is not yet complete

The code and isolated regression tests are updated. No live database migration, RevenueCat dashboard change, purchase, refund, or deployment was performed.

The local configuration has a webhook authorization secret, but **REVENUECAT_API_KEY and REVENUECAT_APP_IDS are missing**. Do not deploy this change without configuring the server API key: real webhook deliveries and authenticated verification deliberately return 503 when the provider cannot be verified.

Set these in Dokploy's backend environment (not the app's EXPO_PUBLIC environment):

```dotenv
REVENUECAT_API_KEY=<RevenueCat secret API key with subscriber-read permission>
REVENUECAT_WEBHOOK_SECRET=<new random secret matching the webhook Authorization header>
REVENUECAT_APP_IDS=<allowed RevenueCat app ID,comma-separated if needed>
REVENUECAT_ALLOW_SANDBOX=false
REVENUECAT_SIGNING_SECRET=<optional webhook HMAC signing secret>
```

Rotate the previously committed webhook secret in BOTH RevenueCat and the deployed environment. Removing it from source does not revoke exposed copies. Enable HMAC in the dashboard if supplying the signing secret. Use a separate test backend with ALLOW_SANDBOX=true for store sandbox / Test Store purchases; do not enable it on production.

Webhook URL: `https://<backend>/api/subscription/webhook/`. Subscribe to all lifecycle events, including TRANSFER. Both webhook path spellings already supported by the backend remain supported. App customer IDs must be immutable **UserProfile.id**, not User.id, email, username, or a locally generated anonymous ID.

Back up PostgreSQL and deploy migrations before the backend/app release:

```sh
python manage.py migrate
python manage.py reconcile_subscriptions
```

Configure a Dokploy scheduled command to run `python manage.py reconcile_subscriptions` every 15 minutes. No scheduler was installed or configured by this change. The command exits nonzero on failure; alert on failures and webhook 503s. Use `--profile-id <UUID>` for a targeted reconciliation. The command refreshes known store customers; customers never seen by the backend are discovered by authenticated startup/purchase/restore sync and webhooks.

## Implemented behavior

- Webhooks use constant-time authorization, optional timestamped HMAC, an allowed-app filter, and sandbox separation. Missing authorization configuration fails closed. Provider traffic no longer shares anonymous API throttling.
- Each accepted event fetches current server-side RevenueCat subscriber state. Cancellation does not itself remove paid access. Expiry, grace periods, refunds, renewals, product changes, restoration and transfer use verified entitlements rather than product-name guesses.
- A unique event ledger and unique charge key prevent duplicate processing/payment creation. State and event completion commit together; provider failure rolls back and returns a retryable status. Synchronous processing is intentional: there is no durable job worker in this deployment to safely acknowledge unfinished work.
- Unknown customers and ambiguous aliases are not silently acknowledged or assigned to another account. Inspect failed deliveries, resolve ownership, then retry in RevenueCat. Deleted customers also need operational review; the pre-existing account-deletion data-retention policy was not changed.
- Entitlements retain separate expirations. All HTTP and socket feature gates evaluate expiration at access time, including already-open community sockets. Community detail/history/send checks use the same allowed-room selection. Users can leave rooms after losing access.
- Gifts are separate from store entitlements. Removing a gift does not cancel or revoke a paid store subscription. Existing dated manual grants with no store metadata are preserved as gifts on first reconciliation. Review legacy/manual grants before rollout; their historical provenance cannot be reconstructed from code.
- Usage counters are updated under profile row locks and commit with message/like writes. Message quota bootstrap counts first initiated conversations in the current month/year, not ongoing replies. Deleting messages or undoing likes does not refund already recorded usage. Existing history supplies the initial baseline; previously deleted history cannot be reconstructed.
- The app switches RevenueCat identity before purchases, prevents concurrent purchase operations, and verifies purchases/restores through the authenticated backend. It never grants a chosen plan optimistically or calls the removed mock-upgrade API. Cancellation is not presented as an error. Account changes invalidate stale profile results.
- Purchase/restore and background verification invalidate cached feature data when appropriate. Store-localized prices are used for add-ons, and generic `$rc_monthly` packages cannot accidentally sell Light as Plus. Unconfigured products remain unavailable rather than guessed.
- Payment reporting hides duplicate legacy receipt IDs without deleting records; placeholder card numbers are no longer presented as real payment methods. Historical subscription end dates are no longer fabricated from product names. Historical receipt data is not a replacement for RevenueCat/store financial exports or tax accounting.

## Required rollout checks

1. Remove the Advanced Filters and All Chat Rooms products/entitlements from the RevenueCat offering. Keep only `premium_light`, `premium_plus`, and `add_on_match_analysis`. Configure explicit product/package IDs used by the app; do not rely on generic package names to distinguish tiers.
2. Confirm the intended RevenueCat restore/transfer policy. Test account A → B on the same device and purchase restoration on another device. Existing merged/ambiguous customer IDs require review, not automatic grants.
3. On the test backend, test a real Android store purchase, cancellation with remaining time, renewal, expiry, grace, refund, restoration, transfer, lifetime and recurring add-ons. Confirm both app gates and server denial after expiry. These real-store tests were not performed here.
4. Re-deliver a webhook twice and out of order; verify one payment and current access. Simulate provider downtime, then retry. Check signed requests and wrong-secret rejection.
5. Run PostgreSQL concurrency checks in staging. Automated tests here use isolated SQLite; they verify behavior but cannot prove PostgreSQL row-lock concurrency under load.
6. Account deletion does not cancel a store subscription. Review cancellation guidance and legal financial-retention requirements before changing deletion policy. Existing historical payment records and grants need reconciliation against provider records; they were not rewritten in the live database.

## Runnable checks

```sh
DATABASE_URL=sqlite:///:memory: .venv/bin/python manage.py test api.test_subscriptions api.tests api.test_chat_socket
DATABASE_URL=sqlite:///:memory: .venv/bin/python manage.py check
DATABASE_URL=sqlite:///:memory: .venv/bin/python manage.py makemigrations --check --dry-run
```

From Constela-app: `node --test tests/purchases.test.cjs` and `npx tsc --noEmit`.

The app's full type-check still has pre-existing errors in i18n, onboarding camera/image options, the email route, sheet profile typing, and Firebase messaging imports. No errors were reported in the changed subscription/purchases code. A clean release build and physical-device store tests are still required.

Design reference: [RevenueCat webhook verification, duplicate deliveries and subscriber synchronization](https://www.revenuecat.com/docs/integrations/webhooks).
