# funding-squeeze-v1 — PARKED

## Thesis validation
Real edge exists in forward returns after extreme funding:
- HYPE 12h forward after p99 funding: +0.86% (83% pos rate, n=6)
- HYPE 24h forward after p99 funding: +2.20% (80% pos rate, n=15)

## Backtest result
PF 0.80 (taker 0.72 / maker 0.77) on 54 trades over 90d. 29.6% WR.

## Why it failed in backtest despite real edge
SL/TP execution caps the trade at 1.5×ATR loss, but the squeeze plays out
over 12-24h with notable intra-trade drawdown. Stop-loss gets tagged in
noise before the thesis resolves.

## What to try
Patience-based execution model:
  - Place LIMIT order at touch when funding extreme triggers
  - Hold without SL until either:
       a) max_hold_bars (12h) elapses, OR
       b) Funding rate normalizes (cur returns to within p25-p75 of 30d)
  - This is a maker-resting-bet, not a momentum chase

Or treat as a confluence amplifier: when an existing engine fires
LONG on a coin in p95+ funding, multiply size by 1.3-1.5×.

## Status
Service NOT deployed. Repo exists for future revival.
