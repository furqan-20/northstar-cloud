# NorthStar

**Better things. Everyday.**

A complete, locally runnable shop for workspace, home and everyday essentials. Includes an original storefront, a real Python JSON backend, a persistent SQLite database and an administrator studio. This package contains the website, source and operating documentation. It does not contain the later Playwright assignment, automated test suites, test reports or deliberately introduced defects.

## Start on Ubuntu / Linux

1. Extract `NorthStar_Website.zip` using your file manager.
2. Open the extracted `northstar` folder in a terminal. It contains `server.py`.
3. Check your Python version, then start the website:

   ```bash
   python3 --version
   python3 server.py
   ```

4. Open **http://127.0.0.1:8000** in your browser.
5. Keep the terminal running. Press **Ctrl+C** in that terminal to stop the website.

**Python 3.10 or newer is required.** No pip install, npm install, virtual environment, API key, external database or internet connection is needed once Python and the ZIP are on your laptop. If Ubuntu has no Python installed, install `python3` using your system package manager first. Python is normally available on Ubuntu, but verify it with the command above.

Optional launcher:

```bash
bash start.sh
```

If port 8000 is already in use:

```bash
python3 server.py --port 8001
```

Then open **http://127.0.0.1:8001**. Do not double-click the HTML file: the Python server is needed for accounts and data.

## Windows / macOS

On Windows with Python installed, open the extracted `northstar` folder in a terminal and run `py -3 server.py`, or double-click `start.bat`. On macOS, run `python3 server.py` from that folder. Use the same local URL. If your Python installation has only a `python` command, verify that it is version 3.10 or later before using `python server.py`.

## Demo accounts

These are deliberately public, fictional local demo accounts, not real service credentials. You can also register your own customer account.

| Role | Email | Password |
| --- | --- | --- |
| Customer | `alex@northstar.local` | `NorthStar123!` |
| Administrator | `admin@northstar.local` | `NorthStarAdmin123!` |

The sign-in page has buttons to fill either demo account. Sign in as the administrator to open `/admin`; a customer cannot access the admin API. The initial customer has one saved address and one saved item. Orders and support requests start empty.

## Six main features

| Feature | Working behaviour |
| --- | --- |
| Accounts & profile | Register, sign in/out, edit name/phone, change password, maintain saved delivery addresses. |
| Product discovery | 20 seeded products across 5 categories, product details/specifications, keyword search, category and price filters, stock filter, sorting and new arrivals. |
| Saved items | Save/remove products, persistent per-account wishlist, add favourites to the bag. |
| Bag & checkout | Guest and signed-in bags, quantities/removal, promotions, server-calculated totals, delivery eligibility, address validation and cash-on-delivery checkout. Guest bags merge into the account at sign-in. |
| Orders | Order confirmation, saved item/price/address snapshots, order history, status timeline and cancellation before dispatch. Stock is reserved transactionally and restored on cancellation. |
| Customer support | Validated contact form, unique request references, account support history and admin responses with Open/Resolved status. Guests may submit a message, but need to sign in before submitting to receive replies in their account. |

## Additional features

- Admin studio: delivered revenue, order/customer counts, low-stock overview and open support counts.
- Catalogue management: create, edit, archive and restore products; change prices, stock, descriptions, badges, specifications and homepage features.
- Admin fulfilment: Confirmed → Processing → Shipped → Delivered. Cancellation is allowed before shipping.
- Promo codes, delivery progress indicator, newsletter signup storage, FAQs, three journal articles, our story, delivery/returns and policy pages.
- Responsive layouts, mobile navigation, keyboard-accessible controls, field labels, visible focus, native validation, loading states, empty states, recoverable error messages and notification toasts.
- Locally bundled fonts, product illustrations and editorial imagery: no CDN dependencies.

## A quick way to explore

1. Browse the collection; search for `lamp` or filter Workspace.
2. Add the Halo Desk Lamp to your bag. Try the `WELCOME10` offer.
3. Sign in as the customer. Your guest bag and offer remain available.
4. Use the saved Home address and choose cash on delivery. Accept the local order terms and place an order.
5. Find the order under **My orders**. It has an order number and a timeline.
6. Send a support message while signed in. Find its reference under **Support requests**.
7. Sign out, sign in as the administrator, then use **Admin studio** to update the order or reply to the request.
8. Sign back in as the customer to see the saved updates.

These steps are a product walkthrough, not an automated test suite.

## Offers and totals

- All prices are whole **Pakistani rupees (PKR)**. No separate tax is added in this shop.
- Standard delivery: **Rs. 250**. Complimentary delivery at **Rs. 8,000 or more after discount**.
- `WELCOME10`: 10% off a merchandise subtotal of at least Rs. 3,000, capped at Rs. 2,000.
- `WORKSPACE15`: 15% off a merchandise subtotal of at least Rs. 10,000, capped at Rs. 3,000.
- One offer per order. Discounts round down to a whole rupee.
- Bags do not reserve stock. The backend re-checks stock at checkout. Each product has a per-bag maximum of 20 units, limited by stock.
- Haven Scented Candle is intentionally seeded **out of stock** to represent ordinary catalogue availability. This is not an injected bug.

## What persists

The first start creates `instance/northstar.sqlite3` and seeds the catalogue/accounts automatically. All later changes persist there across restarts. Back up the whole `instance` folder while the server is stopped. It contains local account and order data, so do not commit or publicly share it.

To return to the original starting state, stop the server and run:

```bash
python3 reset_data.py
```

Type `RESET` when prompted. The previous data is preserved in a timestamped sibling backup folder before a fresh database is created. This operation resets accounts, passwords, stock, carts, orders and support requests. Do not run it while a server is using that database.

An optional `NORTHSTAR_DATA_DIR` environment variable can select a different data folder. See `docs/ARCHITECTURE.md`.

## Scope and honest limitations

This is a fully functional **local demonstration shop**, not a connected trading business. Orders are saved records. No real money is charged, no goods are dispatched and no email is sent. Cash on delivery is the only payment method. Newsletter signups are stored for an administrator to use outside the app; this package has no mailing provider. Return requests go through support. Password changes work from a signed-in account; email-based password recovery and automated account deletion are not implemented.

The standard-library HTTP server is designed for a local laptop/demo, not direct public internet hosting. It binds to `127.0.0.1` by default. Public deployment would require production hosting, HTTPS, private credentials instead of the demo accounts, backups and operational hardening. No production deployment is included.

The later cross-browser Playwright execution and bug demonstration remain a separate task. Development verification is not a claim that the assignment’s formal test coverage has been completed.

## Files

- `server.py`: local HTTP server, session handling, JSON API and business rules.
- `database.py`: SQLite schema, password hashing and first-run initialization.
- `catalog.py`: original catalogue seed data.
- `templates/index.html`: common storefront shell.
- `static/js/app.js`: route rendering and all browser interactions.
- `static/css/style.css`: design system and responsive styles.
- `static/images/`: bundled product illustrations and editorial image.
- `static/fonts/`: bundled typefaces.
- `build_assets.py`: optional rebuild of the original SVG product artwork. Not required to run.
- `start.sh`, `start.bat`: launchers.
- `reset_data.py`: backup-and-reset helper.
- `docs/API.md`: API contracts, request formats and response/status rules.
- `docs/ARCHITECTURE.md`: application and persistence notes.
- `docs/ASSETS.md`, `docs/FONT-LICENSE.txt`: asset provenance and font licensing.

`requirements.txt` intentionally lists no external dependencies. `package.json` is optional preview-runner metadata; it does not make Node a runtime requirement. No `node_modules` or virtual environment is needed.

## Troubleshooting

- **Connection refused:** keep `python3 server.py` running, check its printed port and use the matching URL.
- **Port already in use:** stop the older process or pass `--port 8001`.
- **Blank/stale page after source changes:** refresh with Ctrl+Shift+R. Opening local HTML via `file://` will not work.
- **“Session has expired”:** refresh the page and retry; session/CSRF tokens are browser-specific.
- **Sign-in temporarily blocked:** eight failed attempts for an email from the same client trigger a 15-minute limit.
- **Cannot write database:** extract into a folder you can write to, rather than running inside the ZIP or a protected system folder.
- **Use one address consistently:** `localhost` and `127.0.0.1` have different browser cookie stores. Keep using `127.0.0.1` during a session.

Original application source is provided under the MIT licence in `LICENSE`. Fonts have their own bundled licence.
