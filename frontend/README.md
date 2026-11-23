# Tradeo frontend

Phase 1 is a simulated Indian trading workspace. The dashboard includes a fixed, dated sample portfolio, market indices, an NSE watchlist and sample trades. The rest of the workspace contains labeled placeholder pages.

## Local development

Use Node.js 22.12 or newer and npm. From the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Enter the sample mobile number **98765 43210** and the preview OTP **123456**. The server sets a short-lived preview cookie to demonstrate protected routes and sign-out. The form sends no SMS and stores no mobile number in the cookie. The theme preference is saved locally in the browser.

The development and production build scripts use Next.js’s Webpack mode because Turbopack could not start its PostCSS worker on the Windows development host.

Use **Preview data** on the dashboard to switch between the normal, stale, empty and error responses. Applying a scenario or refreshing data briefly shows the loading state. The **Sample snapshot** date identifies the fixture in use.

## Verification

```sh
npm run lint
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Playwright runs the production build at `127.0.0.1:3100`. Run the build before the smoke tests. Set `TRADEO_CAPTURE_SCREENSHOTS=1` for the Playwright command to save desktop sign-in and desktop and mobile dashboard screenshots in the ignored `screenshots/` directory.

Vitest covers mobile number validation, INR formatting and the mock client. React Testing Library covers dashboard loading, chart range selection, simulated data states, recovery and notifications. Playwright covers preview sign-in and sign-out, protected routes, both themes, all placeholder routes, sample data and responsive navigation.

## Source layout

- `src/app/` holds Next.js App Router routes, the preview sign-in action and protected workspace layout.
- `src/components/ui/` holds locally owned shadcn/ui-style primitives built on Radix where needed. Theme and typography tokens live in `src/app/globals.css`.
- `src/lib/api/types.ts` defines the DTOs and `TradeoClient` interface. `src/lib/api/client.ts` is the single client factory. When the backend publishes an OpenAPI contract, an adapter can call the generated client here and map its DTOs, cancellation and errors. The current implementation calls an in-memory mock and makes no backend requests.
- `public/brand/` contains the provided approved Tradeo raster logo. The UI presents the supplied image in a CSS viewport to trim surrounding padding.

The preview contains only fixture records. Real authentication, broker credentials and connections, order execution, live market feeds, and AI trading are outside Phase 1.

The sample portfolio chart uses [TradingView Lightweight Charts™](https://www.tradingview.com/lightweight-charts/). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the attribution.
