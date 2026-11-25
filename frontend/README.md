# Tradeo frontend

Tradeo is a simulated Indian trading workspace. The dashboard includes a fixed, dated sample portfolio, market indices and recent trades. Markets offers searchable NSE instruments, candlestick charts and a browser-local watchlist. Auto Trading previews paper automation and risk controls. Brokers previews account connection and sync workflows. Strategies previews a strategy library, a draft editor and version history. Backtesting previews a replay queue, holdout results and CSV exports. Agents previews observer health and advisory review. Upcoming modules have labeled placeholder pages.

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

In **Auto Trading**, assign a strategy while the paper engine is idle. Start or pause the simulator, review risk approvals in the order queue, and inspect sample trades and the event log. The paper kill switch requires typing **STOP**. It halts the simulator, cancels pending paper orders and records an event. Clearing a halt returns the simulator to idle. Demo state lives in memory for the current page visit and resets on reload. Live trading is unavailable.

The [proposed paper automation contract](../contracts/auto-trading.openapi.yaml) documents the mock snapshot and commands. A backend integration would require authenticated sessions, server-side risk checks and durable append-only audit records.

In **Brokers**, filter Zerodha and Fyers by connection status, check masked account details, and try connect, reconnect, sync or disconnect. The demo clock advances with each action, and the activity log stays available after disconnect. State lives in memory for the current page visit. The [proposed broker preview contract](../contracts/brokers.openapi.yaml) documents the demo adapter. Real integrations require provider authorization, secure server-side token storage and separate backend work.

In **Strategies**, search by name or instrument, filter by status or risk, and switch between cards and a table. Open a strategy to inspect its parameters, backtest and risk checks, and immutable version history. Create and edit sample drafts, pause an active demo, or activate the prequalified HDFC Mean Reversion draft. New and edited drafts need a fresh backtest and risk review before activation. Demo edits reset when the page is reloaded. The [proposed strategy preview contract](../contracts/strategies.openapi.yaml) describes a future adapter. The preview runs no backtests and sends no orders.

In **Backtesting**, select a fixture strategy revision, instrument, date range and out-of-sample period. Set starting capital, per-fill fees and slippage, then queue a demo replay. The shared three-session trend rule uses completed daily candles, the selected revision's position size, and subsequent session opens for fills. Review equity, drawdown, performance metrics and closed trades, or export the trades as CSV. Runs reset on reload and cannot approve strategy revisions. The [proposed backtesting preview contract](../contracts/backtesting.openapi.yaml) documents the demo workspace and run states. Production backtests require a separate engine, durable jobs, approved market history and a reviewed fill model.

In **Reports**, use either date bound to filter paper fills by inclusive IST session dates. Review realised P&L, current unrealised P&L, fees, daily activity, strategy-version attribution, and the current replay's ledger check. Select a calendar day to filter the journal. **Export period CSV** downloads every fill in the date range, including fills beyond the 500-row journal limit. Preview mode uses sample data. Staging mode reads the backend paper ledger with the signed-in session through the [Reports contract](../contracts/openapi.yaml).

In **Agents**, inspect four simulated observers, their latest decisions, reason codes, latency, and failures. Filter the timeline by observer, severity, or review status. Pause or resume an observer, or acknowledge or dismiss an advisory item. Demo actions reset on reload and never authorize orders or change risk rules. The [proposed Agents preview contract](../contracts/agents-preview.openapi.yaml) describes the fixture adapter. A backend advisory service and durable review records are separate work.

In **Alerts**, filter the demo inbox by unread status, severity or source, acknowledge sample alerts, and review channel preferences. In **Settings**, edit the demo profile and timezone, change notification preferences, or inspect the sample phone, sessions, retention and risk limits. Sensitive demo actions prompt for the code shown in the dialog and appear in the settings audit trail. The workspace shares demo changes across both routes until reload. Theme remains a browser preference. No email or SMS is sent. The [proposed Alerts and Settings contract](../contracts/workspace-controls-preview.openapi.yaml) documents the typed demo adapter.

In staging mode, **Alerts** reads the signed-in account inbox and unread counts from the backend. Its filters and pagination use the server cursor. Acknowledgement and optional warning and info preferences are saved for the account. Critical in-app alerts stay on. Email, SMS and push are shown as unavailable. The staging Settings notification card links to these account preferences.

## Verification

```sh
npm run lint
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Playwright runs the production build at `127.0.0.1:3100`. Run the build before the smoke tests. Set `TRADEO_CAPTURE_SCREENSHOTS=1` for the Playwright command to save screenshots, including Alerts and Settings, in the ignored `screenshots/` directory.

Vitest covers preview validation, API responses, search ranking, candle aggregation and watchlist storage. React Testing Library covers dashboard and Markets interactions. Playwright covers sign-in, sign-out, protected routes, themes, navigation, instrument search, all six chart timeframes, watchlist persistence, demo state recovery and responsive layouts.

## Source layout

- `src/app/` holds Next.js App Router routes, the preview sign-in action and protected workspace layout.
- `src/components/ui/` holds locally owned shadcn/ui-style primitives built on Radix where needed. Theme and typography tokens live in `src/app/globals.css`.
- `src/lib/api/client.ts` is the single typed client factory. Market DTOs live in `src/lib/api/market-types.ts` and match the proposed [Markets OpenAPI contract](../contracts/openapi.yaml). The current implementation serves in-memory fixtures. An adapter can map a future generated client's responses and errors to the same interface.
- `public/brand/` contains the provided approved Tradeo raster logo. The UI presents the supplied image in a CSS viewport to trim surrounding padding.

The preview contains only fixture records. Backend authentication requires staging mode. Broker connections, order execution, live market feeds and AI trading are outside the preview scope.

The portfolio and Markets charts use [TradingView Lightweight Charts™](https://www.tradingview.com/lightweight-charts/). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the attribution.

## Private staging sign-in

The local default is `TRADEO_AUTH_MODE=preview`. To use the [backend auth contract](../contracts/openapi.yaml) from a private staging deployment, configure these variables in the Next.js server environment:

```dotenv
TRADEO_AUTH_MODE=staging
TRADEO_API_ORIGIN=https://tradeo-api.example.internal
TRADEO_PUBLIC_ORIGIN=https://tradeo-staging.example.internal
```

Use a private HTTPS API origin with a certificate trusted by Next.js. Use the staging visitor URL for `TRADEO_PUBLIC_ORIGIN` and configure the backend `PUBLIC_ORIGIN` to match it exactly. Add the API origin's host to the backend host allowlist. Plain HTTP is accepted only on loopback for local development and testing.

Place Next.js behind a trusted ingress and restrict direct network access to Next.js and FastAPI. Provision the same server-only `TRADEO_AUTH_INGRESS_TOKEN` for the ingress and Next.js from a secret store. Use at least 32 random bytes encoded as base64url. Apply both headers to `/api/v1/auth/*` at the ingress:

- `X-Tradeo-Client-IP` carries one IP address derived from the connection peer or a trusted load balancer. Overwrite any inbound value.
- `X-Tradeo-Ingress-Token` carries the configured token. Overwrite any inbound value and keep it out of responses and logs.

Next.js verifies those headers and sends the verified address as a single `X-Forwarded-For` value without the ingress token. Set `TRUSTED_PROXY_HOPS=1` in the backend and preserve that single value through any private API TLS terminator. This keeps the backend's per-client rate limits separate. The browser uses the same-origin auth routes and receives the backend's Secure, HttpOnly cookies. Next.js validates the backend session before serving workspace pages.

Staging requires the email-only backend contract. Enter the email address on the invite. On first sign-in, use the verification code, then scan the locally rendered QR code or enter the setup key in an authenticator app. Confirm the current six-digit code and save the recovery codes shown once. On later visits, enter the same email and an authenticator code, or use a one-time recovery code to set up a replacement authenticator. Private staging uses the configured test-code provider or SMTP. Local preview keeps its simulated phone and code flow.

After building the frontend, run `npm run test:e2e:staging`. The local ingress fixture listens on `127.0.0.1:3101`, the API fixture on `127.0.0.1:3102`, and the production frontend build on `127.0.0.1:3103`. The suite exercises auth, browser cookies, rate-limit isolation, and signed-in paper reports and CSV export without contacting staging or sending SMS.
