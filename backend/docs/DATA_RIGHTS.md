# Market data rights and provider matrix

Jira: TRAD-10 (E02). Builds on `backend/docs/ENGINES.md` **1.0.0** (Market Data engine,
`app/market`, `MarketDataProvider`). Docs only: no provider is signed up for, no money is
spent, no credentials are used. Demo, sandbox and paper scope is unchanged.

Sources were read on **2026-11-26**. Prices and terms change; re-check each link before a
decision that depends on it. Labels used below:

- **Fact**: stated on the cited official page on the read date.
- **Inference**: my reading of a stated term. Not legal advice.
- **Estimate**: a derived number.
- **Opinion**: a recommendation.
- **Unknown**: not stated on any page read. Needs a written answer from the provider.

## 1. Summary

1. **The pilot feed is not named anywhere in the repo or Jira.** (Fact: searched
   `backend/docs`, the Development Kit and TRAD issues.) The broker set in code is Zerodha and
   Fyers (`app/brokers/adapter.py`). This doc assumes the owner-only pilot uses the owner's own
   account at one of those brokers and recommends Zerodha Kite Connect (section 4).
2. **Both broker APIs restrict paper or virtual trading use of their live data.** Kite terms
   2(a) bar use of "the APIs and/or live market data for virtual/mock trading apps"; Fyers terms
   section 11 bar exchange data for "paper trading" and "virtual trading purposes". TrueData
   lists virtual and simulated trading as prohibited too. (Fact.) Tradeo's T38 feeds a live feed
   into the paper engine. **Owner decision (2026-11-26):** Tradeo is a personal tool for the
   owner's own algo trading, which the Kite terms allow ("personal use ... customising personal
   trading"). The owner accepts the residual risk of these clauses and does not need written
   confirmation from the provider. T38 is not blocked on data rights.
3. **NSE MCP is research-only.** NSE states the data is "for information and learning. It is not
   meant for real-time trading, investment advice or commercial products", and that access grants
   no right to "train or fine-tune any AI systems". (Fact.) It is delayed 1 to 3 minutes and
   end-of-day history only. It must not feed Paper, Risk, Execution, or E12/E13 model training.
4. **Exchange non-display licensing is an open question.** NSE's Non-Display Policy covers use of
   market data "as part of automated calculations or algorithms to support trading decision
   making", with fees paid to NSE Data & Analytics (from ₹23.9 lakh a year for Capital Market
   L1, enterprise, effective 1 April 2026). (Fact.) Whether an individual client receiving data
   through a broker API is a "Subscriber" under that policy is **Unknown**; ask NSE Data
   (`marketdata@nse.co.in`) or the broker in writing before any automated use beyond paper.
5. **Storing provider data is restricted.** Kite terms 4(b) and Fyers terms section 12 restrict
   building databases or permanent copies of API content without the provider's permission.
   (Fact.) This affects backtest candle storage and the E12 historical dataset gate. (Inference.)

## 2. Provider matrix

Costs exclude GST unless noted. "Live" means streamed during market hours.

| Provider | Type | Cost (Fact) | Live data (Fact) | Intraday history (Fact) | Permitted use (Fact) | Fit for owner-only pilot (Opinion) |
|---|---|---|---|---|---|---|
| **Zerodha Kite Connect** | Broker API | Personal: free, no market data. Connect: ₹500 per month per API key, includes WebSocket and historical candles. Cut from ₹2,000 in May 2025. | WebSocket: 3,000 instruments per connection, 3 connections per key; modes ltp, quote, full (5-level depth). | Minute to 60-minute candles "spanning back several years"; continuous daily data for expired NFO/MCX futures; no expired option tokens unless cached. | Personal use only; credentials for the account holder only; no display "to the public at large"; no virtual/mock trading apps; not for fully automated trades; no databases or permanent copies of API content without permission; India only. | **Recommended**, subject to the written confirmation in section 5. |
| **Fyers API v3** | Broker API | Standard: free. Prime: price not published on the plans page. | Data socket: 100 symbols (Standard), 5,000 (Prime), per user across connections; tick-by-tick: 1 symbol (Standard). | Standard: intraday 1 year, daily 5 years, no seconds data. Prime: intraday 5+ years. | Personal use; credentials for the client only; no third-party use; exchange data not for charting tools, paper trading or virtual trading; copies and public display need written consent. | Fallback. Free, but 100 symbols and 1 year intraday on Standard, and the same paper-trading restriction. |
| **Dhan DhanHQ Data API** | Broker API | ₹499 + taxes per month; free-with-trades offer discontinued. | 5,000 instruments per connection, 5 connections; **not tick-by-tick**, second-by-second snapshots. | Intraday 1/5/15/25(sic)/60-minute for last 5 years; daily from inception. | **Unknown**: no permitted-use terms found on the pages read. | Not recommended until terms are read. Not in Tradeo's broker set. |
| **Upstox API** | Broker API | Base API described as free (community reply, 2024, stale). Upstox Plus price not published. | V3 feed: 2 connections per user; Full mode 2,000 instruments, LTPC 5,000. Plus: 5 connections. | Not stated on pages read. Expired-instrument history is Upstox Plus only. | **Unknown**: no terms found on the pages read. | Not recommended until terms and pricing are read. Not in Tradeo's broker set. |
| **TrueData** | NSE authorised vendor | API pricing not published; needs a "separate application, compliance review, and approval". Desktop Velocity plans ₹1,440 to ₹3,299 per month (page is internally inconsistent), exchange fees stated as included. | L1 at 1-second frequency per product page; tick add-ons. | 1-minute and 5-minute candles, EOD, tick add-on (5 to 20 days); depth not stated. | Individual or internal use; algo integration into internal systems allowed; no redistribution or public display without written approval; virtual and simulated trading listed as prohibited. | Option if a broker-independent licensed source is required (T34). Cost unknown. |
| **NSE MCP** | Exchange, free | Free, no registration. | None. "Near real time delayed by 1-3 minutes"; no tick or order book. | None. EOD for 3,500+ equities, last 5 years; up to 3 months per request; prices not split-adjusted. | "Information and learning"; not for real-time trading, investment advice or commercial products; no AI training or fine-tuning. | **Research only.** Never an input to Paper, Risk, Execution or model training. |
| **NSE direct licence** | Exchange | Data vendor real-time CM L1: ₹25.5 lakh a year fixed plus ₹1,145 per user per month. Non-display CM L1 enterprise: ₹23.9 lakh a year. Both effective 1 April 2026. | Leased line or via authorised vendors. | Separate historical products. | Commercial use needs an agreement with NSE Data; no redistribution except as agreed. | Out of scope for an owner-only pilot (cost). Relevant only for a commercial product. |
| **Unofficial wrappers** (for example `nse-mcp` on PyPI, built on `jugaad-data`) | Third-party scrapers of public NSE endpoints | Free | Delayed or unavailable, rate-limited by NSE | Daily only | Publisher says "For research and personal use"; no licence found. | **Not permitted** for any Tradeo engine. |

**Authorised vendor check** (Fact): NSE's authorised real-time vendor list includes "TrueData
Financial Information Private Ltd". "Global Datafeeds" has no exact match; the nearest entry is
"Global Financial Datafeeds LLP". Confirm with NSE before relying on that vendor.

## 3. Use classes and what each needs

Each Tradeo use maps to a data-rights requirement. "Allowed source" is an **Opinion** built on
the terms above.

| Use | Engine (ENGINES.md 1.0.0) | Allowed source today | Condition |
|---|---|---|---|
| Demo screens and tests | 1 Market Data (demo provider) | Synthetic fixtures only | None. Every response stays `source: demo`. |
| Research notes, ad-hoc exploration by the owner | none | NSE MCP, broker API | Not stored in Tradeo tables; not shown to other users. |
| Owner-only live quote display | 1 Market Data | Kite Connect (or Fyers) on the owner's own account | Owner is the only user; no other account sees the data. |
| Paper trading on live data (T38) | 6 Paper Trading | Kite Connect | Owner-only, under the owner's accepted-risk decision (section 8). |
| Stored candles for backtests | 5 Backtesting | Kite Connect | Owner-only, never shared or shown to others; under the same decision. |
| Historical training data (E12, E13) | 3 Market Intelligence | Kite Connect | Owner-only models for the owner's own trading, under the same decision. NSE MCP stays excluded (NSE bars AI training). E12 still checks coverage and gaps. |
| Risk freshness checks | 7 Risk | Same feed as the caller's snapshot | Risk only reads `asOf` stamps; it never calls Market Data. |
| Live orders | 8 Execution | Out of scope | Gate G9, E21 and separate owner approval. Kite and Fyers terms also say the APIs are not for fully automated trades. |
| Any second user, public page or commercial product | all | **None** | Exchange-authorised vendor agreement and, for NSE, a licence. |

## 4. Pilot feed decision (approved 2026-11-26)

The owner approved the recommendation below (section 8). The reasoning stays as written.

**Zerodha Kite Connect, ₹500 per month, on the owner's own account, read-only data use.**

Criteria and trade-offs:

- **Already in scope.** Zerodha is one of the two brokers in `app/brokers`. Fyers is the other.
- **Coverage.** 3,000 instruments per connection and minute history over several years cover
  Nifty 50 cash plus index futures for the 9:30 and 9:45 IST decision points in E03. Fyers
  Standard allows only 100 streamed symbols and 1 year of intraday history.
- **Cost.** ₹6,000 a year (Estimate: ₹500 x 12, before GST). Fyers Standard is free; Dhan is
  ₹499 a month; TrueData API is unpublished.
- **Same blockers as the alternatives.** The paper-trading and storage clauses apply to Kite and
  Fyers alike, and TrueData lists simulated trading as prohibited too. Choosing Kite does not
  remove the need for section 5.
- **Engine boundary.** T34 requires the market source to be "independent of execution broker".
  Under ENGINES.md this means a `MarketDataProvider` implementation in `app/market`, separate
  from `BrokerAdapter` in `app/brokers`, even when both talk to Zerodha. (Inference.) If the owner
  reads T34 as "a different company", TrueData is the candidate and its API price must be quoted
  first.

Not decided here: signing up, paying, or creating an API key. Those are owner actions.

## 5. Optional questions for the provider

**Not required.** The owner decided on 2026-11-26 not to send these (section 8). They are kept
for reference if Tradeo ever gains a second user. Send to the chosen provider (Kite: `kiteconnect@zerodha.com`, which Zerodha staff named on the Kite forum
for compliance questions) and keep the reply as the approval record for TRAD-10.

1. May live data from my own account be used in a private, single-user paper trading simulator
   that places no orders? (Kite terms 2(a) "virtual/mock trading apps"; Fyers section 11.)
2. May I store historical candles fetched through the API in a private database for my own
   backtesting and model research, and for how long? (Kite 4(b); Fyers 12.)
3. Does my use as an individual client require a separate NSE non-display licence, or is it
   covered by the broker's arrangements? (NSE Non-Display Policy 1.3, 3.1.)
4. Does a private app with one user and no public access count as "display to the public"?

## 6. Sources

Zerodha
- Charges: https://support.zerodha.com/category/trading-and-markets/kite-api/articles/what-are-the-charges-for-kite-apis
- Data plan: https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/historical-data-and-live-market-data-payment-plan
- FAQ: https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs
- Product: https://zerodha.com/products/api
- Price change (May 2025): https://kite.trade/forum/discussion/15015/revising-kite-connect-fees-from-2000-to-500-per-month
- Terms: https://kite.trade/terms/
- WebSocket limits: https://kite.trade/docs/connect/v3/websocket/
- Historical: https://kite.trade/docs/connect/v3/historical/
- Rate limits (quote 1/s, historical 3/s, others 10/s): https://kite.trade/docs/connect/v3/exceptions/

Fyers
- Plans and limits (updated 14 October 2026): https://fyers.in/api-docs/v3/getting-started/plans-and-limits/
- FAQ: https://support.fyers.in/portal/en/kb/fyers-api-integrations/fyers-api/general
- Terms: https://fyers.in/terms-and-conditions-api

Dhan
- Subscription: https://dhan.co/support/platforms/dhanhq-api/how-does-the-dhanhq-data-api-subscription-work/
- Offer ended: https://dhan.co/support/platforms/dhanhq-api/is-the-dhanhq-data-api-subscription-free-if-i-execute-a-minimum-number-of-trades-every-month/
- Rate limits: https://dhan.co/support/platforms/dhanhq-api/what-are-the-api-rate-limits-for-dhan/
- Feed capacity: https://dhan.co/support/platforms/dhanhq-api/how-many-instruments-can-i-track-using-dhan-s-live-market-feed/
- History: https://dhan.co/support/platforms/dhanhq-api/what-timeframe-data-is-available-through-dhan-s-historical-data-apis/
- Not tick-by-tick: https://dhan.co/support/platforms/dhanhq-api/does-dhan-websockets-and-api-s-provide-tick-by-tick-market-data/

Upstox
- Market data feed V3: https://upstox.com/developer/api-documentation/v3/get-market-data-feed
- Announcements: https://upstox.com/developer/api-documentation/announcements
- Rate limits: https://upstox.com/developer/api-documentation/rate-limiting
- Pricing reply (2024, stale): https://community.upstox.com/t/developer-api-pricing/3796

TrueData
- API terms: https://truedata.in/market-data-apis
- Product: https://www.truedata.in/products/marketdataapi
- Prices (Velocity, not API): https://www.truedata.in/price
- About: https://www.truedata.in/about_us

NSE
- NSE MCP: https://www.nseindia.com/nse-mcp (served from https://www.nseindia.in/nse-mcp)
- Data policy: https://www.nseindia.com/market-data/nse-data-policy
- Data sharing and usage policy: https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing%26Usage_Policy.pdf
- Non-display policy: https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Non_Display_Policy.pdf
- Pricing, domestic, effective 1 April 2026: https://nsearchives.nseindia.com//web/mediaattachment/2026-03/NSE_Pricing_file_-_Domestic_clients_20260309171343.pdf
- Authorised real-time vendors: https://nsearchives.nseindia.com/web/sites/default/files/inline-files/AUTHORISED%20REALTIME%20DATA%20VENDORS.pdf
- Unofficial wrapper example: https://pypi.org/project/nse-mcp/

## 7. Known gaps in this review

- Kite pages disagree on the 2026 Developer Credits rule (₹500 brokerage from November 2026 vs
  ₹2,000 from October 2026). It does not change the ₹500 list price.
- Not read: Dhan and Upstox API terms, Upstox historical depth, TrueData API price list, NSE
  website Terms of Use. Parts of the NSE policy page and Dhan pages were read via summary of a
  truncated page; the PDF clauses quoted above were read directly.
- Owner approved the Kite Connect feed and its cost on 2026-11-26 and chose not to seek written
  answers to section 5 (section 8).
- Still relevant at any live-order step (gate G9, E21): Kite terms 2(e) say the APIs are "not
  meant for placing fully automated trades (without manual intervention)", and Zerodha's FAQ says
  client algos above 10 orders per second need exchange registration.

## 8. Approval record

| Item | Status |
|---|---|
| Pilot feed choice | **Approved**: Zerodha Kite Connect. Owner (Avinash), 2026-11-26 16:38 UTC, project thread decision card |
| Cost approval | **Approved**: ₹500 per month per API key (plus GST). Same record. Sign-up and payment are owner actions |
| Provider written answers (section 5) | **Not required.** Owner decision, 2026-11-26 16:45 UTC, project thread: personal tool for the owner's own algo trading; owner accepts the residual risk. Re-open if any second user is added |
| Tested revision | Docs only; read against main `17a409d` |
