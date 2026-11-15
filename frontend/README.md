# Grocy Assistant front end

Svelte 5 + TypeScript + Vite, shipped as an installable PWA (`vite-plugin-pwa`).

```sh
npm install
npm run dev      # http://127.0.0.1:5173, proxies /api to the backend
npm run check    # svelte-check, warnings are errors
npm run build    # outputs dist/, which the backend serves
```

The dev server proxies `/api` to `http://127.0.0.1:8765`; set `GA_BACKEND` to point
it elsewhere. Camera scanning needs a secure origin, which `127.0.0.1` counts as.

- `src/lib/` has the typed API client (`api.ts`, `types.ts` mirror
  `backend/app/schemas.py`), the router, and the barcode scanner. The scanner uses
  the browser's `BarcodeDetector` when present and otherwise a bundled zxing-wasm
  build; nothing is fetched from a CDN at runtime.
- `src/trip/` is the three-step trip flow: `scan/`, `receipts/`, `review/`.
- `src/routes/` holds the remaining screens: sign-in, the trip list and settings.
  People sign in with their Grocy username and password (or a Grocy API key);
  the app has no accounts of its own, so there is no setup, registration or
  user management here. `src/settings/` has the pieces of the settings page:
  the Grocy connection check, and one AI form used for both a person's own
  settings and the household default that admins set.

Icons are generated from the SVG sources in `icons/` into `public/` with
`npm run icons`. The service worker precaches the app shell only; `/api/*` is
never cached.

When dependencies change, regenerate the lockfile with the same Node image the
Dockerfile builds with, otherwise `npm ci` in the image build can reject it:

```sh
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/web -w /web \
  node:24-slim npm install --package-lock-only
```
