"""
META down / QQQ up ≥2% divergence analysis.

Reads OHLCV JSON files fetched from the IBKR price-history API
(5-year daily bars for META and QQQ) and identifies every session
where META closed negative while QQQ gained ≥2%.

Usage:
    python3 meta_qqq_divergence.py <meta_json> <qqq_json>

If no arguments are supplied the script expects the files at the
default paths shown in DEFAULT_*.
"""

import json
import sys
from datetime import datetime

DEFAULT_META = "meta_price_history.json"
DEFAULT_QQQ  = "qqq_price_history.json"


def build_closes(data: dict) -> dict[str, float]:
    """Return {YYYY-MM-DD: close_price} from IBKR chart JSON."""
    return {t[:10]: c for t, c in zip(data["time"], data["close"])}


def run(meta_path: str, qqq_path: str) -> None:
    with open(meta_path) as f:
        meta = json.load(f)
    with open(qqq_path) as f:
        qqq = json.load(f)

    meta_c = build_closes(meta)
    qqq_c  = build_closes(qqq)
    dates  = sorted(set(meta_c) & set(qqq_c))

    events = []
    for i in range(1, len(dates)):
        d, p = dates[i], dates[i - 1]
        mr = (meta_c[d] - meta_c[p]) / meta_c[p]
        qr = (qqq_c[d]  - qqq_c[p])  / qqq_c[p]
        if mr < 0 and qr >= 0.02:
            events.append({
                "date":         d,
                "weekday":      datetime.strptime(d, "%Y-%m-%d").strftime("%A"),
                "meta_ret_pct": round(mr * 100, 4),
                "qqq_ret_pct":  round(qr * 100, 4),
                "meta_close":   meta_c[d],
                "qqq_close":    qqq_c[d],
                "spread_bp":    round((qr - mr) * 10000, 1),
            })

    total = len(dates) - 1

    print("=" * 78)
    print("  META DOWN / QQQ UP ≥ 2%  — Divergence Events")
    print("=" * 78)
    print(f"  Window       : {dates[0]} → {dates[-1]}")
    print(f"  Trading days : {total}")
    print(f"  Events       : {len(events)} ({len(events)/total*100:.2f}% of sessions)")
    if events:
        avg_q = sum(e["qqq_ret_pct"]  for e in events) / len(events)
        avg_m = sum(e["meta_ret_pct"] for e in events) / len(events)
        avg_s = sum(e["spread_bp"]    for e in events) / len(events)
        print(f"  Avg QQQ ret  : {avg_q:+.2f}%")
        print(f"  Avg META ret : {avg_m:+.2f}%")
        print(f"  Avg spread   : {avg_s:.0f} bp")
    print()
    print(f"  {'Date':<12} {'Day':<11} {'META':>8} {'QQQ':>8} {'Spread':>9}  META $    QQQ $")
    print("  " + "-" * 68)
    for e in events:
        print(
            f"  {e['date']:<12} {e['weekday']:<11} "
            f"{e['meta_ret_pct']:>+7.2f}% {e['qqq_ret_pct']:>+7.2f}% "
            f"{e['spread_bp']:>8.0f}bp  ${e['meta_close']:>8.2f}  ${e['qqq_close']:>7.2f}"
        )
    print("  " + "-" * 68)


if __name__ == "__main__":
    meta_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_META
    qqq_path  = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_QQQ
    run(meta_path, qqq_path)
