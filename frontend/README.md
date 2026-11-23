# Tradeo frontend

Tradeo is a simulated Indian trading workspace. The dashboard includes a fixed, dated sample portfolio, market indices and recent trades. Phase 2 adds a Markets page with searchable NSE instruments, candlestick charts and a browser-local watchlist. Upcoming modules have labeled placeholder pages.

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

In **Markets**, select an overview card, find an instrument by name or symbol, or choose one from the watchlist. The chart supports 1m, 5m, 15m, 30m, 1h and 1D candles. **Chart demo data** lets you exercise stale, empty and failed history requests. The session indicator is dated to the demo snapshot. Equity volumes use sample share counts. Index volume is unavailable.

## Verification

```sh
npm run lint
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Playwright runs the production build at `127.0.0.1:3100`. Run the build before the smoke tests. Set `TRADEO_CAPTURE_SCREENSHOTS=1` for the Playwright command to save sign-in, dashboard and Markets screenshots in the ignored `screenshots/` directory.

Vitest covers preview validation, API responses, search ranking, candle aggregation and watchlist storage. React Testing Library covers dashboard and Markets interactions. Playwright covers sign-in, sign-out, protected routes, themes, navigation, instrument search, all six chart timeframes, watchlist persistence, demo state recovery and responsive layouts.

## Source layout

- `src/app/` holds Next.js App Router routes, the preview sign-in action and protected workspace layout.
- `src/components/ui/` holds locally owned shadcn/ui-style primitives built on Radix where needed. Theme and typography tokens live in `src/app/globals.css`.
- `src/lib/api/client.ts` is the single typed client factory. Market DTOs live in `src/lib/api/market-types.ts` and match the proposed [Markets OpenAPI contract](../contracts/openapi.yaml). The current implementation serves in-memory fixtures. An adapter can map a future generated client's responses and errors to the same interface.
- `public/brand/` contains the provided approved Tradeo raster logo. The UI presents the supplied image in a CSS viewport to trim surrounding padding.

The preview contains only fixture records. Real authentication, broker connections, order execution, live market feeds and AI trading are outside the preview scope.

The portfolio and Markets charts use [TradingView Lightweight Charts™](https://www.tradingview.com/lightweight-charts/). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the attribution.
