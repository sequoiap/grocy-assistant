# Grocy Assistant

A self-hosted companion app for [Grocy](https://grocy.info) that takes the tedium
out of logging purchases. Instead of entering every product on Grocy's Purchase
page one at a time:

1. **Scan** the barcode of each thing you bought, once.
2. **Snap** a photo of the receipt (or several, if you went to several stores).
3. **Review** one screen and tap **Add to Grocy**.

Quantities, prices, the store and due dates are filled in from the receipt and
from each product's defaults in Grocy. It is an installable PWA, so it works in a
desktop browser and as a home-screen app on a phone.

## How it works

- **Scanning** uses the phone camera (or a USB/Bluetooth barcode scanner, or typed
  codes). Barcodes Grocy already knows resolve instantly. Unknown ones are looked up
  in the Open Food Facts family of databases, and in the review step you either
  confirm a new Grocy product with the suggested name or link the barcode to a
  product you already have. Grocycode labels (`grcy:p:…`) work too.
- **Receipts** are read on your server by a built-in OCR engine (RapidOCR, models
  bundled, no internet needed) with dedicated parsers for Walmart, Costco and the
  Kroger family (Kroger, Smith's, Fred Meyer, Ralphs, …) plus a generic fallback.
  Each read gets a confidence score, mostly based on whether the item prices add up
  to the printed subtotal.
- **Matching** pairs receipt lines with what you scanned: by the UPC printed on the
  receipt (Walmart), by what it learned on earlier trips, and by abbreviation-aware
  name matching ("GV WHL MLK" ↔ "Great Value Whole Milk"). Whatever you confirm is
  remembered per store, so the second trip needs less attention than the first.
  Receipt lines for things without a barcode (produce, deli) can be turned into
  items directly, and are recognized automatically from then on.
- **AI assist is optional.** With a provider configured (Anthropic, or any
  OpenAI-compatible endpoint such as OpenAI, OpenRouter, Ollama or LM Studio), it
  is consulted only when the built-in reader is unsure, or when you tap
  "re-read with AI". A Grocy admin can set a household default under *Settings*,
  and anyone can set their own provider and key instead, which then applies to
  their receipts. Without a provider everything still works.
- **Phone as the scanner for your computer.** Open a trip on the computer, choose
  *Use phone as scanner*, and scan the QR code it shows with your phone (the phone's
  camera app, or *Join a trip* inside the installed app). Both devices then show the
  same trip live: barcodes and receipt photos taken on the phone appear on the
  computer within a couple of seconds, where reviewing is more comfortable. Trips are
  shared by the household, so two people can also work on one trip at once.
- **Submitting** books each item through Grocy's REST API under the API key of the
  person who taps the button, so Grocy's journal shows who logged what. A submitted
  trip can be undone, which reverses its stock bookings in Grocy.
- **When Grocy is down** the app keeps working from its last copy of your products:
  scanning, editing trips and reading receipts carry on, and the trip waits until
  Grocy is back to be submitted.

### Accounts

There are none to manage: **people sign in with their Grocy username and
password.** On the first sign-in the app creates an API key for that person in
Grocy (it shows up under *Manage API keys* as "Grocy Assistant"), keeps it
encrypted, and discards the password. Whoever is an admin in Grocy is an admin
here, which only matters for the household AI settings. While someone has the
app open, it re-checks their Grocy key every few seconds, so deleting a Grocy
user signs them out on all their devices within about half a minute.

If your Grocy doesn't use its own login form (LDAP or reverse-proxy
authentication), choose *Use a Grocy API key instead* on the sign-in screen and
paste a key from Grocy's wrench menu → *Manage API keys* → *Add*.

## Running it

You need Docker and a reachable Grocy (4.x; developed against 4.7).

Phones only allow camera access over **HTTPS**, so the app is meant to sit behind
something that terminates TLS. The app itself serves plain HTTP on port 8080.
Pick whichever fits:

| Setup | Use |
| --- | --- |
| You already run a reverse proxy | `docker compose up -d --build`, then proxy to port 8080 |
| Caddy with automatic certificates | [`deploy/caddy`](deploy/caddy/docker-compose.yml) |
| Private HTTPS on your tailnet | [`deploy/tailscale`](deploy/tailscale/docker-compose.yml) |

Each compose file has its steps in the comments at the top. The one thing you
must set is **`GA_GROCY_URL`**, the address of your Grocy as seen from inside the
container (so not `localhost`, unless Grocy shares the container's network). Put
it in a `.env` file next to the compose file; see [`.env.example`](.env.example).
Then open the app and sign in with your Grocy account. On a phone, use the
browser's *Add to Home Screen* to install it.

The Grocy address is deliberately not editable from the app: people type their
Grocy password into it, so where that password is sent should only be changeable
by whoever controls the server.

Data (trips, receipt photos, what the matcher has learned) lives in the
`grocy_assistant_data` volume. Stored Grocy and AI keys are encrypted with a key
kept in that same volume, or with `GA_SECRET_KEY` if you set one.

### Configuration

The AI provider is set in the app under *Settings*. Everything else is an
environment variable:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GA_GROCY_URL` | **required** | Address of your Grocy; the app won't start without it |
| `GA_SECRET_KEY` | generated | Encrypts stored API keys |
| `GA_DATA_DIR` | `/data` | Where the database and receipt photos live |
| `GA_OCR_CONFIDENCE_THRESHOLD` | `0.6` | Below this, the AI fallback is consulted |
| `GA_MAX_UPLOAD_MB` | `25` | Per-photo upload limit |
| `GA_SESSION_DAYS` | `90` | How long a sign-in lasts |
| `GA_KEY_CHECK_SECONDS` | `15` | How often the Grocy key of each person using the app is re-checked (`0` turns it off) |

## Development

```sh
# backend (Python 3.12, uv)
cd backend
uv sync
GA_GROCY_URL=http://localhost:9283 uv run uvicorn app.main:app --port 8765 --reload
uv run pytest                 # add -m "not slow" to skip the tests that run real OCR
uv run ruff check app tests

# front end (see frontend/README.md)
cd frontend
npm install
npm run dev
```

`uv run python -m app.receipts photo.jpg` prints how a receipt photo was read, row
by row, which is the quickest way to see why one misparsed. API docs are at
`/api/docs`; `backend/app/schemas.py` is the contract the front end is built on.

```
backend/app/
  routers/      HTTP API (auth, settings, trips, Grocy metadata)
  services/     matching, trip resolution, receipt processing, submit/undo
  receipts/     OCR, row reconstruction, store parsers, confidence scoring
  ai/           optional providers (Anthropic, OpenAI-compatible)
  grocy/        Grocy REST client and the sign-in exchange
frontend/src/   the PWA
deploy/         Caddy and Tailscale compose examples
```

## Status and known limits

- The receipt parsers are tested against realistic receipt text and rendered
  receipt images, not yet against a collection of real photos from each store.
  Expect to tune them; the debug command above and the *raw text* kept with every
  receipt are there for that.
- The AI providers are covered by tests against mocked APIs only.
- The Tailscale compose example has not been run against a real tailnet.
- Signing in creates the person's API key through a page of Grocy's web interface
  rather than its documented API (which has no way to do it). It works on Grocy
  4.7; if a later Grocy changes that page, signing in with a pasted API key still
  works.
- The phone needs a connection to the app's server to scan; there is no offline
  queue on the phone. (Grocy itself being down is fine, see above.)
- A phone joining a trip signs in with a Grocy account (once; sign-ins last 90
  days). Pairing by QR code without signing in is not built yet.
- Upgrading from a version with the app's own accounts starts a fresh database;
  the old one is kept next to it as `grocy-assistant.db.pre-grocy-login.bak`.
- Items sold by weight are booked as quantity 1 unless the product's stock unit in
  Grocy is that weight unit (lb, kg, …), in which case the weight is used.
