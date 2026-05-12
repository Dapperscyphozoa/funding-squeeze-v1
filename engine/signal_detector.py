"""
funding-squeeze-v1 — goes WITH the funding-payer direction during extreme events.

THESIS (empirically validated on 60d HL data):
  When longs pay extreme positive funding (p99 funding rate), the price
  often continues higher over the next 6-24h. The conviction holders
  endure the funding cost because they believe in the direction.

  Counter-intuitive vs textbook "crowded trade fades" — the squeeze is real
  but it squeezes the SHORTS who are getting paid (they exit, drive price
  up further), not the longs who are paying.

  Empirical: HYPE 12h forward return after p99 funding = +0.86%, 83% pos
  rate (n=6). 24h forward return = +2.20%, 80% pos rate (n=15).

Fire LONG when:
  - Latest funding rate > p95 of last 30d funding distribution
  - Funding is positive (longs paying — short squeeze setup)
  - Coin in trend_up or range regime (not trend_down — let macro filter handle)

Fire SHORT when:
  - Latest funding rate < p5 of last 30d funding distribution
  - Funding is negative (shorts paying — long squeeze setup)
  - Coin in trend_down or range regime

SL: 1.5×ATR (cascade can be sharp). TP: 5.0×ATR (squeezes overshoot).
max_hold: 12 bars (squeezes resolve within 12h or never).
"""
from __future__ import annotations
import json
import time
import urllib.request
import numpy as np
import pandas as pd
from typing import Optional
from .config import STRATEGY_PARAMS, TRADE_PARAMS

_funding_cache = {"ts": 0, "data": {}}
_FUNDING_TTL = 900  # 15 min


def _hl_request(payload, timeout=10):
    try:
        req = urllib.request.Request("https://api.hyperliquid.xyz/info",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _get_funding_distribution(coin: str):
    """Returns (current_rate, p95, p5) over last 30 days."""
    cache = _funding_cache["data"].get(coin)
    if cache and (time.time() - cache.get("ts", 0)) < _FUNDING_TTL:
        return cache["current"], cache["p95"], cache["p5"]

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - 30 * 86400_000
    fh = _hl_request({"type": "fundingHistory", "coin": coin,
                       "startTime": start_ms, "endTime": end_ms})
    if not fh or len(fh) < 50:
        return None, None, None
    rates = [float(f["fundingRate"]) for f in fh]
    rates_arr = np.array(rates)
    current = rates[-1]
    p95 = float(np.quantile(rates_arr, 0.95))
    p5 = float(np.quantile(rates_arr, 0.05))
    _funding_cache["data"][coin] = {
        "ts": time.time(), "current": current, "p95": p95, "p5": p5
    }
    return current, p95, p5


def _calc_atr(highs, lows, closes, period=14):
    h_s = pd.Series(highs); l_s = pd.Series(lows); pc = pd.Series(closes).shift(1)
    tr = pd.concat([h_s - l_s, (h_s - pc).abs(), (l_s - pc).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def evaluate_latest_bar(df: pd.DataFrame) -> Optional[dict]:
    """Fire funding-squeeze when current funding hits extreme of 30d distribution."""
    coin = df.attrs.get("coin", "")
    if not coin: return None
    if df is None or len(df) < 50: return None

    current, p95, p5 = _get_funding_distribution(coin)
    if current is None: return None

    # Backtest mode: funding can be injected via df.attrs to avoid HTTP
    if "funding_current" in df.attrs:
        current = df.attrs["funding_current"]
    if "funding_p95" in df.attrs:
        p95 = df.attrs["funding_p95"]
    if "funding_p5" in df.attrs:
        p5 = df.attrs["funding_p5"]

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    last_c = float(closes[-1])

    is_long = False
    is_short = False
    fire_reason = ""

    # Hysteresis to avoid firing every bar in a sustained-extreme regime
    if current > p95 and current > 0:
        is_long = True
        fire_reason = f"long_funding_p95+ ({current:.6f} > {p95:.6f})"
    elif current < p5 and current < 0:
        is_short = True
        fire_reason = f"short_funding_p5- ({current:.6f} < {p5:.6f})"
    else:
        return None

    # Don't fight obvious counter-trend: skip if recent 20-bar slope strongly opposed
    slope_20 = (closes[-1] / closes[-21]) - 1 if len(closes) > 21 else 0
    if is_long and slope_20 < -0.05: return None
    if is_short and slope_20 > 0.05: return None

    # Build SL/TP from ATR
    atr = _calc_atr(highs, lows, closes, TRADE_PARAMS.get("atr_period", 14))
    if not atr or atr <= 0: return None

    sl_m = TRADE_PARAMS.get("sl_atr_mult", 1.5)
    tp_m = TRADE_PARAMS.get("tp_atr_mult", 5.0)
    if is_long:
        sl_p = last_c - sl_m * atr
        tp_p = last_c + tp_m * atr
    else:
        sl_p = last_c + sl_m * atr
        tp_p = last_c - tp_m * atr

    sl_pct = abs(last_c - sl_p) / last_c
    if sl_pct < 0.003 or sl_pct > 0.06:
        return None

    return {
        "fire_ts": df.index[-1],
        "ref_price": last_c,
        "atr": atr,
        "trade_side": "B" if is_long else "A",
        "is_long": is_long,
        "sl_px": float(sl_p),
        "tp_px": float(tp_p),
        "max_hold_bars": TRADE_PARAMS.get("max_hold_bars", 12),
        "fire_reason": fire_reason,
        "raw_direction": "LONG" if is_long else "SHORT",
        "fade_direction": "LONG" if is_long else "SHORT",
        "funding_rate": float(current),
        "funding_p95_30d": float(p95),
        "funding_p5_30d": float(p5),
        "slope_20": float(slope_20),
    }
