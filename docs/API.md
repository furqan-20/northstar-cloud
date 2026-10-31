# NorthStar JSON API

Base URL when run with defaults: `http://127.0.0.1:8000`. All request/response bodies are JSON. IDs and order references come from server responses. Prices and totals are whole PKR integers.

## Sessions and request headers

1. Send `GET /api/session`, retaining the response cookie.
2. Read the response's `csrf_token`.
3. Include that cookie and `X-CSRF-Token: <token>` on every POST, PATCH and DELETE request. Use `Content-Type: application/json` for JSON bodies.
4. Login, registration and logout rotate the cookie and return a new token. Use the new token for later writes. A browser uses same-origin credentials automatically.

`GET /api/session` returns:

```json
{
  "user": null,
  "csrf_token": "server-generated-token",
  "cart_count": 0,
  "wishlist": []
}
```

When signed in, `user` contains `id`, `name`, `email`, `phone`, `role` and `created_at`. Password hashes and session IDs are never returned. Guest carts are linked to their session; customer carts are linked to the account.

## Catalogue and configuration

| Method | Path | Behaviour / success |
| --- | --- | --- |
| GET | `/api/config` | Categories, cities, currency and delivery rules; 200. |
| GET | `/api/products` | `{products: [...], total, categories}`; 200, including an empty result. |
| GET | `/api/products/<slug-or-id>` | `{product, related}`; 200 or 404. |

Product query parameters: `q`, `category`, `in_stock=1`, `featured=1`, `new=1`, `min_price`, `max_price`, `sort`. Sort values: `featured`, `price_asc`, `price_desc`, `name`, `newest`. Filters combine. Search uses a case-insensitive substring match across product name, description and category. All active matching products are returned; there is no pagination.

Product fields: `id`, `slug`, `name`, `category`, `price`, `compare_price`, `description`, `specs`, `image`, `color`, `badge`, `stock`, `featured`, `active`, `created_at`. `specs` is an object of text keys and values. Archived products are absent from the public catalogue.

## Accounts

| Method | Path | Body | Success |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | `name`, `email`, `password`, `terms: true` | 201, `{user, csrf_token}`. |
| POST | `/api/auth/login` | `email`, `password` | 200, `{user, csrf_token}`. |
| POST | `/api/auth/logout` | Empty body | 200, new guest session/token. |
| PATCH | `/api/profile` | `name`, optional `phone` | 200, `{user}`; sign-in required. |
| POST | `/api/profile/password` | `current_password`, `new_password` | 200; sign-in required. |

Registration and new passwords require 8–128 characters, at least one ASCII letter and one digit. Email is case-insensitive. Duplicate registration returns 409. Invalid login returns 401. Eight failed attempts within 15 minutes for the same email/client trigger 429. Password changes invalidate other sessions for that account.

## Saved addresses: full CRUD

All address routes require sign-in and restrict access to the current account.

| Method | Path | Behaviour / success |
| --- | --- | --- |
| POST | `/api/addresses` | Create an address; 201, `{address}`. |
| GET | `/api/addresses` | Read owned addresses; 200, `{addresses: [...]}`. |
| PATCH | `/api/addresses/<id>` | Replace address fields; 200, `{address}`. |
| DELETE | `/api/addresses/<id>` | Remove owned address; 200, `{message}`. |

POST and PATCH both require the full address object, including `label`:

```json
{
  "label": "Home",
  "name": "Demo Customer",
  "phone": "03001234567",
  "line1": "House 18, Street 4",
  "line2": "Block 7, Gulshan-e-Iqbal",
  "city": "Karachi",
  "postal_code": "75300"
}
```

`line2` may be omitted or empty. City must be one returned by `/api/config`. Postal code is exactly five digits. Mobile numbers support `03XXXXXXXXX` and `+923XXXXXXXXX` with spaces, brackets or hyphens. Maximum 10 saved addresses per account. Missing or other-user addresses return 404. Removing or editing a saved address never changes existing order snapshots.

## Wishlist

| Method | Path | Body / success |
| --- | --- | --- |
| GET | `/api/wishlist` | 200, `{products: [...]}`. |
| POST | `/api/wishlist` | `{product_id: <integer>}`; 201. Adding an existing item is idempotent. |
| DELETE | `/api/wishlist/<product-id>` | 200; 404 if absent. |

All routes require sign-in. Archived items are hidden from the public wishlist.

## Shopping bag

| Method | Path | Body / success |
| --- | --- | --- |
| GET | `/api/cart` | 200, cart summary. |
| POST | `/api/cart/items` | `product_id`, `quantity`; 201, cart summary. Adds to existing quantity. |
| PATCH | `/api/cart/items/<product-id>` | `quantity`; 200, cart summary. Sets the quantity. |
| DELETE | `/api/cart/items/<product-id>` | 200, cart summary. |
| POST | `/api/cart/coupon` | `code`; 200, cart summary. |
| DELETE | `/api/cart/coupon` | 200, cart summary. |

Guests can use all bag endpoints. Quantities must be integers from 1 to 20 and cannot exceed current stock. Out-of-stock/excess quantity returns 409. There is no quantity-zero deletion; use DELETE. A missing bag item returns 404.

Cart summaries contain `items`, `count` (total units), `subtotal`, `discount`, `shipping`, `total`, `coupon`, `coupon_applied`, `coupon_message`, `free_shipping_threshold`. Each item includes product data plus `quantity` and `line_total`.

Offers:

- WELCOME10: 10%, minimum subtotal 3,000, cap 2,000.
- WORKSPACE15: 15%, minimum subtotal 10,000, cap 3,000.
- One code at a time. Discount = minimum of the integer percentage amount and cap.
- Delivery = 250, unless the merchandise total after discount is at least 8,000; then zero. Empty bags have zero delivery.
- If a bag changes and an applied code no longer meets its minimum, the code remains visible with `coupon_applied: false`, a zero discount and a helpful message.

## Orders

| Method | Path | Behaviour / success |
| --- | --- | --- |
| POST | `/api/orders` | Create order from the signed-in customer's bag; 201. |
| GET | `/api/orders` | 200, `{orders: [...]}` belonging to the signed-in customer. |
| GET | `/api/orders/<number>` | 200, `{order}` or 404 if missing/not owned. |
| POST | `/api/orders/<number>/cancel` | 200, `{order}`; 409 after dispatch or if already cancelled. |

Order body:

```json
{
  "address": {
    "name": "Demo Customer",
    "phone": "03001234567",
    "line1": "House 18, Street 4",
    "line2": "Block 7",
    "city": "Karachi",
    "postal_code": "75300"
  },
  "payment_method": "cod",
  "terms": true,
  "note": "Please call on arrival.",
  "idempotency_key": "unique-checkout-key-at-least-16-characters"
}
```

`note` is optional, max 500 characters. `idempotency_key` must be 16–100 characters and unique for a new checkout. Retrying the same key returns the original order with 200 instead of placing it twice. Prices/totals in the request are not accepted as the source of truth. The backend calculates totals, verifies availability, deducts stock, writes item/address snapshots, creates the timeline and clears the bag in one SQLite transaction.

Orders contain `number`, `status`, totals, address, payment method, note, creation time, `items` and `events`. The idempotency key is not exposed in responses. Order references start with `NS-`. Dates are stored as UTC ISO 8601 strings and shown in the browser's local time.

## Support and newsletter

| Method | Path | Behaviour / success |
| --- | --- | --- |
| POST | `/api/support` | `name`, `email`, `subject`, `message`; 201, `{message, reference}`. |
| GET | `/api/support` | Sign-in required; 200, `{tickets: [...]}` linked to that account. |
| POST | `/api/newsletter` | `email`; 201, `{message}`. Repeat subscriptions do not create duplicates. |

Support messages require 20–3,000 characters. Subjects require 3–120 characters. A guest submission is saved in the admin inbox without an account link. Sign in before sending to track replies in the account. Ten messages per client per hour are allowed. No email is sent by either feature.

## Administrator API

All of these routes require the administrator role. Customer sessions receive 403; guests with a valid CSRF token receive 401.

| Method | Path | Behaviour / success |
| --- | --- | --- |
| GET | `/api/admin/overview` | Counts and delivered revenue; 200, `{stats}`. |
| GET | `/api/admin/products` | All active/archived products; 200, `{products}`. |
| POST | `/api/admin/products` | Create product; 201, `{product}`. |
| PATCH | `/api/admin/products/<id>` | Edit fields; 200, `{product}`. |
| DELETE | `/api/admin/products/<id>` | Archive and remove from bags; 200. Preserves order history. |
| GET | `/api/admin/orders` | All orders with customer name/email; 200, `{orders}`. |
| PATCH | `/api/admin/orders/<number>` | `{status: "Processing"}` or another allowed transition; 200, `{order}`. |
| GET | `/api/admin/tickets` | All messages; 200, `{tickets}`. |
| PATCH | `/api/admin/tickets/<id>` | `response` (5–3,000 characters), `status` (`Open`/`Resolved`); 200. |

Product creation requires `name`, unique lowercase hyphenated `slug`, `category`, positive integer `price`, non-negative integer `stock`, `description` (20–3,000 characters), bundled `image` path and hex `color`. Optional: `badge`, `compare_price` (greater than price), `featured` boolean, `active` boolean, `specs` object. PATCH merges supplied fields with the existing product. Restore an archived product with `PATCH {"active": true}`. Only bundled local image files are accepted; arbitrary uploads and URLs are not supported.

Order transitions:

| Current | Allowed next status |
| --- | --- |
| Confirmed | Processing, Cancelled |
| Processing | Shipped, Cancelled |
| Shipped | Delivered |
| Delivered | None |
| Cancelled | None |

Cancellation restores stock only once. Archived products still retain the stock needed for order history/cancellation accounting.

## Errors and HTTP behaviour

```json
{
  "error": {
    "message": "Enter a valid email address.",
    "fields": {"email": "Use an email such as name@example.com."}
  }
}
```

| Status | Meaning |
| --- | --- |
| 200 | Successful read/update/delete; also repeated checkout key. |
| 201 | Successful resource creation. |
| 400 | Invalid/missing fields or malformed JSON. |
| 401 | Sign-in required or incorrect credentials. |
| 403 | Invalid CSRF token, disallowed Origin or administrator permission required. |
| 404 | Unknown API/resource; another customer's private address/order is treated as missing. |
| 405 | Known API path with unsupported HTTP method. |
| 409 | Duplicate account/product slug, stock conflict, empty checkout or invalid order transition. |
| 413 | Request body exceeds 64 KiB. |
| 415 | Non-empty write body is not application/json. |
| 429 | Authentication or support rate limit. |
| 500 | Unexpected server error; a generic message is returned to the browser. |

Unknown page paths return an actual 404 with the branded missing-page view. Initial requests to a missing/archived product page also return 404. SPA navigation fetches the product API and renders its 404 message without a document reload. GET and HEAD are supported for pages/static files. Other methods do not serve page content. APIs are same-origin; no CORS allowlist is enabled.
