"""
MDY/IWM ATH Divergence Study
=============================
Examines forward returns when MDY and IWM hit new all-time high weekly closes
simultaneously while QQQ and SPY are below their respective highs (breadth
divergence). Additional cut: does this cluster near quarter-end, and what are
the implications for a Q3 2026 lift-off?

Data: ~19 years of weekly OHLCV via broker MCP (step_count=1000)
"""

import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch
import matplotlib.gridspec as gridspec
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

# ─── 0. FILE PATHS ────────────────────────────────────────────────────────────
BASE = ("/root/.claude/projects/-home-user-alpha-query-monitor/"
        "b3e43b86-8eb5-552b-9309-a399a9b57c27/tool-results/")

FILES = {
    "MDY": BASE + "mcp-c0a06834-e584-4e39-990c-e409c8149ce1-get_price_history-1781444148859.txt",
    "IWM": BASE + "mcp-c0a06834-e584-4e39-990c-e409c8149ce1-get_price_history-1781444149854.txt",
    "QQQ": BASE + "mcp-c0a06834-e584-4e39-990c-e409c8149ce1-get_price_history-1781444151542.txt",
    "SPY": BASE + "mcp-c0a06834-e584-4e39-990c-e409c8149ce1-get_price_history-1781444152605.txt",
}

# ─── 1. LOAD DATA ─────────────────────────────────────────────────────────────
def load_series(path, ticker):
    with open(path) as f:
        raw = json.load(f)
    df = pd.DataFrame({
        "date":  pd.to_datetime(raw["time"]),
        "open":  raw["open"],
        "high":  raw["high"],
        "low":   raw["low"],
        "close": raw["close"],
        "vol":   raw["volume"],
    }).set_index("date").sort_index()
    df.index = df.index.tz_localize(None)
    print(f"{ticker}: {len(df)} weeks  |  {df.index[0].date()} → {df.index[-1].date()}"
          f"  |  close range ${df.close.min():.2f}–${df.close.max():.2f}")
    return df

frames = {t: load_series(p, t) for t, p in FILES.items()}

# Align on common dates
common_idx = frames["MDY"].index
for t in ["IWM", "QQQ", "SPY"]:
    common_idx = common_idx.intersection(frames[t].index)

close = pd.DataFrame({t: frames[t].loc[common_idx, "close"] for t in frames})
print(f"\nAligned universe: {len(close)} weeks  |  {close.index[0].date()} → {close.index[-1].date()}")

# ─── 2. ATH DETECTION ─────────────────────────────────────────────────────────
# Rolling expanding max of close (ATH = current close == all-time high so far)
ath = {}
for t in close.columns:
    running_max = close[t].expanding().max()
    ath[t] = close[t] >= running_max          # True when at ATH weekly close

ath = pd.DataFrame(ath)

# ─── 3. CONSOLIDATION FILTER ──────────────────────────────────────────────────
# MDY and IWM must have been BELOW ATH for at least MIN_CONSOL consecutive weeks
# before this week's ATH break — signals a "breakout after rest" rather than
# an immediate continuation
MIN_CONSOL = 3   # weeks below ATH immediately prior

def consol_weeks_below_ath(series_at_ath, min_weeks):
    """True at week t if: series is at ATH at t, AND was below ATH for at
       least `min_weeks` of the prior weeks without interruption."""
    result = pd.Series(False, index=series_at_ath.index)
    for i in range(min_weeks, len(series_at_ath)):
        if not series_at_ath.iloc[i]:
            continue
        # count how many consecutive weeks prior were NOT at ATH
        look_back = series_at_ath.iloc[max(0, i - 52): i]  # look back up to 1yr
        # walk backwards from i-1
        consec = 0
        for j in range(len(look_back) - 1, -1, -1):
            if look_back.iloc[j]:  # was at ATH, chain broken
                break
            consec += 1
        if consec >= min_weeks:
            result.iloc[i] = True
    return result

print("\nComputing consolidation filter (this takes a moment)…")
mdy_breakout = consol_weeks_below_ath(ath["MDY"], MIN_CONSOL)
iwm_breakout = consol_weeks_below_ath(ath["IWM"], MIN_CONSOL)

# ─── 4. SIGNAL: BOTH SMALL/MID BREAK OUT, LARGE-CAP STILL BELOW ──────────────
signal = (
    mdy_breakout &                   # MDY new ATH after ≥3 wk consolidation
    iwm_breakout &                   # IWM new ATH after ≥3 wk consolidation
    ~ath["QQQ"] &                    # QQQ NOT at ATH
    ~ath["SPY"]                      # SPY NOT at ATH
)

# De-duplicate: keep only first week of each signal cluster
# (suppress signal if prior week also signaled)
signal_dedup = signal & ~signal.shift(1, fill_value=False)

signal_dates = close.index[signal_dedup]
print(f"\nSignal occurrences (MDY+IWM ATH breakout, QQQ+SPY lagging): {len(signal_dates)}")

# ─── 5. FORWARD RETURNS ───────────────────────────────────────────────────────
HORIZONS = {
    "1w":  1,
    "2w":  2,
    "4w":  4,
    "8w":  8,
    "13w": 13,
}

def forward_returns(price_series, dates, horizons):
    """Returns dict of horizon → Series of forward returns."""
    results = {}
    for label, n in horizons.items():
        fwd = []
        for d in dates:
            loc = price_series.index.get_loc(d)
            future_loc = loc + n
            if future_loc < len(price_series):
                ret = price_series.iloc[future_loc] / price_series.iloc[loc] - 1
                fwd.append({"date": d, "fwd_ret": ret})
        results[label] = pd.DataFrame(fwd).set_index("date")
    return results

fwd_rets = {t: forward_returns(close[t], signal_dates, HORIZONS) for t in close.columns}

# ─── 6. QUARTER-END ANALYSIS ──────────────────────────────────────────────────
# Final 4 weeks of a calendar quarter: mid-March, mid-June, mid-Sept, mid-Dec
def is_quarter_end_zone(dt, weeks_before_qend=4):
    """True if the date falls in the final `weeks_before_qend` weeks of a quarter."""
    month = dt.month
    # Quarter ends: March 31, June 30, Sept 30, Dec 31
    qend_month = {1:3, 2:3, 3:3, 4:6, 5:6, 6:6, 7:9, 8:9, 9:9, 10:12, 11:12, 12:12}[month]
    qend = pd.Timestamp(dt.year, qend_month, 1) + pd.offsets.MonthEnd(0)
    days_to_qend = (qend - dt).days
    return 0 <= days_to_qend <= (weeks_before_qend * 7)

qend_mask = pd.Series([is_quarter_end_zone(d) for d in signal_dates], index=signal_dates)
qend_dates    = signal_dates[qend_mask]
non_qend_dates = signal_dates[~qend_mask]

print(f"\nSignals in final-4-weeks of quarter: {len(qend_dates)}")
print(f"Signals outside quarter-end zone:    {len(non_qend_dates)}")

# ─── 7. STATISTICS SUMMARY ────────────────────────────────────────────────────
def summarize(ret_dict, label):
    rows = []
    for hz in HORIZONS:
        for ticker in close.columns:
            s = ret_dict[ticker][hz]["fwd_ret"]
            if len(s) == 0:
                continue
            t_stat, p_val = stats.ttest_1samp(s, 0)
            rows.append({
                "Horizon": hz,
                "Ticker": ticker,
                f"N ({label})": len(s),
                "Mean %": round(s.mean() * 100, 2),
                "Median %": round(s.median() * 100, 2),
                "Std %": round(s.std() * 100, 2),
                "Win%": round((s > 0).mean() * 100, 1),
                "Max %": round(s.max() * 100, 2),
                "Min %": round(s.min() * 100, 2),
                "t-stat": round(t_stat, 2),
                "p-val": round(p_val, 3),
            })
    return pd.DataFrame(rows)

all_fwd_rets_by_horizon = {}
for hz in HORIZONS:
    all_fwd_rets_by_horizon[hz] = pd.DataFrame({
        t: fwd_rets[t][hz]["fwd_ret"] for t in close.columns
    })

# Full signal stats
full_stats = summarize(fwd_rets, "All")

# Compute qend / non-qend splits
def split_forward_returns(full_fwd, dates_subset, horizons):
    subset_dict = {}
    for t in close.columns:
        subset_dict[t] = {}
        for hz in horizons:
            series = full_fwd[t][hz]["fwd_ret"]
            subset_dict[t][hz] = series[series.index.isin(dates_subset)].to_frame()
    return subset_dict

qend_fwd  = split_forward_returns(fwd_rets, qend_dates, HORIZONS)
nqend_fwd = split_forward_returns(fwd_rets, non_qend_dates, HORIZONS)

qend_stats  = summarize(qend_fwd, "Q-end zone")
nqend_stats = summarize(nqend_fwd, "Non Q-end")

# ─── 8. PRINT RESULTS ─────────────────────────────────────────────────────────
print("\n" + "═"*80)
print("  MDY/IWM ATH BREAKOUT WHILE QQQ/SPY LAG — FULL SIGNAL FORWARD RETURNS")
print("═"*80)
pivot = full_stats.pivot_table(
    index=["Horizon", "Ticker"],
    values=["N (All)", "Mean %", "Median %", "Win%", "t-stat", "p-val"],
    aggfunc="first"
)
print(pivot.to_string())

print("\n" + "═"*80)
print("  SIGNAL DATES & CONTEXT")
print("═"*80)
for d in signal_dates:
    qz = "  ◄ Q-END ZONE" if is_quarter_end_zone(d) else ""
    mdy_c = close.loc[d, "MDY"]
    iwm_c = close.loc[d, "IWM"]
    qqq_c = close.loc[d, "QQQ"]
    spy_c = close.loc[d, "SPY"]
    qqq_max = close.loc[:d, "QQQ"].max()
    spy_max = close.loc[:d, "SPY"].max()
    qqq_pct_below = (qqq_c / qqq_max - 1) * 100
    spy_pct_below = (spy_c / spy_max - 1) * 100
    print(f"  {d.strftime('%Y-%m-%d')}  MDY={mdy_c:.1f}  IWM={iwm_c:.1f}"
          f"  QQQ {qqq_pct_below:+.1f}% from ATH  SPY {spy_pct_below:+.1f}% from ATH"
          + qz)

print("\n" + "═"*80)
print("  QUARTER-END ZONE SIGNALS (final 4 weeks of quarter)")
print("═"*80)
if len(qend_dates) > 0:
    qe_pivot = qend_stats.pivot_table(
        index=["Horizon", "Ticker"],
        values=["N (Q-end zone)", "Mean %", "Median %", "Win%", "t-stat"],
        aggfunc="first"
    )
    print(qe_pivot.to_string())
else:
    print("  No quarter-end signals found.")

print("\n" + "═"*80)
print("  NON QUARTER-END SIGNALS")
print("═"*80)
if len(non_qend_dates) > 0:
    nqe_pivot = nqend_stats.pivot_table(
        index=["Horizon", "Ticker"],
        values=["N (Non Q-end)", "Mean %", "Median %", "Win%", "t-stat"],
        aggfunc="first"
    )
    print(nqe_pivot.to_string())

# ─── 9. CURRENT SETUP CONTEXT ────────────────────────────────────────────────
print("\n" + "═"*80)
print("  CURRENT SETUP — JUNE 14, 2026 (Week of Jun 9–13)")
print("═"*80)
last = close.index[-1]
mdy_last = close.loc[last, "MDY"]
iwm_last = close.loc[last, "IWM"]
qqq_last = close.loc[last, "QQQ"]
spy_last = close.loc[last, "SPY"]
mdy_ath_val = close["MDY"].max()
iwm_ath_val = close["IWM"].max()
qqq_ath_val = close["QQQ"].max()
spy_ath_val = close["SPY"].max()
print(f"  Last weekly close: {last.date()}")
print(f"  MDY: ${mdy_last:.2f}  (ATH: ${mdy_ath_val:.2f})  {'✓ AT ATH' if mdy_last >= mdy_ath_val*0.999 else f'{(mdy_last/mdy_ath_val-1)*100:+.1f}% from ATH'}")
print(f"  IWM: ${iwm_last:.2f}  (ATH: ${iwm_ath_val:.2f})  {'✓ AT ATH' if iwm_last >= iwm_ath_val*0.999 else f'{(iwm_last/iwm_ath_val-1)*100:+.1f}% from ATH'}")
print(f"  QQQ: ${qqq_last:.2f}  (ATH: ${qqq_ath_val:.2f})  {'✓ AT ATH' if qqq_last >= qqq_ath_val*0.999 else f'{(qqq_last/qqq_ath_val-1)*100:+.1f}% from ATH'}")
print(f"  SPY: ${spy_last:.2f}  (ATH: ${spy_ath_val:.2f})  {'✓ AT ATH' if spy_last >= spy_ath_val*0.999 else f'{(spy_last/spy_ath_val-1)*100:+.1f}% from ATH'}")
print(f"\n  Days to Q2 end (June 30): {(pd.Timestamp('2026-06-30') - pd.Timestamp('2026-06-14')).days}")
print(f"  In quarter-end zone (final 4 wks): {is_quarter_end_zone(pd.Timestamp('2026-06-14'))}")

# ─── 10. CHARTS ───────────────────────────────────────────────────────────────
SAVE_DIR = "/home/user/alpha-query-monitor/studies/"

# ── Chart 1: Price with signal flags ──────────────────────────────────────────
fig, axes = plt.subplots(4, 1, figsize=(16, 14), sharex=True)
fig.suptitle("MDY/IWM ATH Breakout While QQQ/SPY Lag — Weekly Price History\n"
             "(Vertical bands = signal weeks)", fontsize=14, fontweight='bold', y=0.98)

colors = {"MDY": "#1f77b4", "IWM": "#ff7f0e", "QQQ": "#2ca02c", "SPY": "#d62728"}
for ax, ticker in zip(axes, ["MDY", "IWM", "QQQ", "SPY"]):
    ax.plot(close.index, close[ticker], color=colors[ticker], lw=1.2, label=ticker)
    # ATH line
    ax.plot(close.index, close[ticker].expanding().max(),
            color=colors[ticker], lw=0.6, ls='--', alpha=0.5, label="Rolling ATH")
    # Signal shading
    for d in signal_dates:
        ax.axvline(d, color='gold', alpha=0.6, lw=1.5, zorder=2)
    # Q-end signals
    for d in qend_dates:
        ax.axvline(d, color='red', alpha=0.8, lw=2, zorder=3)
    ax.set_ylabel(f"{ticker} ($)", fontsize=9)
    ax.legend(loc='upper left', fontsize=8)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'${x:.0f}'))
    ax.grid(True, alpha=0.3)

axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
axes[-1].xaxis.set_major_locator(mdates.YearLocator(2))
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(SAVE_DIR + "chart1_price_with_signals.png", dpi=150, bbox_inches='tight')
plt.close()
print("\nSaved: chart1_price_with_signals.png")

# ── Chart 2: Forward return bar charts by horizon ──────────────────────────────
fig, axes = plt.subplots(2, 5, figsize=(22, 8))
fig.suptitle("Mean Forward Returns After MDY+IWM ATH Breakout / QQQ+SPY Lagging\n"
             "(All signals vs Q-end zone signals vs Non Q-end signals)",
             fontsize=13, fontweight='bold')

hz_list = list(HORIZONS.keys())
tickers = list(close.columns)

for col_i, hz in enumerate(hz_list):
    for row_i, ticker in enumerate(["MDY", "IWM"]):  # top row: small/mid
        ax = axes[row_i][col_i]
        all_r  = fwd_rets[ticker][hz]["fwd_ret"]
        qe_r   = qend_fwd[ticker][hz]["fwd_ret"] if len(qend_dates) > 0 else pd.Series(dtype=float)
        nqe_r  = nqend_fwd[ticker][hz]["fwd_ret"] if len(non_qend_dates) > 0 else pd.Series(dtype=float)
        means  = [all_r.mean()*100, qe_r.mean()*100 if len(qe_r)>0 else 0,
                  nqe_r.mean()*100 if len(nqe_r)>0 else 0]
        ns     = [len(all_r), len(qe_r), len(nqe_r)]
        bar_colors = ['steelblue', 'firebrick', 'seagreen']
        bars = ax.bar(["All", "Q-end", "Non-Q"], means, color=bar_colors, alpha=0.85, width=0.5)
        for bar, n, m in zip(bars, ns, means):
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height() + (0.1 if m >= 0 else -0.4),
                    f'{m:.1f}%\n(n={n})', ha='center', va='bottom', fontsize=7.5)
        ax.axhline(0, color='black', lw=0.8)
        ax.set_title(f"{ticker}  {hz}", fontsize=9, fontweight='bold')
        ax.set_ylabel("Mean Return (%)" if col_i == 0 else "", fontsize=8)
        ax.grid(True, alpha=0.3, axis='y')

# Bottom row: win rates
for col_i, hz in enumerate(hz_list):
    ax = axes[1][col_i]
    ax.clear()
    for row_i, ticker in enumerate(["QQQ", "SPY"]):
        all_r  = fwd_rets[ticker][hz]["fwd_ret"]
        qe_r   = qend_fwd[ticker][hz]["fwd_ret"] if len(qend_dates) > 0 else pd.Series(dtype=float)
        nqe_r  = nqend_fwd[ticker][hz]["fwd_ret"] if len(non_qend_dates) > 0 else pd.Series(dtype=float)
        means  = [all_r.mean()*100, qe_r.mean()*100 if len(qe_r)>0 else 0,
                  nqe_r.mean()*100 if len(nqe_r)>0 else 0]
        ns     = [len(all_r), len(qe_r), len(nqe_r)]
        bar_colors = ['steelblue', 'firebrick', 'seagreen']
        x_pos = np.arange(3) + row_i*3.5
        bars = ax.bar(x_pos, means, color=bar_colors, alpha=0.85, width=0.5)
        for bar, n, m in zip(bars, ns, means):
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height() + (0.05 if m >= 0 else -0.35),
                    f'{m:.1f}%\n(n={n})', ha='center', va='bottom', fontsize=7)
        ax.set_xticks(list(np.arange(3)) + list(np.arange(3)+3.5))
        ax.set_xticklabels(["All","Q","NQ","All","Q","NQ"], fontsize=7)
    ax.axhline(0, color='black', lw=0.8)
    ax.set_title(f"QQQ/SPY  {hz}", fontsize=9, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')
    ax.set_ylabel("Mean Return (%)" if col_i == 0 else "", fontsize=8)

plt.tight_layout()
plt.savefig(SAVE_DIR + "chart2_forward_returns_by_horizon.png", dpi=150, bbox_inches='tight')
plt.close()
print("Saved: chart2_forward_returns_by_horizon.png")

# ── Chart 3: Win-rate heat map ─────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(16, 5))
fig.suptitle("Win Rates (% Weeks with Positive Forward Return)\nAfter MDY+IWM ATH Breakout / QQQ+SPY Lagging",
             fontsize=12, fontweight='bold')

subsets = [
    ("All Signals",       signal_dates),
    ("Q-End Zone (4wk)",  qend_dates),
    ("Non Q-End",         non_qend_dates),
]
tickers_order = ["MDY", "IWM", "QQQ", "SPY"]
hz_order = list(HORIZONS.keys())

for ax, (title, dates_sub) in zip(axes, subsets):
    matrix = np.zeros((len(tickers_order), len(hz_order)))
    n_mat  = np.zeros_like(matrix, dtype=int)
    for ri, t in enumerate(tickers_order):
        for ci, hz in enumerate(hz_order):
            s = fwd_rets[t][hz]["fwd_ret"]
            s_sub = s[s.index.isin(dates_sub)]
            matrix[ri, ci] = s_sub.mean() * 100 if len(s_sub) > 0 else 0
            n_mat[ri, ci] = len(s_sub)
    im = ax.imshow(matrix, cmap='RdYlGn', aspect='auto', vmin=-5, vmax=10)
    ax.set_xticks(range(len(hz_order)))
    ax.set_xticklabels(hz_order, fontsize=10)
    ax.set_yticks(range(len(tickers_order)))
    ax.set_yticklabels(tickers_order, fontsize=11, fontweight='bold')
    ax.set_title(f"{title}\n(n={len(dates_sub)} signals)", fontsize=10, fontweight='bold')
    for ri in range(len(tickers_order)):
        for ci in range(len(hz_order)):
            val = matrix[ri, ci]
            n = n_mat[ri, ci]
            ax.text(ci, ri, f"{val:+.1f}%\n(n={n})",
                    ha='center', va='center', fontsize=8,
                    color='black' if -3 < val < 7 else 'white')
    plt.colorbar(im, ax=ax, label="Mean Fwd Return %", shrink=0.8)

plt.tight_layout()
plt.savefig(SAVE_DIR + "chart3_return_heatmap.png", dpi=150, bbox_inches='tight')
plt.close()
print("Saved: chart3_return_heatmap.png")

# ── Chart 4: Distribution of 4-week forward returns ───────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle("Distribution of 4-Week Forward Returns After Signal\n"
             "(Blue=All  |  Red=Q-end  |  Green=Non Q-end)",
             fontsize=13, fontweight='bold')

for ax, ticker in zip(axes.flat, tickers_order):
    all_r  = fwd_rets[ticker]["4w"]["fwd_ret"] * 100
    qe_r   = (qend_fwd[ticker]["4w"]["fwd_ret"] * 100 if len(qend_dates) > 0
               else pd.Series(dtype=float))
    nqe_r  = (nqend_fwd[ticker]["4w"]["fwd_ret"] * 100 if len(non_qend_dates) > 0
               else pd.Series(dtype=float))

    bins = np.linspace(all_r.min()-2, all_r.max()+2, 25)
    ax.hist(all_r, bins=bins, alpha=0.5, color='steelblue', label=f'All (n={len(all_r)})', density=True)
    if len(qe_r) > 0:
        ax.hist(qe_r, bins=bins, alpha=0.6, color='firebrick',
                label=f'Q-end (n={len(qe_r)})', density=True)
    if len(nqe_r) > 0:
        ax.hist(nqe_r, bins=bins, alpha=0.5, color='seagreen',
                label=f'Non-Q (n={len(nqe_r)})', density=True)
    ax.axvline(all_r.mean(), color='steelblue', lw=2, ls='--',
               label=f'Mean={all_r.mean():.1f}%')
    ax.axvline(0, color='black', lw=1)
    ax.set_title(f"{ticker} — 4-Week Forward Return Distribution", fontsize=10, fontweight='bold')
    ax.set_xlabel("4-Week Return (%)")
    ax.set_ylabel("Density")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(SAVE_DIR + "chart4_distribution_4w.png", dpi=150, bbox_inches='tight')
plt.close()
print("Saved: chart4_distribution_4w.png")

# ── Chart 5: Quarter calendar of signals ──────────────────────────────────────
fig, ax = plt.subplots(figsize=(14, 6))
fig.suptitle("Signal Calendar: When in the Quarter Do MDY+IWM ATH Breakouts Occur?\n"
             "(Each quarter = 13 weeks; 0 = quarter start, 13 = quarter end)",
             fontsize=12, fontweight='bold')

def week_in_quarter(dt):
    """0-indexed week within the current quarter (0=first week, ~12=last week)."""
    qstart_month = {1:1, 2:1, 3:1, 4:4, 5:4, 6:4, 7:7, 8:7, 9:7, 10:10, 11:10, 12:10}[dt.month]
    qstart = pd.Timestamp(dt.year, qstart_month, 1)
    return int((dt - qstart).days / 7)

week_positions = [week_in_quarter(d) for d in signal_dates]
qend_positions = [week_in_quarter(d) for d in qend_dates]

ax.hist(week_positions, bins=range(0, 15), alpha=0.7, color='steelblue',
        edgecolor='white', label=f'All signals (n={len(signal_dates)})')
if qend_positions:
    ax.hist(qend_positions, bins=range(0, 15), alpha=0.8, color='firebrick',
            edgecolor='white', label=f'Q-end signals (n={len(qend_dates)})')

ax.axvspan(9, 13, alpha=0.12, color='gold', label='Final 4 weeks of quarter')
ax.set_xlabel("Week Number Within Quarter (0=Q-start, 12=Q-end)", fontsize=11)
ax.set_ylabel("Number of Signals", fontsize=11)
ax.set_xticks(range(0, 14))
ax.set_xticklabels([f"Wk {i}" for i in range(14)], fontsize=8, rotation=45)
ax.legend(fontsize=10)
ax.grid(True, alpha=0.3, axis='y')
plt.tight_layout()
plt.savefig(SAVE_DIR + "chart5_signal_calendar.png", dpi=150, bbox_inches='tight')
plt.close()
print("Saved: chart5_signal_calendar.png")

# ── Chart 6: Cumulative return paths after signal ─────────────────────────────
fig, axes = plt.subplots(1, 4, figsize=(20, 6))
fig.suptitle("Average Cumulative Return Path (Weeks 0–13) After MDY+IWM ATH Breakout Signal\n"
             "Blue=All  |  Red dashed=Q-end zone  |  Green dashed=Non-Q",
             fontsize=12, fontweight='bold')

for ax, ticker in zip(axes, tickers_order):
    paths_all, paths_qe, paths_nqe = [], [], []
    for d in signal_dates:
        loc = close.index.get_loc(d)
        if loc + 13 < len(close):
            path = close[ticker].iloc[loc:loc+14] / close[ticker].iloc[loc] - 1
            path.index = range(len(path))
            paths_all.append(path)
            if d in qend_dates:
                paths_qe.append(path)
            else:
                paths_nqe.append(path)

    if paths_all:
        df_all = pd.DataFrame(paths_all)
        mean_all = df_all.mean()
        ci95 = df_all.std() * 1.96 / np.sqrt(len(df_all))
        ax.fill_between(mean_all.index, (mean_all-ci95)*100, (mean_all+ci95)*100,
                        alpha=0.15, color='steelblue')
        ax.plot(mean_all.index, mean_all*100, color='steelblue', lw=2,
                label=f'All (n={len(paths_all)})')

    if paths_qe:
        df_qe = pd.DataFrame(paths_qe)
        ax.plot(df_qe.mean().index, df_qe.mean()*100, color='firebrick', lw=2.5,
                ls='--', label=f'Q-end (n={len(paths_qe)})', zorder=5)

    if paths_nqe:
        df_nqe = pd.DataFrame(paths_nqe)
        ax.plot(df_nqe.mean().index, df_nqe.mean()*100, color='seagreen', lw=2,
                ls='--', label=f'Non-Q (n={len(paths_nqe)})', zorder=4)

    ax.axhline(0, color='black', lw=0.8)
    ax.set_title(f"{ticker}", fontsize=12, fontweight='bold')
    ax.set_xlabel("Weeks After Signal")
    ax.set_ylabel("Cum. Return (%)" if ticker == "MDY" else "")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(range(0, 14))

plt.tight_layout()
plt.savefig(SAVE_DIR + "chart6_cumulative_paths.png", dpi=150, bbox_inches='tight')
plt.close()
print("Saved: chart6_cumulative_paths.png")

# ─── 11. ANALYTICAL SUMMARY ───────────────────────────────────────────────────
print("\n" + "═"*80)
print("  QUANT SUMMARY — MDY/IWM ATH BREAKOUT WHILE QQQ/SPY LAG")
print("═"*80)

# Best stats for the report
for hz in ["4w", "8w", "13w"]:
    mdy_all   = fwd_rets["MDY"][hz]["fwd_ret"]
    iwm_all   = fwd_rets["IWM"][hz]["fwd_ret"]
    qqq_all   = fwd_rets["QQQ"][hz]["fwd_ret"]
    spy_all   = fwd_rets["SPY"][hz]["fwd_ret"]
    print(f"\n  {hz} FORWARD RETURNS — ALL SIGNALS (n={len(mdy_all)})")
    for t, s in [("MDY",mdy_all),("IWM",iwm_all),("QQQ",qqq_all),("SPY",spy_all)]:
        print(f"    {t}: mean={s.mean()*100:+.1f}%  med={s.median()*100:+.1f}%  "
              f"win={s.gt(0).mean()*100:.0f}%  stdev={s.std()*100:.1f}%")

if len(qend_dates) > 0:
    print(f"\n  4w FORWARD RETURNS — Q-END ZONE SIGNALS (n={len(qend_dates)})")
    for t in tickers_order:
        s = qend_fwd[t]["4w"]["fwd_ret"]
        if len(s) > 0:
            print(f"    {t}: mean={s.mean()*100:+.1f}%  med={s.median()*100:+.1f}%  "
                  f"win={s.gt(0).mean()*100:.0f}%")

    print(f"\n  13w FORWARD RETURNS — Q-END ZONE SIGNALS (n={len(qend_dates)})")
    for t in tickers_order:
        s = qend_fwd[t]["13w"]["fwd_ret"]
        if len(s) > 0:
            print(f"    {t}: mean={s.mean()*100:+.1f}%  med={s.median()*100:+.1f}%  "
                  f"win={s.gt(0).mean()*100:.0f}%")

print("\n  ⚠  N-counts are small — treat all figures as directional, not definitive.")
print("  Study covers ~19 years of weekly data (2007–2026).")
print("  Signal definition: MDY+IWM close at new rolling ATH after ≥3 weeks below ATH;")
print("  simultaneously QQQ and SPY are NOT at their rolling ATH.")
print("═"*80)
print("\nAll charts saved to /home/user/alpha-query-monitor/studies/")
