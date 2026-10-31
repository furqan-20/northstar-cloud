# NorthStar implementation notes

## Stack

- Python 3.10+ standard library only.
- `ThreadingHTTPServer` and a small explicit request router for the local HTTP server.
- `sqlite3` with foreign keys, WAL journalling and a busy timeout for durable data.
- HTML, responsive CSS and plain JavaScript using Fetch and the History API.
- No framework, compilation, package installation or remote asset dependency.

## Request path

The server serves the common HTML shell for known application routes and local static files under `/static/`. `static/js/app.js` renders the appropriate page and requests current data through the JSON API. Unknown page/API resources return 404. The frontend shows loading, empty, error and success states rather than relying on static hardcoded results.

The browser's user state controls visible navigation. The backend separately enforces access to protected data and administrator actions; hiding links is not its authorization mechanism.

## Persistence

`database.initialize()` creates the schema and initial records on first launch. It does not reset existing records on restart. `catalog.py` defines 20 starting products, of which four are featured on the homepage. One product starts with zero stock as an ordinary availability state.

Key tables: `users`, `sessions`, `products`, `carts`, `cart_coupons`, `wishlist`, `addresses`, `orders`, `order_items`, `order_events`, `tickets`, `subscribers`, `auth_attempts`.

The default database is `instance/northstar.sqlite3`. To use an independent data folder on Linux/macOS:

```bash
NORTHSTAR_DATA_DIR=/absolute/path/to/northstar-data python3 server.py
```

Use one server per data folder. Stop it before making a backup or running the reset helper. SQLite creates `-wal`/`-shm` companions while in use; a stopped-server backup of the whole data folder avoids partial backups.

## Accounts and sessions

- PBKDF2-HMAC-SHA256 with 600,000 iterations and a random per-password salt.
- Random session tokens; the database stores their SHA-256 digests, not the raw cookies.
- Server-side sessions expire after seven days.
- HttpOnly, SameSite=Lax cookies. Local HTTP does not set Secure by default. An HTTPS installation can set `NORTHSTAR_SECURE_COOKIE=1`.
- CSRF tokens on writes and an Origin check when an Origin header is supplied.
- Login, registration and logout rotate the session; a password change invalidates other sessions.
- Authentication and support submission rate limits.
- Parameterized SQL, escaped dynamic HTML and constrained static-file paths.
- Content Security Policy, no-sniff, frame restrictions, permissions policy and same-origin referrer policy.

These are implemented protections for a local application, not a claim of a security audit or production certification.

## Bags and checkout

Guest bags use a guest session owner key. Signed-in bags use the account ID. At sign-in, guest quantities are merged into the account bag up to current stock/per-item limits, and the offer is carried across.

Checkout uses `BEGIN IMMEDIATE` to serialize stock-changing operations. The server recalculates totals, verifies quantities and availability, creates the order, deducts stock and clears the cart within a single transaction. An account-scoped idempotency key prevents duplicate orders from repeated submission. Product names, images, quantities, prices and delivery details are copied into the order so that catalogue/address edits do not rewrite history.

Cancellation uses a write transaction and the allowed state machine, so stock is restored once. Shipped or delivered orders cannot be cancelled through the account UI/API. The admin cannot arbitrarily jump between statuses.

## Frontend organisation

`app.js` includes routing, a Fetch wrapper, reusable field/product components, page renderers and event handlers. A render counter avoids mounting a stale page after rapid navigation. Requests time out after 15 seconds. Forms display field-specific errors returned by the server. Native `dialog` supplies modal focus behaviour. Local font fallback, reduced-motion CSS and media queries handle different display conditions.

Logical routes include the home, shop, product, auth, wishlist, cart, checkout, account, orders, support, about, journal, policy and admin screens. No service worker caches API data.

## Local scope

The bundled server intentionally uses Python's local HTTP facilities. It is not an internet-facing production server. The shop has no payment gateway, mail service, courier integration, account-recovery email, user image uploads or automatic return/refund engine. The UI and documentation describe those limits where they affect use.

No automated test code or injected defect is part of this package. Formal cross-browser/API/network-mocking work can be added later against this application's real endpoints.

## Official implementation references

- [Python HTTP server documentation](https://docs.python.org/3/library/http.server.html)
- [Python SQLite documentation](https://docs.python.org/3/library/sqlite3.html)
- [Python password derivation primitives](https://docs.python.org/3/library/hashlib.html#hashlib.pbkdf2_hmac)
- [Python secure token generation](https://docs.python.org/3/library/secrets.html)
