# Financial validation plan

## Oracles (`qa/financial_oracles/oracles.py`)

Exact `Decimal` arithmetic, written from first principles, never calling product code.
Money rounds half-up to paise only where a statement would round.

| Function | Validates | Self-tests |
|---|---|---|
| `apply_fills`, `unrealized_pnl` | Weighted-average position, realised/unrealised P&L, shorts, reversals | Hand examples FIN-PNL-001/002; conservation property FIN-PNL-003 (300 random fill sequences) |
| `order_charges` + `ChargeSchedule` | Brokerage (with cap), STT, exchange, SEBI, stamp, GST | FIN-CHG-001 on a synthetic schedule |
| `position_size`, `size_from_bps` | Risk-budget sizing in whole lots; bps notional sizing | FIN-SIZE-001; budget property FIN-SIZE-002 |
| `max_drawdown`, `profit_factor`, `simple_return` | Metrics | FIN-DD-001/002, FIN-PF-001, FIN-RET-001 |
| `daily_loss_breached` | Daily loss limit (Rs 25,000, contract 0.7.0) | FIN-RISK-001 (boundary at exactly the limit) |

Charge rates are deliberately not hard-coded: statutory rates change, so each cross-check must pass a
schedule with a cited source. No current NSE/SEBI rates are asserted in this repository.

## Cross-checks against the product (next, specified)

| ID | Check | How |
|---|---|---|
| FIN-X-PAPER-001 | Paper ledger P&L equals oracle | Drive paper trading via API on demo data, read trades, recompute with `apply_fills` |
| FIN-X-REPORT-001 | Report totals reconcile with `trades.csv` | Parse CSV with `Decimal`, sum, compare to `/reports/paper` |
| FIN-X-BT-001 | Backtest metrics equal oracle | Run a backtest via API, recompute from returned trades with fee/slippage bps |
| FIN-X-RISK-001 | Risk tiers enforced at order time, fail closed | Submit orders at tier boundaries ± 1 bps |

Any discrepancy is filed as high or critical according to monetary impact; tolerance is zero for
paise-rounded money unless the contract states a rounding rule.
