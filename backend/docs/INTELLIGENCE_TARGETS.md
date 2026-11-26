# Market Intelligence: decision points, prediction targets, regimes and abstention

Jira: TRAD-9 (E03). Version **0.1.0 (draft)**, 2026-11-26. Builds against
[ENGINES.md](ENGINES.md) **1.0.0 (frozen)**. Engine 3, Market Intelligence (lead:
Claude Quant). Downstream users: E05 feature and score engine, E06 regime filter,
E07 historical replay, E16 conformance and leakage tests.

Labels used below: **Fact** is true of the code on main `17a409d` or of a cited
source. **Proposal** is a rule for review; every number in a Proposal is a
starting value the owner can change. Nothing here adds an order path. A
prediction is advisory input to Strategy Research and Paper Trading; Risk
Management still decides independently (ENGINES.md rule 4).

## 1. Scope

| In scope (this document) | Out of scope |
|---|---|
| Decision times, horizons, label construction | Model choice and training (E05) |
| Regime definitions used at decision time | Regime-to-strategy eligibility rules (E06) |
| Rules that prevent lookahead | Cost model and replay (E07) |
| When the engine abstains, with reason codes | API shape in `contracts/openapi.yaml` (a separate contract PR, if an API exposes it) |

**Proposal, universe v1:** the three tradable indices in the catalog,
`NSE:NIFTY50`, `NSE:BANKNIFTY`, `NSE:FINNIFTY`. `NSE:INDIAVIX` is an input
feature only, never a target. Single equities are excluded from v1 because their
history needs point-in-time adjustment for splits and dividends (rule L8).

## 2. Time conventions

**Facts (code):**

- The NSE regular session is 09:15 to 15:30 IST (`app/market/demo.py`,
  `_OPEN_UTC`, `_CLOSE_UTC`; 375 one-minute bars).
- A candle's `time` is the **start** of the bar, in UTC (`MarketCandle.time`,
  `_session_minutes` appends `start + minute`). The 1m bar stamped 09:29 IST
  covers 09:29:00 to 09:29:59.999 and is complete only at 09:30:00.
- Storage is UTC; market logic is IST (ENGINES.md rule 7). IST is a fixed
  UTC+05:30 with no daylight saving, so 09:30 IST = 04:00 UTC and 09:45 IST =
  04:15 UTC.
- `MarketCandles` carries `asOf` and `freshness` (`fresh` or `stale`).

**Facts (exchange):** NSE publishes a pre-open session before 09:15 and a
market-wide circuit breaker that halts trading on large index moves. Sources:
[NSE market timings](https://www.nseindia.com/static/market-data/market-timings),
[NSE pre-open session](https://www.nseindia.com/products-services/equity-market-pre-open),
[NSE circuit breakers](https://www.nseindia.com/products/content/equities/equities/circuit_breakers.htm).
This document depends only on the 09:15 open and on a halt being observable; it
does not depend on the exact pre-open sub-timings or breaker percentages.

**Proposal, availability time.** Every input record gets an `availableAt`:

| Input | `availableAt` |
|---|---|
| 1m bar stamped `t` | `max(t + 1 min, receivedAt)` |
| Daily bar of session `S` | close of `S` (15:30 IST) or `receivedAt`, whichever is later |
| Quote snapshot | its `asOf`, or `receivedAt` if later |

`receivedAt` is when Tradeo stored the record. Live feeds stamp it on arrival.
Historical backfills have no true arrival time, so they use the bar's end plus a
fixed **publication lag of 5 seconds** (Estimate; tune from the E02 feed once it
is chosen). The cutoff test always uses `availableAt`, never the bar `time`.

**Proposal, input grace.** The last feature bar (stamped `D - 1 min`) ends exactly
at `D`, so any real arrival is a little after `D`. The engine therefore computes
at `T = D + 10 s` and accepts inputs with `availableAt <= T`, but only minute-aligned bars
that end at or before `D` (rule L2). The 10 seconds covers the 5 second backfill lag and
normal live delivery; a bar that arrives later is treated as missing. Nothing in
the grace window can carry information from after `D`, because no input observed
after `D` (a bar stamped `D` or later, or a snapshot with `asOf > D`) is ever a
feature (rule L2).

## 3. Decision points

**Proposal.** Two decision points per regular session, fixed in IST:

| Id | Decision time `D` (IST) | UTC | Input cutoff `T` | Feature bars (1m) | Publish deadline |
|---|---|---|---|---|---|
| `DP0930` | 09:30:00 | 04:00:00 | `availableAt <= 09:30:10` | stamped 09:15 to 09:29 (15 bars) | 09:31:00 |
| `DP0945` | 09:45:00 | 04:15:00 | `availableAt <= 09:45:10` | stamped 09:15 to 09:44 (30 bars) | 09:46:00 |

Why these two: the first 15 minutes form the opening range, and 09:45 gives a
second look after the opening auction noise settles. Each decision point is
evaluated independently; DP0945 may use DP0930's published output as a feature
because that output's `availableAt` (its publish time) is before 09:45.

A prediction published after its deadline is not used (abstain `LATE`, section
6). The label starts one further minute after the deadline, so a consumer has
time to act on a published prediction (section 4).

## 4. Prediction targets and labels

**Proposal.** Horizons `h` in {15, 30, 60} minutes, for each decision point,
giving six targets per instrument per session.

Price references, from 1m bars of the target instrument:

- **Entry reference** `P0` = close of the 1m bar stamped `D + 1 min`. That bar
  ends at `D + 2 min`, one full minute after the publish deadline (`D + 1 min`).
  The minute is the execution latency budget: a consumer that receives the
  prediction by the deadline can act at `P0`.
- **Exit reference** `Ph` = close of the 1m bar stamped `D + 1 min + h`.
- The return window is therefore exactly `h` minutes, from `D + 2 min` to
  `D + h + 2 min`.
- **Replays (E07) fill at `P0` or later, never earlier.** A replay that models
  slower execution moves both `P0` and `Ph` later by the same whole minutes; it
  never fills at a price whose bar ends before `D + 2 min`. The label itself does
  not change with the replay's choice.

| Decision | `P0` bar | 15m `Ph` bar | 30m `Ph` bar | 60m `Ph` bar | Last exit bar ends |
|---|---|---|---|---|---|
| DP0930 | 09:31 | 09:46 | 10:01 | 10:31 | 10:32 IST |
| DP0945 | 09:46 | 10:01 | 10:16 | 10:46 | 10:47 IST |

A label is **final** only when every bar it needs has `availableAt` at or before
that time: the last exit bar's end for a live feed that delivered on time, or that
end plus 5 seconds for a backfill (so 10:32:05 and 10:47:05 IST for the 60m
labels above). A label is never read before it is final.

If a needed bar has not arrived by `W` after the last exit bar's end, the label
becomes final as `INVALID` (proposal: `W` = 15 minutes; the value is an open
policy choice for E07). A bar that arrives after that is stored as a late record
with its own `receivedAt` (rule L7) and does not change the final label. It is
counted in the data-quality report, and only an explicit, versioned relabel run
may use it.

All windows end well before 15:30, so no label crosses a session.

Labels per (instrument, session, decision point, horizon):

1. **Return** `r_h = 10,000 * ln(Ph / P0)` in basis points (regression target).
2. **Direction** (primary classification target), with a dead zone `theta_h`:
   `UP` if `r_h > theta_h`, `DOWN` if `r_h < -theta_h`, else `FLAT`.
3. **Excursions** (for E07 stop and target studies, not trained on in v1):
   `mfe_h` and `mae_h` = max and min of `10,000 * ln(high / P0)` and
   `10,000 * ln(low / P0)` over bars stamped `D + 2 min` to `D + 1 min + h`.

**Dead zone.** `theta_h = max(C, 0.5 * m_h)`, where

- `C = 16 bps`: the round trip at the backtest minimums, `2 * (3 fee + 5
  slippage)` (Fact: `MIN_FEE_BPS = 3`, `MIN_SLIPPAGE_BPS = 5` in
  `app/strategies/rules.py`). A move smaller than costs is not a tradable `UP` or
  `DOWN`.
- `m_h` = median of `|r_h|` for the same instrument, decision point and horizon
  over the **20 prior sessions** (strictly before the labelled session, rule L4).

A label is `INVALID`, not `FLAT`, when any bar it needs is missing. Invalid
labels are excluded from training and scoring and counted in the evaluation
report.

## 5. Regimes

**Proposal.** A regime is computed **at the decision point from features only**,
so it is known when the prediction is made and can be used by E06 as a filter.
It is never computed from the label window.

Inputs at decision `D` (all from inputs with `availableAt <= T`, and bars that end at or before `D`, rule L2):

| Name | Definition |
|---|---|
| `O` | open of the 09:15 bar |
| `C_D` | close of the last bar before `D` (09:29 or 09:44) |
| `H_D`, `L_D` | high and low over bars 09:15 to `D - 1 min` |
| `PC` | previous session's daily close |
| `gap` | `10,000 * ln(O / PC)` bps |
| `drive` | `10,000 * ln(C_D / O)` bps |
| `range` | `10,000 * ln(H_D / L_D)` bps |
| `eff` | `abs(C_D - O) / (H_D - L_D)`, 0 when the range is 0 |
| `M` | median `range` at the same `D` over the 20 prior sessions |
| `rangeRatio` | `range / M` when `M > 0`; undefined when `M = 0` (abstain `FLAT_HISTORY`, section 6), whatever the current `range` |
| `vix` | last INDIAVIX observation made at or before `D` (a 1m bar whose end, `time + 1 min`, is at or before `D`; or a snapshot with `asOf <= D`) and with `availableAt <= T` (feature only) |

Two axes, each with fixed rules evaluated in order:

**Volatility state**

| State | Rule |
|---|---|
| `EXTREME` | `rangeRatio >= 3.0` or `abs(gap) >= 200 bps` |
| `HIGH` | `rangeRatio >= 1.5` |
| `LOW` | `rangeRatio <= 0.6` |
| `NORMAL` | otherwise |

**Direction state**

| State | Rule |
|---|---|
| `TREND_UP` | `eff >= 0.6` and `drive > 0` |
| `TREND_DOWN` | `eff >= 0.6` and `drive < 0` |
| `RANGE` | otherwise |

Regime id = `<direction>/<volatility>`, for example `TREND_UP/NORMAL`. That gives
12 ids (3 x 4). `EXTREME` always abstains (section 6), so 9 ids can carry a
prediction. A `gapDirection` flag (`GAP_UP` if `gap >= 30 bps`, `GAP_DOWN` if
`gap <= -30 bps`, else `NONE`) is reported alongside but is not part of the id,
to keep the id set small for E06.

Thresholds (0.6, 1.5, 3.0, 0.6, 200, 30) are starting values to be checked
against real history once the E02 feed is chosen. The regime definition gets a
`regimeVersion`; changing a threshold is a new version, and stored regimes are
never relabelled in place.

## 6. Abstention

**Proposal.** Abstaining is an explicit output, not a missing one. For every
scheduled (instrument, decision point) the engine publishes exactly one record,
with `status` `PREDICT` or `ABSTAIN` and a list of reason codes. Downstream
engines treat `ABSTAIN` as "no signal". Abstention never blocks or approves an
order by itself; Risk decides separately.

Checks run in this order; all failing checks are reported, and any one of them
forces `ABSTAIN`:

| Code | Abstain when |
|---|---|
| `NOT_A_SESSION` | the calendar says `D` is not in a regular session (holiday, weekend) |
| `SESSION_NOT_STANDARD` | the session did not open at 09:15, is a special or shortened session, or a market-wide halt is in force or occurred before `D` |
| `SOURCE_MISMATCH` | inputs come from more than one `source`, or the source does not match the environment (`demo` data may only feed `DEMO` records) |
| `STALE_INPUT` | `freshness` is `stale`; or the newest 1m bar's `availableAt` is earlier than `D - 2 min`; or the INDIAVIX value is older than 5 min at `D` |
| `MISSING_BARS` | any 1m bar stamped 09:15 to `D - 1 min` is missing at `T` (v1 requires all 15 or 30) |
| `INVALID_BAR` | a bar fails the `MarketCandle` invariants (OHLC bounds, UTC, ascending), or a 1m bar's `time` is not on a whole minute (seconds and fractions must be 0; the schema does not enforce this today, so the engine checks it on input) |
| `NO_HISTORY` | fewer than 20 prior sessions exist for the trailing medians, or `PC` is missing |
| `FLAT_HISTORY` | the 20 sessions exist but their median opening range `M` is 0, so `rangeRatio` is undefined (a frozen or bad feed, not a real market) |
| `EXTREME_REGIME` | volatility state is `EXTREME` |
| `MODEL_NOT_VALIDATED` | no validated model version exists for this decision point and horizon (E06 rule: no automatic promotion) |
| `LOW_CONFIDENCE` | the model's top class probability is below `0.55` (Estimate, to be calibrated in E05) |
| `LOOKAHEAD_GUARD` | any input used has `availableAt > T`, or any bar used is stamped `D` or later (rules L1, L2); this also raises an error event, because it means a bug, not a market condition |
| `LATE` | the record would be published after `D + 1 min` |

Abstention is per horizon where the cause is horizon-specific (`MODEL_NOT_VALIDATED`,
`LOW_CONFIDENCE`), and per decision point otherwise.

Coverage is a reported metric: the share of scheduled records that are
`PREDICT`. A model is judged on accuracy where it predicts **and** on coverage;
a model that abstains on everything scores zero coverage, not perfect accuracy.

## 7. Rules that prevent lookahead

**Proposal.** Each rule is written so E16 can test it.

| Id | Rule | How E16 can test it |
|---|---|---|
| L1 | A feature at `D` uses only records with `availableAt <= T` (`T = D + 10 s`). The bar `time` alone is never the cutoff. | Inject a bar stamped `D - 1 min` with `receivedAt = D + 3 s`: used. Same bar with `receivedAt = D + 15 s`: excluded (`MISSING_BARS`), never used. |
| L2 | No input observed after `D` is a feature, even if it arrives before `T`. A bar is a feature only if its end (`time + 1 min`) is at or before `D`, so the bar stamped `D` and later bars are only label inputs; a snapshot is a feature only if `asOf <= D`. 1m bars must be minute-aligned (`INVALID_BAR` otherwise). | Change the `D` and `D + 1 min` bars' values: features and regime must not change. Inject a bar stamped `D - 55 s`: it is rejected (`INVALID_BAR`), never used. |
| L3 | Today's daily bar is forming during the session and is never a feature. Only completed prior-session daily bars are. | Drop today's 1D bar; features must not change. |
| L4 | Every trailing statistic (medians, percentiles, scaler means, the `theta_h` dead zone) uses sessions strictly before the decision session. No full-sample normalization. | Change any value on or after the decision session; past statistics must not change. |
| L5 | Feature and label code live in separate modules; feature code may not import label code. | Import-graph check. |
| L6 | Model evaluation is walk-forward by session: train on sessions before `S`, test on `S`. Labels end inside their session (max 10:47 IST), so no purge gap is needed between sessions; a random row-level split is not allowed. | Assert every training session precedes every test session. |
| L7 | Inputs are stored as first received. A later correction is a new record with its own `receivedAt`; replays use what was available at `D`. | Correct a stored bar after `D`; a replay at `D` must use the original. |
| L8 | Adjusted history (splits, dividends) is used only with point-in-time adjustment factors. v1 has indices only, so this applies from the first equity target. | Out of v1; tracked for later. |
| L9 | Each record stores `decisionTime = D`, `featureCutoff = T`, the max `availableAt` it used, and a hash of its inputs, so any record can be re-derived and audited. | Recompute from stored inputs; hash must match. |

## 8. Output record

**Proposal.** Payload of `Intelligence.SnapshotPublished`, version 1 (the event
named in ENGINES.md section 4). Shown as JSON; field names follow the envelope's
camelCase. Not in `contracts/openapi.yaml`; it goes there only if an API exposes
it, through a separate contract PR.

```json
{
  "instrumentId": "NSE:NIFTY50",
  "sessionDate": "2026-11-23",
  "decisionPoint": "DP0930",
  "decisionTime": "2026-11-23T04:00:00Z",
  "featureCutoff": "2026-11-23T04:00:10Z",
  "maxInputAvailableAt": "2026-11-23T04:00:05Z",
  "publishedAt": "2026-11-23T04:00:12Z",
  "source": "demo",
  "regimeVersion": 1,
  "regime": "RANGE/NORMAL",
  "gapDirection": "NONE",
  "status": "PREDICT",
  "reasons": [],
  "predictions": [
    { "horizonMinutes": 15, "status": "PREDICT", "direction": "FLAT", "probabilities": { "UP": 0.21, "FLAT": 0.6, "DOWN": 0.19 }, "modelVersion": "e05-x.y" },
    { "horizonMinutes": 30, "status": "ABSTAIN", "reasons": ["LOW_CONFIDENCE"] },
    { "horizonMinutes": 60, "status": "ABSTAIN", "reasons": ["MODEL_NOT_VALIDATED"] }
  ],
  "inputsHash": "sha256:..."
}
```

The probabilities and model version above are placeholders; no model exists yet.

## 9. Worked examples

### 9.1 Features precede targets (real demo data)

Reproducible from the demo provider on main `17a409d`
(`DemoMarketDataProvider("ready")`, `NSE:NIFTY50`, 1m and 1D, session
2026-11-23; the previous session in the demo calendar is 2026-11-20). Script in
section 9.4.

Inputs at DP0930, treated as a backfill (bar end plus the 5 second lag). Every
feature input is available at or before the input cutoff `T` = 04:00:10 UTC:

| Input | Bar `time` (IST) | `availableAt` (UTC) | Used as |
|---|---|---|---|
| Daily bar 2026-11-20, close 24349.61 | 2026-11-20 09:15 | 2026-11-20 10:00:05 | `PC` |
| 1m bar, open 24318.73 | 09:15 | 03:46:05 | `O` |
| ... 13 more 1m bars ... | 09:16 to 09:28 | 03:47:05 to 03:59:05 | `H_D`, `L_D` |
| 1m bar, close 24327.62 | 09:29 | 04:00:05 | `C_D` (last feature bar) |
| 1m bar 09:30 | 09:30 | 04:01:05 | not used (stamped `D`, rule L2) |
| 1m bar 09:31, close 24329.21 | 09:31 | **04:02:05** | label `P0` only, not a feature |

Computed features and regime:

| Decision | `gap` | `drive` | `range` | `eff` | Direction state |
|---|---|---|---|---|---|
| DP0930 | -12.7 bps | +3.7 bps | 10.1 bps | 0.363 | `RANGE` |
| DP0945 | -12.7 bps | +5.9 bps | 12.3 bps | 0.483 | `RANGE` |

`gapDirection` is `NONE` (|gap| < 30). The volatility state needs 20 prior
sessions of 1m data; the demo provider serves one session of 1m bars (Fact:
`_SESSION_COUNTS["1m"] = 1`), so on demo data the record abstains with
`NO_HISTORY` (example 9.2 C). The labels below are still computable, which is
what this example shows.

Labels. Every exit bar is available after the publish deadline:

| Decision | h | `P0` (bar, close) | `Ph` (bar, close) | `r_h` | Label final at, backfill (IST) | Direction at `theta = 16` |
|---|---|---|---|---|---|---|
| DP0930 | 15 | 09:31, 24329.21 | 09:46, 24335.17 | +2.4 bps | 09:47:05 | `FLAT` |
| DP0930 | 30 | 09:31, 24329.21 | 10:01, 24343.09 | +5.7 bps | 10:02:05 | `FLAT` |
| DP0930 | 60 | 09:31, 24329.21 | 10:31, 24338.70 | +3.9 bps | 10:32:05 | `FLAT` |
| DP0945 | 15 | 09:46, 24335.17 | 10:01, 24343.09 | +3.3 bps | 10:02:05 | `FLAT` |
| DP0945 | 30 | 09:46, 24335.17 | 10:16, 24348.58 | +5.5 bps | 10:17:05 | `FLAT` |
| DP0945 | 60 | 09:46, 24335.17 | 10:46, 24317.68 | -7.2 bps | 10:47:05 | `FLAT` |

`theta = 16` is the cost floor `C`; with 20 prior sessions it would be
`max(16, 0.5 * m_h)`. Ordering holds in every row (DP0930, IST): latest feature
`availableAt` (09:30:05) <= input cutoff (09:30:10) < publish deadline (09:31:00)
< `P0` bar end (09:32:00) < label final.
The demo series moves little, so every label is `FLAT`; that is a property of the
demo data, not of the rule.

### 9.2 Abstention cases (constructed)

These records are constructed to show each rule; they are not provider output.

**A. Stale input.** DP0930, 2026-12-01. Newest 1m bar stamped 09:26 IST,
`availableAt` 03:57:00 UTC (09:27 IST). `D - 2 min` = 09:28 IST. 09:27 < 09:28,
so `STALE_INPUT`; bars 09:27 to 09:29 are also absent, so `MISSING_BARS`.

```json
{ "decisionPoint": "DP0930", "sessionDate": "2026-12-01", "status": "ABSTAIN",
  "reasons": ["STALE_INPUT", "MISSING_BARS"], "maxInputAvailableAt": "2026-12-01T03:57:00Z" }
```

**B. Provider says stale.** `MarketCandles.freshness = "stale"` (the demo
provider's `stale` scenario serves the previous session): `STALE_INPUT`, whatever
the bar times say.

**C. Not enough history.** Demo data at DP0930 on 2026-11-23 (example 9.1): one
session of 1m bars, so the 20-session medians for `rangeRatio` and `theta_h`
cannot be computed: `NO_HISTORY`.

**D. One missing bar.** DP0945, bars 09:15 to 09:44 present except 09:37:
`MISSING_BARS`. v1 does not interpolate.

**E. Late input (lookahead guard).** DP0930, bar stamped 09:29 IST arrives with
`receivedAt` 04:00:15 UTC. Its `availableAt` is 04:00:15 > cutoff `T` 04:00:10,
so it is excluded, which makes it missing: `MISSING_BARS`. If any code path did
use it, the record is `LOOKAHEAD_GUARD` and an error event is raised. (The same
bar arriving at 04:00:03 is inside the grace window and is used normally.)

**G. Frozen history.** 20 prior sessions exist, but a bad feed repeated one
price, so the median opening range `M` is 0. `rangeRatio` is undefined:
`FLAT_HISTORY`.

**F. Extreme open.** `gap = -240 bps`: volatility state `EXTREME`,
`EXTREME_REGIME`.

### 9.3 Holiday

`D` on an exchange holiday: one record per scheduled instrument is still
written for the audit trail, with `NOT_A_SESSION`. (Proposal: the scheduler,
E11, may instead skip scheduling holidays; either way no prediction is made.)

### 9.4 Reproduction script

Run from `backend/` with `uv run python <file>`:

```python
import asyncio, math
from datetime import timedelta, timezone
from app.market.demo import DemoMarketDataProvider

IST = timezone(timedelta(hours=5, minutes=30))

async def main() -> None:
    p = DemoMarketDataProvider()
    bars = (await p.get_candles("NSE:NIFTY50", "1m")).candles
    prev = (await p.get_candles("NSE:NIFTY50", "1D")).candles[-2]
    by = {b.time.astimezone(IST).strftime("%H:%M"): b for b in bars}
    for hh, mm in ((9, 30), (9, 45)):
        t0 = hh * 60 + mm
        f = [b for b in bars if b.time.astimezone(IST).hour * 60 + b.time.astimezone(IST).minute < t0]
        o, c = f[0].open, f[-1].close
        hi, lo = max(b.high for b in f), min(b.low for b in f)
        print(f"{hh:02d}:{mm:02d}", len(f), "gap", round(1e4 * math.log(o / prev.close), 1),
              "drive", round(1e4 * math.log(c / o), 1), "range", round(1e4 * math.log(hi / lo), 1),
              "eff", round(abs(c - o) / (hi - lo), 3))
        e = t0 + 1  # P0 is the bar stamped D + 1 min
        p0 = by[f"{e // 60:02d}:{e % 60:02d}"].close
        for h in (15, 30, 60):
            ph = by[f"{(e + h) // 60:02d}:{(e + h) % 60:02d}"].close
            print("  h", h, p0, ph, round(1e4 * math.log(ph / p0), 1))

asyncio.run(main())
```

## 10. Decisions for the owner

Each has a recommended option; the values above already use it.

1. **Universe v1.** Recommended: the three indices only (NIFTY 50, Bank Nifty,
   Fin Nifty). Alternative: add liquid equities now, which needs point-in-time
   corporate-action data (L8) from the E02 feed.
2. **Entry reference.** Recommended: close of the bar stamped `D + 1 min`
   (one minute to publish, then one minute to act). Alternatives: the close of
   the bar stamped `D`, which ends exactly at the publish deadline and so assumes
   zero execution latency; or a later bar, which is safer if execution turns out
   slower than a minute but measures less of the move.
3. **Dead zone.** Recommended: `max(16 bps, 0.5 x 20-session median |r_h|)`.
   Alternative: a fixed 16 bps, simpler but makes `FLAT` rare on volatile days.
4. **Missing bars.** Recommended: abstain on any missing bar in v1.
   Alternative: allow one missing non-final bar, which raises coverage but makes
   the regime depend on a gap-filling rule.
5. **Holidays.** Recommended: write `NOT_A_SESSION` records. Alternative: skip.

## 11. Review record

| Item | Status |
|---|---|
| Draft | 0.1.0, 2026-11-26 (revised after CodeRabbit review: input grace, entry latency, zero-range history) |
| Engine boundary version | ENGINES.md 1.0.0 |
| Owner decisions (section 10) | Pending |
| Tested revision | Docs only; examples computed on main `17a409d` with the script in 9.4 |
