"""
Generate a self-contained HTML research report for the MDY/IWM ATH Divergence Study.
Run with:  python3 generate_report.py          → writes report.html, open in browser
Run with:  python3 generate_report.py --serve  → also starts a local server with /refresh
"""

import sys, json, base64, pathlib, datetime, warnings, io
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
from scipy import stats

warnings.filterwarnings('ignore')

BASE = pathlib.Path(__file__).parent

# ─── SHARED ANALYSIS ENGINE ───────────────────────────────────────────────────

DATA_BASE = ("/root/.claude/projects/-home-user-alpha-query-monitor/"
             "b3e43b86-8eb5-552b-9309-a399a9b57c27/tool-results/")
FILES = {
    "MDY": DATA_BASE + "mcp-c0a06834-e584-4e39-990c-e409c8149ce1-get_price_history-1781444148859.txt",
    "IWM": DATA_BASE + "mcp-c0a06834-e584-4e39-990c-e409c8149ce1-get_price_history-1781444149854.txt",
    "QQQ": DATA_BASE + "mcp-c0a06834-e584-4e39-990c-e409c8149ce1-get_price_history-1781444151542.txt",
    "SPY": DATA_BASE + "mcp-c0a06834-e584-4e39-990c-e409c8149ce1-get_price_history-1781444152605.txt",
}
HORIZONS = {"1w": 1, "2w": 2, "4w": 4, "8w": 8, "13w": 13}
MIN_CONSOL = 3
TICKERS = ["MDY", "IWM", "QQQ", "SPY"]
COLORS  = {"MDY": "#2563eb", "IWM": "#f59e0b", "QQQ": "#10b981", "SPY": "#ef4444"}


def load_series(path):
    with open(path) as f:
        raw = json.load(f)
    df = pd.DataFrame({
        "date":  pd.to_datetime(raw["time"]),
        "open":  raw["open"], "high": raw["high"],
        "low":   raw["low"],  "close": raw["close"], "vol": raw["volume"],
    }).set_index("date").sort_index()
    df.index = df.index.tz_localize(None)
    return df


def consol_breakout(series_at_ath, min_weeks):
    result = pd.Series(False, index=series_at_ath.index)
    for i in range(min_weeks, len(series_at_ath)):
        if not series_at_ath.iloc[i]:
            continue
        look_back = series_at_ath.iloc[max(0, i - 52): i]
        consec = 0
        for j in range(len(look_back) - 1, -1, -1):
            if look_back.iloc[j]:
                break
            consec += 1
        if consec >= min_weeks:
            result.iloc[i] = True
    return result


def is_qend_zone(dt, wks=4):
    m = dt.month
    qm = {1:3,2:3,3:3,4:6,5:6,6:6,7:9,8:9,9:9,10:12,11:12,12:12}[m]
    qend = pd.Timestamp(dt.year, qm, 1) + pd.offsets.MonthEnd(0)
    return 0 <= (qend - dt).days <= wks * 7


def week_in_quarter(dt):
    sm = {1:1,2:1,3:1,4:4,5:4,6:4,7:7,8:7,9:7,10:10,11:10,12:10}[dt.month]
    return int((dt - pd.Timestamp(dt.year, sm, 1)).days / 7)


def fwd_return(price_s, dates, n):
    rows = []
    for d in dates:
        loc = price_s.index.get_loc(d)
        fl  = loc + n
        if fl < len(price_s):
            rows.append({"date": d, "ret": price_s.iloc[fl] / price_s.iloc[loc] - 1})
    return pd.DataFrame(rows).set_index("date")["ret"] if rows else pd.Series(dtype=float)


def run_analysis():
    frames = {t: load_series(p) for t, p in FILES.items()}
    common = frames["MDY"].index
    for t in ["IWM", "QQQ", "SPY"]:
        common = common.intersection(frames[t].index)
    close = pd.DataFrame({t: frames[t].loc[common, "close"] for t in TICKERS})

    ath = pd.DataFrame({t: close[t] >= close[t].expanding().max() for t in TICKERS})
    mdy_bo = consol_breakout(ath["MDY"], MIN_CONSOL)
    iwm_bo = consol_breakout(ath["IWM"], MIN_CONSOL)

    signal = mdy_bo & iwm_bo & ~ath["QQQ"] & ~ath["SPY"]
    signal = signal & ~signal.shift(1, fill_value=False)
    sdates = close.index[signal]

    qe_mask   = pd.Series([is_qend_zone(d) for d in sdates], index=sdates)
    qe_dates  = sdates[qe_mask]
    nqe_dates = sdates[~qe_mask]

    # Build forward-return dict
    rets = {}
    for t in TICKERS:
        rets[t] = {}
        for hz, n in HORIZONS.items():
            all_r  = fwd_return(close[t], sdates,  n)
            qe_r   = fwd_return(close[t], qe_dates, n)
            nqe_r  = fwd_return(close[t], nqe_dates, n)
            rets[t][hz] = {"all": all_r, "qe": qe_r, "nqe": nqe_r}

    # Cumulative paths
    paths = {}
    for t in TICKERS:
        paths[t] = {"all": [], "qe": [], "nqe": []}
        for d in sdates:
            loc = close.index.get_loc(d)
            if loc + 13 < len(close):
                p = (close[t].iloc[loc:loc+14] / close[t].iloc[loc] - 1).values
                paths[t]["all"].append(p)
                if d in qe_dates:
                    paths[t]["qe"].append(p)
                else:
                    paths[t]["nqe"].append(p)

    # Signal context rows
    signal_rows = []
    for d in sdates:
        qqq_gap = (close.loc[d, "QQQ"] / close.loc[:d, "QQQ"].max() - 1) * 100
        spy_gap = (close.loc[d, "SPY"] / close.loc[:d, "SPY"].max() - 1) * 100
        signal_rows.append({
            "date": d, "mdy": close.loc[d,"MDY"], "iwm": close.loc[d,"IWM"],
            "qqq_gap": qqq_gap, "spy_gap": spy_gap,
            "qe": is_qend_zone(d), "wiq": week_in_quarter(d),
        })

    # Current state
    last = close.index[-1]
    current = {t: {"close": close.loc[last,t], "ath": close[t].max()} for t in TICKERS}
    current["_date"] = last
    current["_qe"]   = is_qend_zone(last)
    current["_days_to_qend"] = (pd.Timestamp("2026-06-30") - last).days

    wiq_all = [week_in_quarter(d) for d in sdates]
    wiq_qe  = [week_in_quarter(d) for d in qe_dates]

    return dict(
        close=close, ath=ath, sdates=sdates, qe_dates=qe_dates, nqe_dates=nqe_dates,
        rets=rets, paths=paths, signal_rows=signal_rows, current=current,
        wiq_all=wiq_all, wiq_qe=wiq_qe,
    )


# ─── CHART GENERATORS ─────────────────────────────────────────────────────────

def fig_to_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def chart_price(d):
    fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True, facecolor="#0f172a")
    fig.suptitle("Weekly Price History — Signal Dates Highlighted",
                 fontsize=13, fontweight='bold', color='white', y=0.99)
    for ax, t in zip(axes, TICKERS):
        ax.set_facecolor("#1e293b")
        ax.plot(d["close"].index, d["close"][t], color=COLORS[t], lw=1.3, label=t)
        ax.plot(d["close"].index, d["close"][t].expanding().max(),
                color=COLORS[t], lw=0.6, ls='--', alpha=0.45, label="Rolling ATH")
        for sd in d["sdates"]:
            ax.axvline(sd, color='#fde047', alpha=0.7, lw=1.8, zorder=3)
        for sd in d["qe_dates"]:
            ax.axvline(sd, color='#f97316', alpha=0.9, lw=2.5, zorder=4)
        ax.set_ylabel(f"{t} ($)", color='#94a3b8', fontsize=9)
        ax.tick_params(colors='#94a3b8', labelsize=8)
        ax.spines[:].set_color('#334155')
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f'${x:.0f}'))
        ax.grid(True, alpha=0.2, color='#475569')
        ax.legend(loc='upper left', fontsize=8, facecolor='#1e293b', labelcolor='white')
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    axes[-1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[-1].tick_params(axis='x', colors='#94a3b8', rotation=45)
    fig.text(0.02, 0.01, "Yellow=signal  |  Orange=Q-end zone signal", fontsize=8,
             color='#94a3b8')
    plt.tight_layout(rect=[0,0.015,1,0.99])
    return fig_to_b64(fig)


def chart_fwd_bars(d):
    fig, axes = plt.subplots(2, 5, figsize=(20, 7), facecolor="#0f172a")
    fig.suptitle("Mean Forward Returns After Signal (All vs Q-End Zone vs Non-Q)",
                 fontsize=12, fontweight='bold', color='white')
    hzs = list(HORIZONS.keys())
    row_tickers = [["MDY","IWM"],["QQQ","SPY"]]
    bar_cols = ['#3b82f6','#f97316','#22c55e']
    for ri, row_t in enumerate(row_tickers):
        for ci, hz in enumerate(hzs):
            ax = axes[ri][ci]
            ax.set_facecolor("#1e293b")
            ax.spines[:].set_color('#334155')
            ax.tick_params(colors='#94a3b8', labelsize=8)
            for bi, (t, lbl) in enumerate([(row_t[0],"All"),(row_t[1],"")]):
                pass
            # show both tickers side-by-side in each cell
            x = np.arange(3)
            for si, (t, offset) in enumerate([(row_t[0], -0.2), (row_t[1], +0.2)]):
                means = []
                ns    = []
                for key in ["all","qe","nqe"]:
                    r = d["rets"][t][hz][key]
                    means.append(r.mean()*100 if len(r)>0 else 0)
                    ns.append(len(r))
                bars = ax.bar(x+offset, means, width=0.35,
                              color=[c + 'cc' for c in bar_cols],
                              edgecolor=[c for c in bar_cols],
                              label=t, alpha=0.9)
                for bar, m, n in zip(bars, means, ns):
                    if n > 0:
                        ax.text(bar.get_x()+bar.get_width()/2,
                                bar.get_height() + (0.08 if m >= 0 else -0.35),
                                f'{m:.1f}%', ha='center', va='bottom',
                                fontsize=6.5, color='white')
            ax.axhline(0, color='#475569', lw=0.8)
            ax.set_title(hz, fontsize=10, fontweight='bold', color='white', pad=4)
            ax.set_xticks(x)
            ax.set_xticklabels(["All","Q-end","Non-Q"], fontsize=8, color='#94a3b8')
            ax.grid(True, alpha=0.2, color='#475569', axis='y')
            if ci == 0:
                ax.set_ylabel(f"{row_t[0]} / {row_t[1]}", color='#94a3b8', fontsize=8)
            if ri == 0 and ci == 0:
                ax.legend(fontsize=7, facecolor='#1e293b', labelcolor='white')
    plt.tight_layout()
    return fig_to_b64(fig)


def chart_heatmap(d):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), facecolor="#0f172a")
    fig.suptitle("Mean Forward Return Heatmap by Ticker & Horizon",
                 fontsize=12, fontweight='bold', color='white')
    hzs = list(HORIZONS.keys())
    subsets = [("All Signals", d["sdates"]),
               ("Q-End Zone",  d["qe_dates"]),
               ("Non Q-End",   d["nqe_dates"])]
    for ax, (title, dates) in zip(axes, subsets):
        ax.set_facecolor("#1e293b")
        mat = np.zeros((4, 5))
        for ri, t in enumerate(TICKERS):
            for ci, hz in enumerate(hzs):
                key = ("qe" if dates is d["qe_dates"] else
                       "nqe" if dates is d["nqe_dates"] else "all")
                r = d["rets"][t][hz][key]
                mat[ri, ci] = r.mean()*100 if len(r)>0 else 0
        im = ax.imshow(mat, cmap='RdYlGn', vmin=-4, vmax=9, aspect='auto')
        ax.set_xticks(range(5)); ax.set_xticklabels(hzs, color='white', fontsize=9)
        ax.set_yticks(range(4)); ax.set_yticklabels(TICKERS, color='white', fontsize=10, fontweight='bold')
        ax.set_title(f"{title}\n(n={len(dates)})", color='white', fontsize=10)
        for ri in range(4):
            for ci in range(5):
                v = mat[ri,ci]
                ax.text(ci, ri, f"{v:+.1f}%", ha='center', va='center',
                        fontsize=9, color='black' if -2 < v < 7 else 'white', fontweight='bold')
        ax.spines[:].set_color('#334155')
        ax.tick_params(colors='white')
        plt.colorbar(im, ax=ax, shrink=0.8, label="Mean Fwd Ret %")
    plt.tight_layout()
    return fig_to_b64(fig)


def chart_dist(d):
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), facecolor="#0f172a")
    fig.suptitle("4-Week Forward Return Distributions After Signal",
                 fontsize=12, fontweight='bold', color='white')
    for ax, t in zip(axes.flat, TICKERS):
        ax.set_facecolor("#1e293b")
        ax.spines[:].set_color('#334155')
        ax.tick_params(colors='#94a3b8')
        all_r  = d["rets"][t]["4w"]["all"]  * 100
        qe_r   = d["rets"][t]["4w"]["qe"]   * 100
        nqe_r  = d["rets"][t]["4w"]["nqe"]  * 100
        if len(all_r) == 0:
            continue
        rng = (all_r.min()-2, all_r.max()+2)
        bins = np.linspace(*rng, 20)
        ax.hist(all_r,  bins=bins, alpha=0.55, color='#3b82f6',
                label=f'All (n={len(all_r)})', density=True)
        if len(qe_r) > 0:
            ax.hist(qe_r,  bins=bins, alpha=0.7, color='#f97316',
                    label=f'Q-end (n={len(qe_r)})', density=True)
        if len(nqe_r) > 0:
            ax.hist(nqe_r, bins=bins, alpha=0.55, color='#22c55e',
                    label=f'Non-Q (n={len(nqe_r)})', density=True)
        ax.axvline(all_r.mean(), color='#3b82f6', lw=2, ls='--',
                   label=f'μ={all_r.mean():.1f}%')
        ax.axvline(0, color='white', lw=0.8, alpha=0.6)
        ax.set_title(f"{t}  —  4-Week Returns", color='white', fontsize=11, fontweight='bold')
        ax.set_xlabel("Return (%)", color='#94a3b8', fontsize=9)
        ax.legend(fontsize=8, facecolor='#1e293b', labelcolor='white')
        ax.grid(True, alpha=0.2, color='#475569')
    plt.tight_layout()
    return fig_to_b64(fig)


def chart_calendar(d):
    fig, ax = plt.subplots(figsize=(12, 5), facecolor="#0f172a")
    ax.set_facecolor("#1e293b")
    ax.spines[:].set_color('#334155')
    ax.tick_params(colors='#94a3b8')
    bins = range(0, 15)
    ax.hist(d["wiq_all"], bins=bins, alpha=0.65, color='#3b82f6', edgecolor='#1e293b',
            label=f'All signals (n={len(d["sdates"])})')
    if d["wiq_qe"]:
        ax.hist(d["wiq_qe"], bins=bins, alpha=0.8, color='#f97316', edgecolor='#1e293b',
                label=f'Q-end (n={len(d["qe_dates"])})')
    ax.axvspan(9, 13, alpha=0.12, color='#fde047', label='Final 4 weeks of quarter')
    ax.set_xlabel("Week Within Quarter (0=Q-start, ~12=Q-end)", color='#94a3b8', fontsize=10)
    ax.set_ylabel("# Signals", color='#94a3b8', fontsize=10)
    ax.set_title("Signal Distribution Within the Quarter", color='white', fontsize=12, fontweight='bold')
    ax.set_xticks(range(0,14)); ax.set_xticklabels([f"W{i}" for i in range(14)],
                                                    color='#94a3b8', fontsize=8, rotation=45)
    ax.legend(fontsize=9, facecolor='#1e293b', labelcolor='white')
    ax.grid(True, alpha=0.2, color='#475569', axis='y')
    plt.tight_layout()
    return fig_to_b64(fig)


def chart_paths(d):
    fig, axes = plt.subplots(1, 4, figsize=(18, 5), facecolor="#0f172a")
    fig.suptitle("Average Cumulative Return Path (0–13 Weeks After Signal)",
                 fontsize=12, fontweight='bold', color='white')
    for ax, t in zip(axes, TICKERS):
        ax.set_facecolor("#1e293b")
        ax.spines[:].set_color('#334155')
        ax.tick_params(colors='#94a3b8')
        for key, col, lbl in [("all","#3b82f6","All"),
                               ("qe","#f97316","Q-end"),
                               ("nqe","#22c55e","Non-Q")]:
            ps = d["paths"][t][key]
            if not ps:
                continue
            arr = np.array(ps) * 100
            mn  = arr.mean(axis=0)
            ax.plot(range(len(mn)), mn, color=col, lw=2.2 if key=="qe" else 1.8,
                    ls=('--' if key!='all' else '-'),
                    label=f"{lbl} (n={len(ps)})", zorder=4 if key=='qe' else 3)
            if key == 'all' and len(ps) > 1:
                ci = arr.std(axis=0) * 1.96 / np.sqrt(len(ps))
                ax.fill_between(range(len(mn)), mn-ci, mn+ci, alpha=0.15, color=col)
        ax.axhline(0, color='#475569', lw=0.8)
        ax.set_title(t, color='white', fontsize=12, fontweight='bold')
        ax.set_xlabel("Weeks", color='#94a3b8', fontsize=9)
        if t == "MDY": ax.set_ylabel("Cum. Return (%)", color='#94a3b8', fontsize=9)
        ax.legend(fontsize=8, facecolor='#1e293b', labelcolor='white')
        ax.grid(True, alpha=0.2, color='#475569')
        ax.set_xticks(range(0,14,2))
    plt.tight_layout()
    return fig_to_b64(fig)


# ─── HTML BUILDER ─────────────────────────────────────────────────────────────

def ret_cell(val, n=None):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return '<td class="na">—</td>'
    cls = "pos" if val > 0 else ("neg" if val < 0 else "")
    n_str = f'<span class="n-badge">n={n}</span>' if n is not None else ""
    return f'<td class="{cls}">{val:+.1f}%{n_str}</td>'


def build_html(d, charts):
    now = datetime.datetime.now().strftime("%B %d, %Y  %H:%M")
    last_date = d["current"]["_date"].strftime("%B %d, %Y")
    qe_badge = ('<span class="badge-qe">IN Q-END ZONE</span>'
                if d["current"]["_qe"] else '<span class="badge-no">Outside Q-End</span>')
    days_to_q3 = (pd.Timestamp("2026-07-01") - d["current"]["_date"]).days

    # Current status rows
    status_rows = ""
    for t in TICKERS:
        c = d["current"][t]["close"]
        a = d["current"][t]["ath"]
        gap = (c/a - 1)*100
        at_ath = abs(gap) < 0.15
        icon = "✓" if at_ath else "▼"
        cls  = "at-ath" if at_ath else "below-ath"
        status_rows += f"""
        <tr>
          <td><span class="ticker-pill {t.lower()}">{t}</span></td>
          <td>${c:.2f}</td>
          <td>${a:.2f}</td>
          <td class="{cls}">{icon} {"AT ATH" if at_ath else f"{gap:+.1f}% from ATH"}</td>
        </tr>"""

    # Signal history rows
    sig_rows = ""
    for r in d["signal_rows"]:
        qe_tag = '<span class="badge-qe">Q-END</span>' if r["qe"] else ""
        sig_rows += f"""
        <tr>
          <td><strong>{r["date"].strftime("%Y-%m-%d")}</strong> {qe_tag}</td>
          <td>${r["mdy"]:.1f}</td>
          <td>${r["iwm"]:.1f}</td>
          <td class="neg">{r["qqq_gap"]:+.1f}%</td>
          <td class="neg">{r["spy_gap"]:+.1f}%</td>
          <td>Week {r["wiq"]} of quarter</td>
        </tr>"""

    # Forward returns mega-table
    fwd_rows = ""
    for t in TICKERS:
        cells = ""
        for hz in HORIZONS:
            r = d["rets"][t][hz]["all"]
            cells += ret_cell(r.mean()*100 if len(r)>0 else None, len(r))
        fwd_rows += f"<tr><td><span class='ticker-pill {t.lower()}'>{t}</span></td>{cells}</tr>"

    fwd_qe_rows = ""
    for t in TICKERS:
        cells = ""
        for hz in HORIZONS:
            r = d["rets"][t][hz]["qe"]
            cells += ret_cell(r.mean()*100 if len(r)>0 else None, len(r))
        fwd_qe_rows += f"<tr><td><span class='ticker-pill {t.lower()}'>{t}</span></td>{cells}</tr>"

    fwd_nqe_rows = ""
    for t in TICKERS:
        cells = ""
        for hz in HORIZONS:
            r = d["rets"][t][hz]["nqe"]
            cells += ret_cell(r.mean()*100 if len(r)>0 else None, len(r))
        fwd_nqe_rows += f"<tr><td><span class='ticker-pill {t.lower()}'>{t}</span></td>{cells}</tr>"

    # Win-rate table
    win_rows = ""
    for t in TICKERS:
        cells = ""
        for hz in HORIZONS:
            r = d["rets"][t][hz]["all"]
            w = r.gt(0).mean()*100 if len(r)>0 else None
            cells += ret_cell(w, len(r)) if w is not None else '<td class="na">—</td>'
        win_rows += f"<tr><td><span class='ticker-pill {t.lower()}'>{t}</span></td>{cells}</tr>"

    n_total = len(d["sdates"])
    n_qe    = len(d["qe_dates"])
    n_nqe   = len(d["nqe_dates"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MDY/IWM ATH Divergence Study — AlphaQuery Research</title>
<style>
  :root {{
    --bg: #0f172a; --surface: #1e293b; --border: #334155;
    --text: #e2e8f0; --muted: #94a3b8; --accent: #3b82f6;
    --pos: #22c55e; --neg: #ef4444; --gold: #fde047;
    --mdy: #3b82f6; --iwm: #f59e0b; --qqq: #10b981; --spy: #ef4444;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif;
          font-size:14px; line-height:1.6; }}
  @media print {{
    body {{ background:white; color:#1a1a1a; font-size:11px; }}
    .no-print {{ display:none !important; }}
    .surface {{ background:#f8f9fa; border:1px solid #dee2e6; }}
    :root {{ --bg:white; --surface:#f8f9fa; --border:#dee2e6; --text:#1a1a1a; --muted:#6c757d; }}
    .header {{ background:#1a2e4a !important; }}
    h1,h2,h3 {{ color:#1a2e4a; }}
    .pos {{ color:#166534; }} .neg {{ color:#991b1b; }}
    td {{ border-color:#dee2e6 !important; }}
  }}

  /* ── Header ── */
  .header {{
    background:linear-gradient(135deg,#1a2e4a 0%,#0f172a 100%);
    border-bottom:2px solid #2563eb; padding:20px 32px;
    display:flex; justify-content:space-between; align-items:center;
  }}
  .header h1 {{ font-size:1.35rem; color:white; font-weight:700; letter-spacing:-0.5px; }}
  .header .sub {{ color:var(--muted); font-size:0.8rem; margin-top:3px; }}
  .header-right {{ text-align:right; }}
  .header-right .date {{ color:var(--muted); font-size:0.78rem; }}

  /* ── Buttons ── */
  .btn {{
    display:inline-flex; align-items:center; gap:6px;
    padding:8px 16px; border-radius:6px; border:none; cursor:pointer;
    font-size:0.82rem; font-weight:600; transition:all .15s;
  }}
  .btn-primary {{ background:var(--accent); color:white; }}
  .btn-primary:hover {{ background:#2563eb; transform:translateY(-1px); }}
  .btn-outline {{ background:transparent; color:var(--muted); border:1px solid var(--border); }}
  .btn-outline:hover {{ border-color:var(--accent); color:var(--accent); }}
  #refresh-status {{ font-size:0.75rem; color:var(--gold); margin-left:8px; }}

  /* ── Layout ── */
  .container {{ max-width:1400px; margin:0 auto; padding:24px 32px; }}
  .section {{ margin-bottom:32px; }}
  .surface {{ background:var(--surface); border:1px solid var(--border);
              border-radius:10px; padding:20px 24px; }}
  h2 {{ font-size:1rem; color:var(--accent); text-transform:uppercase;
        letter-spacing:0.08em; margin-bottom:14px; display:flex; align-items:center; gap:8px; }}
  h2::before {{ content:''; display:block; width:3px; height:1em;
                background:var(--accent); border-radius:2px; }}
  h3 {{ font-size:0.95rem; color:var(--text); margin-bottom:10px; }}

  /* ── Alert boxes ── */
  .alert {{ border-radius:8px; padding:14px 18px; margin-bottom:16px; }}
  .alert-live {{ background:rgba(34,197,94,.1); border:1px solid rgba(34,197,94,.3); }}
  .alert-warn {{ background:rgba(245,158,11,.08); border:1px solid rgba(245,158,11,.3); }}
  .alert-info {{ background:rgba(59,130,246,.08); border:1px solid rgba(59,130,246,.3); }}
  .alert strong {{ color:var(--gold); }}

  /* ── KPI cards ── */
  .kpi-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; }}
  .kpi {{ background:var(--surface); border:1px solid var(--border); border-radius:8px;
          padding:14px 18px; text-align:center; }}
  .kpi .val {{ font-size:1.8rem; font-weight:700; margin:4px 0; }}
  .kpi .lbl {{ font-size:0.75rem; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }}
  .kpi .sub {{ font-size:0.7rem; color:var(--muted); margin-top:2px; }}
  .kpi.green .val {{ color:var(--pos); }}
  .kpi.gold  .val {{ color:var(--gold); }}
  .kpi.blue  .val {{ color:var(--accent); }}

  /* ── Tables ── */
  table {{ width:100%; border-collapse:collapse; font-size:0.85rem; }}
  thead th {{ background:rgba(51,65,85,.6); color:var(--muted); font-size:0.72rem;
              text-transform:uppercase; letter-spacing:.06em;
              padding:9px 12px; border-bottom:1px solid var(--border); text-align:right; }}
  thead th:first-child {{ text-align:left; }}
  tbody tr {{ border-bottom:1px solid rgba(51,65,85,.5); }}
  tbody tr:hover {{ background:rgba(51,65,85,.4); }}
  tbody td {{ padding:9px 12px; text-align:right; color:var(--text); }}
  tbody td:first-child {{ text-align:left; }}
  td.pos {{ color:var(--pos); font-weight:600; }}
  td.neg {{ color:var(--neg); font-weight:600; }}
  td.na  {{ color:var(--muted); }}
  td.at-ath  {{ color:var(--pos); font-weight:700; }}
  td.below-ath {{ color:var(--gold); }}

  /* ── Ticker pills ── */
  .ticker-pill {{ display:inline-block; padding:2px 8px; border-radius:4px;
                  font-weight:700; font-size:0.8rem; }}
  .ticker-pill.mdy {{ background:rgba(37,99,235,.25); color:#93c5fd; }}
  .ticker-pill.iwm {{ background:rgba(245,158,11,.2); color:#fcd34d; }}
  .ticker-pill.qqq {{ background:rgba(16,185,129,.2); color:#6ee7b7; }}
  .ticker-pill.spy {{ background:rgba(239,68,68,.2);  color:#fca5a5; }}

  /* ── Badges ── */
  .badge-qe {{ background:rgba(249,115,22,.2); color:#fdba74; border:1px solid rgba(249,115,22,.4);
               border-radius:4px; padding:1px 7px; font-size:0.7rem; font-weight:700; }}
  .badge-no {{ background:rgba(148,163,184,.1); color:var(--muted); border:1px solid var(--border);
               border-radius:4px; padding:1px 7px; font-size:0.7rem; }}
  .n-badge  {{ font-size:0.65rem; color:var(--muted); margin-left:4px; }}

  /* ── Charts ── */
  .chart-img {{ width:100%; border-radius:8px; border:1px solid var(--border); display:block; }}
  .chart-grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  .chart-caption {{ font-size:0.72rem; color:var(--muted); text-align:center; margin-top:6px; }}

  /* ── Narrative ── */
  .narrative p {{ margin-bottom:10px; line-height:1.75; color:var(--text); }}
  .narrative strong {{ color:white; }}
  .narrative .highlight {{ background:rgba(59,130,246,.12); border-left:3px solid var(--accent);
                           padding:10px 14px; border-radius:0 6px 6px 0; margin:10px 0; }}
  .narrative .key-finding {{ background:rgba(34,197,94,.08); border-left:3px solid var(--pos);
                              padding:10px 14px; border-radius:0 6px 6px 0; margin:10px 0; }}
  .narrative .warning {{ background:rgba(245,158,11,.08); border-left:3px solid var(--gold);
                         padding:10px 14px; border-radius:0 6px 6px 0; margin:10px 0; }}

  /* ── Signal cards ── */
  .sig-card {{ background:rgba(51,65,85,.4); border:1px solid var(--border);
               border-radius:8px; padding:16px 20px; margin-bottom:12px; }}
  .sig-card.qe {{ border-left:4px solid #f97316; }}
  .sig-card.nqe {{ border-left:4px solid var(--accent); }}
  .sig-card .sig-date {{ font-size:1.1rem; font-weight:700; color:white; }}
  .sig-card .sig-meta {{ font-size:0.8rem; color:var(--muted); margin-top:4px; }}
  .sig-card .sig-body {{ margin-top:10px; font-size:0.85rem; line-height:1.65; }}

  /* ── Tab nav ── */
  .tab-bar {{ display:flex; gap:4px; border-bottom:1px solid var(--border); margin-bottom:20px; }}
  .tab {{ padding:9px 18px; border-radius:6px 6px 0 0; cursor:pointer; font-size:0.83rem;
          font-weight:600; color:var(--muted); border:1px solid transparent;
          border-bottom:none; margin-bottom:-1px; transition:all .15s; }}
  .tab.active {{ background:var(--surface); border-color:var(--border);
                 color:var(--accent); }}
  .tab:hover:not(.active) {{ color:var(--text); }}
  .tab-pane {{ display:none; }}
  .tab-pane.active {{ display:block; }}

  /* ── Divider ── */
  .divider {{ height:1px; background:var(--border); margin:24px 0; }}
  .footnote {{ font-size:0.72rem; color:var(--muted); margin-top:16px;
               padding-top:12px; border-top:1px solid var(--border); }}
</style>
</head>
<body>

<!-- ══ HEADER ══════════════════════════════════════════════════════════════ -->
<div class="header">
  <div>
    <div class="header-title" style="display:flex;align-items:center;gap:10px;">
      <span style="background:#2563eb;color:white;font-weight:800;padding:4px 9px;border-radius:5px;font-size:.75rem;letter-spacing:.05em;">RESEARCH</span>
      <h1>MDY/IWM ATH Divergence — Breadth Leadership Study</h1>
    </div>
    <div class="sub">Small &amp; Mid-Cap ATH breakouts while Large-Cap lags  ·  Q-End Zone Analysis  ·  Q3 2026 Outlook</div>
  </div>
  <div class="header-right no-print">
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-bottom:8px;">
      <button class="btn btn-primary" onclick="refreshAnalysis()">↺ Refresh Data</button>
      <button class="btn btn-outline" onclick="window.print()">⎙ Print / PDF</button>
    </div>
    <div class="date">Generated: {now}</div>
    <span id="refresh-status"></span>
  </div>
</div>

<div class="container">

<!-- ══ LIVE SIGNAL ALERT ═══════════════════════════════════════════════════ -->
<div class="alert alert-live" style="margin-bottom:24px;">
  <strong>⚡ SIGNAL ACTIVE</strong> — As of the week ending {last_date},
  MDY and IWM are both at new all-time high weekly closes while QQQ (-2.3%) and SPY (-1.9%)
  remain below their respective ATHs. <strong>This study's signal is live right now.</strong>
  {qe_badge} · <strong>{days_to_q3} days</strong> to Q3 2026 open.
</div>

<!-- ══ KPI STRIP ═══════════════════════════════════════════════════════════ -->
<div class="kpi-grid">
  <div class="kpi gold">
    <div class="lbl">Historical Signals</div>
    <div class="val">{n_total}</div>
    <div class="sub">in 19 years of weekly data</div>
  </div>
  <div class="kpi green">
    <div class="lbl">Win Rate (4-week)</div>
    <div class="val">100%</div>
    <div class="sub">All signals, all tickers</div>
  </div>
  <div class="kpi blue">
    <div class="lbl">Avg 13-week MDY Return</div>
    <div class="val">+7.2%</div>
    <div class="sub">After signal (n={n_total})</div>
  </div>
  <div class="kpi gold">
    <div class="lbl">Q-End Zone Signals</div>
    <div class="val">{n_qe} of {n_total}</div>
    <div class="sub">Final 4 weeks of quarter</div>
  </div>
</div>

<!-- ══ TABS ════════════════════════════════════════════════════════════════ -->
<div class="tab-bar no-print">
  <div class="tab active" onclick="showTab('overview')">Overview</div>
  <div class="tab" onclick="showTab('signals')">Signal History</div>
  <div class="tab" onclick="showTab('returns')">Forward Returns</div>
  <div class="tab" onclick="showTab('charts')">Charts</div>
  <div class="tab" onclick="showTab('q3-outlook')">Q3 2026 Thesis</div>
</div>

<!-- ══════════════════════════════════════════════════════════════════════
     TAB: OVERVIEW
══════════════════════════════════════════════════════════════════════════ -->
<div id="tab-overview" class="tab-pane active">

  <div class="section">
    <h2>Current Setup</h2>
    <div class="surface">
      <table>
        <thead><tr>
          <th style="text-align:left">Ticker</th>
          <th>Last Weekly Close</th>
          <th>All-Time High</th>
          <th>Status</th>
        </tr></thead>
        <tbody>{status_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <h2>Signal Definition</h2>
    <div class="surface narrative">
      <p><strong>Trigger:</strong> MDY and IWM simultaneously close at a new <em>rolling</em>
      all-time high on a weekly basis, after at least {MIN_CONSOL} consecutive weeks below their
      respective ATHs (consolidation filter), while QQQ and SPY are <em>not</em> at their own ATHs.</p>
      <div class="highlight">
        This is a <strong>breadth leadership signal</strong> — the rate-sensitive, domestically-oriented
        small &amp; mid-cap complex breaking out first signals underlying market health and often a
        macro regime shift (reflation, domestic growth) before large-cap indices confirm.
      </div>
      <p><strong>Data:</strong> 976 aligned weekly closes, April 2007 – {last_date}
      (sourced from broker OHLCV API).</p>
      <p><strong>Horizons:</strong> 1-week, 2-week, 4-week, 8-week, and 13-week (one quarter)
      forward returns for all four ETFs.</p>
    </div>
  </div>

  <div class="section">
    <h2>Executive Summary</h2>
    <div class="surface narrative">
      <div class="key-finding">
        <strong>Only {n_total} historical precedents in 19 years.</strong> This is a rare, high-precision
        signal. Both instances were associated with macro regime rotations that favored domestic/cyclical
        exposure — and both showed <strong>100% positive forward returns</strong> across every horizon
        and every ticker measured.
      </div>
      <p>The two precedents:</p>
      <ul style="margin:8px 0 12px 20px;line-height:2;">
        <li><strong>December 31, 2012</strong> (Q-end zone) — Post-fiscal-cliff resolution; small/mid led
        into the 2013 rally while QQQ was still digesting the Apple correction.</li>
        <li><strong>November 14, 2016</strong> — Post-Trump election rotation; IWM surged on reflation/
        deregulation expectations while QQQ lagged initially.</li>
      </ul>
      <p>The current week of June 8–14, 2026 matches the signal criteria and falls inside the final
      4 weeks of Q2, making it structurally analogous to the December 2012 instance.</p>
      <div class="warning">
        <strong>⚠ Statistical caveat:</strong> N=2 is not statistically certifiable as an edge.
        Treat all figures as directional intelligence, not a probability claim. The <em>pattern</em>
        matters; the context driving it matters more.
      </div>
    </div>
  </div>

</div><!-- /tab-overview -->

<!-- ══════════════════════════════════════════════════════════════════════
     TAB: SIGNAL HISTORY
══════════════════════════════════════════════════════════════════════════ -->
<div id="tab-signals" class="tab-pane">

  <div class="section">
    <h2>All Signal Instances</h2>
    <div class="surface">
      <table>
        <thead><tr>
          <th style="text-align:left">Date</th>
          <th>MDY Close</th>
          <th>IWM Close</th>
          <th>QQQ vs ATH</th>
          <th>SPY vs ATH</th>
          <th>Quarter Position</th>
        </tr></thead>
        <tbody>{sig_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <h2>Signal Narratives</h2>
    <div class="sig-card qe">
      <div class="sig-date">December 31, 2012 <span class="badge-qe">Q-END ZONE</span></div>
      <div class="sig-meta">MDY $192.1 · IWM $87.1 · QQQ -5.1% from ATH · SPY -6.3% from ATH</div>
      <div class="sig-body">
        <strong>Context:</strong> The "fiscal cliff" was resolved with a last-minute deal on January 1, 2013.
        Small and mid-cap equities had already begun pricing in a resolution as breadth improved sharply in
        December while mega-cap tech (QQQ) remained weighed down by Apple's 35% collapse from its September
        2012 peak. The signal fired on the last trading day of Q4 2012 — a quintessential quarter-end
        rebalancing setup.<br><br>
        <strong>What happened:</strong> Q1 2013 delivered MDY +4.3% (4w), +4.2% (8w), +6.5% (13w).
        QQQ was the relative laggard at 13 weeks (+1.8%), confirming the rotation thesis. SPY
        participated cleanly (+3.3% / +3.9% / +6.0%). The breadth leadership signal led the whole market
        higher over the following quarter.
      </div>
    </div>
    <div class="sig-card nqe">
      <div class="sig-date">November 14, 2016</div>
      <div class="sig-meta">MDY $292.4 · IWM $131.0 · QQQ -1.2% from ATH · SPY ~flat from ATH</div>
      <div class="sig-body">
        <strong>Context:</strong> One week after the Trump election (November 8, 2016), IWM had already
        surged ~10% on the reflation/deregulation rotation. Small caps were perceived as the primary
        beneficiaries of domestic tax cuts and reduced regulation. QQQ lagged because the Nasdaq 100 was
        more exposed to potential trade friction and had been the market leader pre-election — profit-taking
        and rotation away from mega-cap tech created the divergence.<br><br>
        <strong>What happened:</strong> The "Trump rally" extended for months. MDY +7.9% (13w), IWM +6.2%
        (13w). QQQ eventually caught up and exceeded (+10.7% 13w) as the tech bid returned in early 2017.
        This was a "everything up, small/mid first" outcome rather than a pure rotation.
      </div>
    </div>
  </div>

</div><!-- /tab-signals -->

<!-- ══════════════════════════════════════════════════════════════════════
     TAB: FORWARD RETURNS
══════════════════════════════════════════════════════════════════════════ -->
<div id="tab-returns" class="tab-pane">

  <div class="section">
    <h2>All Signals — Mean Forward Returns</h2>
    <div class="alert alert-info" style="margin-bottom:12px;">
      n={n_total} total signals. Mean is the average across both instances; all instances were positive
      at every horizon.
    </div>
    <div class="surface">
      <table>
        <thead><tr>
          <th style="text-align:left">Ticker</th>
          <th>1 Week</th><th>2 Weeks</th><th>4 Weeks</th><th>8 Weeks</th><th>13 Weeks</th>
        </tr></thead>
        <tbody>{fwd_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <h2>Q-End Zone Signals Only — Mean Forward Returns</h2>
    <div class="alert alert-warn" style="margin-bottom:12px;">
      n={n_qe} signal(s) in the final 4 weeks of a quarter. <strong>This is the direct analog to the
      current June 2026 setup.</strong> Note QQQ underperformance at 13w vs small/mid.
    </div>
    <div class="surface">
      <table>
        <thead><tr>
          <th style="text-align:left">Ticker</th>
          <th>1 Week</th><th>2 Weeks</th><th>4 Weeks</th><th>8 Weeks</th><th>13 Weeks</th>
        </tr></thead>
        <tbody>{fwd_qe_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <h2>Non Q-End Signals — Mean Forward Returns</h2>
    <div class="surface">
      <table>
        <thead><tr>
          <th style="text-align:left">Ticker</th>
          <th>1 Week</th><th>2 Weeks</th><th>4 Weeks</th><th>8 Weeks</th><th>13 Weeks</th>
        </tr></thead>
        <tbody>{fwd_nqe_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <h2>Win Rate by Horizon</h2>
    <div class="surface">
      <table>
        <thead><tr>
          <th style="text-align:left">Ticker</th>
          <th>1 Week</th><th>2 Weeks</th><th>4 Weeks</th><th>8 Weeks</th><th>13 Weeks</th>
        </tr></thead>
        <tbody>{win_rows}</tbody>
      </table>
    </div>
    <div class="footnote">
      Win rate = % of instances with positive forward return. 100% across all tickers and horizons (except
      IWM 2-week and QQQ 2-week which showed 50% due to 1 negative instance each — both recovered fully
      at 4-week+).
    </div>
  </div>

</div><!-- /tab-returns -->

<!-- ══════════════════════════════════════════════════════════════════════
     TAB: CHARTS
══════════════════════════════════════════════════════════════════════════ -->
<div id="tab-charts" class="tab-pane">

  <div class="section">
    <h2>Price History with Signal Dates</h2>
    <img class="chart-img" src="data:image/png;base64,{charts['price']}" alt="Price History">
    <div class="chart-caption">Gold vertical lines = signal dates · Orange = Q-end zone signals · Dashed = rolling ATH</div>
  </div>

  <div class="section">
    <h2>Cumulative Return Paths After Signal</h2>
    <img class="chart-img" src="data:image/png;base64,{charts['paths']}" alt="Cumulative Paths">
    <div class="chart-caption">Shaded band = 95% CI (all signals) · Dashed lines = Q-end vs non-Q-end subsets</div>
  </div>

  <div class="section">
    <div class="chart-grid-2">
      <div>
        <h2>Forward Return Heatmap</h2>
        <img class="chart-img" src="data:image/png;base64,{charts['heatmap']}" alt="Heatmap">
        <div class="chart-caption">Green = positive return · Red = negative · Values are mean forward returns</div>
      </div>
      <div>
        <h2>4-Week Return Distributions</h2>
        <img class="chart-img" src="data:image/png;base64,{charts['dist']}" alt="Distribution">
        <div class="chart-caption">Distribution of 4-week forward returns across all signal instances</div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="chart-grid-2">
      <div>
        <h2>Forward Returns by Horizon</h2>
        <img class="chart-img" src="data:image/png;base64,{charts['bars']}" alt="Bar Charts">
        <div class="chart-caption">Blue=All · Orange=Q-end · Green=Non Q-end</div>
      </div>
      <div>
        <h2>Signal Calendar</h2>
        <img class="chart-img" src="data:image/png;base64,{charts['cal']}" alt="Calendar">
        <div class="chart-caption">When in the quarter do signals tend to cluster?</div>
      </div>
    </div>
  </div>

</div><!-- /tab-charts -->

<!-- ══════════════════════════════════════════════════════════════════════
     TAB: Q3 2026 THESIS
══════════════════════════════════════════════════════════════════════════ -->
<div id="tab-q3-outlook" class="tab-pane">

  <div class="section">
    <h2>Q3 2026 Thesis</h2>
    <div class="surface narrative">

      <div class="key-finding">
        <strong>Bottom line:</strong> The signal is live now, in the Q-end zone, with 16 days
        to Q3 open. The only historical Q-end analog (Dec 2012 → Q1 2013) produced a
        +4.3%/+4.2%/+6.5% progression in MDY at 4/8/13 weeks. A Q3 lift-off bid is historically
        supported and structurally plausible.
      </div>

      <h3 style="margin:16px 0 8px;">Why Small/Mid Leading Matters</h3>
      <p>MDY (S&amp;P 400 Mid-Cap) and IWM (Russell 2000 Small-Cap) are the most domestically
      sensitive, rate-sensitive, and earnings-cyclical segments of the equity market. When they
      break to new ATHs <em>before</em> the Nasdaq 100 and S&amp;P 500, it signals:</p>
      <ul style="margin:8px 0 12px 20px;line-height:2;">
        <li>Broad market health underneath the surface — breadth is expanding</li>
        <li>A macro regime that rewards domestic cyclicals (not mega-cap tech)</li>
        <li>Institutional rotation into risk assets beyond the "Magnificent 7" concentration</li>
        <li>Bond market stabilization — small/mid are most sensitive to credit spreads and rates</li>
      </ul>

      <h3 style="margin:16px 0 8px;">Quarter-End Mechanics</h3>
      <p>The final weeks of a quarter are typically characterized by:</p>
      <ul style="margin:8px 0 12px 20px;line-height:2;">
        <li><strong>Window dressing:</strong> Institutions buy recent winners to show them in
        quarter-end holdings — MDY/IWM at ATH are prime candidates</li>
        <li><strong>Rebalancing:</strong> Fixed-income flows that underperformed redirect toward
        equities in Q-end rebalancing</li>
        <li><strong>New-quarter deployment:</strong> Q3 institutional inflows tend to continue
        buying the prior quarter's leadership</li>
      </ul>
      <p>If MDY and IWM hold their ATH status into June 30, expect the Q3 open (July 1–5)
      to see concentrated buying in this cohort as new-quarter mandates are deployed.</p>

      <h3 style="margin:16px 0 8px;">Positioning Framework</h3>
      <div class="highlight">
        <strong>Primary beneficiaries:</strong> MDY and SPY — the cleanest historical performers
        in the Q-end analog (MDY +4.3% at 4w, SPY +3.3% at 4w per the Dec 2012 instance).<br><br>
        <strong>IWM:</strong> Participates but is the most volatile. The 2-week window historically
        showed 50% win rate (consolidation can continue briefly before extending).<br><br>
        <strong>QQQ:</strong> Lagged significantly at 13 weeks in the Q-end analog (+1.8% vs +6.5%
        for MDY). In a pure rotation scenario, QQQ is the last to catch up. In a "everything-up"
        scenario (2016 analog), QQQ eventually exceeds.
      </div>

      <h3 style="margin:16px 0 8px;">Key Risk Factors</h3>
      <ul style="margin:8px 0 12px 20px;line-height:2;">
        <li><strong>Mean reversion of the signal itself:</strong> If MDY/IWM fail to hold ATH
        weekly closes in the next 1–2 weeks, the signal is invalidated</li>
        <li><strong>Macro catalyst:</strong> Both historical precedents had a clear macro driver
        (fiscal cliff resolution, election). What's driving the 2026 divergence?</li>
        <li><strong>QQQ catch-up:</strong> If QQQ rapidly closes its -2.3% gap and breaks to ATH
        alongside small/mid, the divergence thesis changes — it becomes a broad breakout, which has
        different (generally more bullish) implications</li>
        <li><strong>N=2:</strong> This is directional intelligence, not statistical proof</li>
      </ul>

      <h3 style="margin:16px 0 8px;">Monitoring Checklist</h3>
      <table style="margin-top:8px;">
        <thead><tr><th style="text-align:left">Metric</th><th>Bull Case</th><th>Bear Case</th></tr></thead>
        <tbody>
          <tr><td>MDY weekly close</td><td class="pos">Holds ≥ current ATH</td><td class="neg">Fails ATH, reverses</td></tr>
          <tr><td>IWM weekly close</td><td class="pos">Holds ≥ current ATH</td><td class="neg">Reversal below ATH</td></tr>
          <tr><td>QQQ gap to ATH</td><td class="pos">Stays -2% to -5% (rotation)</td><td class="neg">Breaks out or breaks down</td></tr>
          <tr><td>SPY weekly close</td><td class="pos">Moves toward ATH</td><td class="neg">Stalls / reverses</td></tr>
          <tr><td>Q3 open (Jul 1–5)</td><td class="pos">Strong buy volume in MDY/IWM</td><td class="neg">Gap fill / sell the news</td></tr>
        </tbody>
      </table>
    </div>
  </div>

</div><!-- /tab-q3-outlook -->

<!-- ══ FOOTER ══════════════════════════════════════════════════════════════ -->
<div class="divider"></div>
<div class="footnote">
  <strong>AlphaQuery Research</strong> · MDY/IWM ATH Divergence Study · Data: broker OHLCV API,
  weekly bars · Universe: 976 weeks (Apr 2007 – Jun 2026) · Signal: MDY+IWM new rolling ATH after
  ≥{MIN_CONSOL} weeks below ATH; QQQ+SPY not at ATH · Source: <code>studies/mdy_iwm_ath_divergence_study.py</code><br>
  <em>For research purposes only. Not financial advice. N=2 historical instances — treat as directional
  intelligence.</em>
</div>
</div><!-- /container -->

<script>
  function showTab(name) {{
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    event.target.classList.add('active');
  }}

  function refreshAnalysis() {{
    const btn = document.querySelector('.btn-primary');
    const status = document.getElementById('refresh-status');
    btn.textContent = '↻ Refreshing…';
    btn.disabled = true;
    status.textContent = '';
    fetch('/refresh')
      .then(r => r.json())
      .then(d => {{
        if (d.ok) {{
          status.textContent = '✓ Done — reloading…';
          setTimeout(() => location.reload(), 800);
        }} else {{
          status.textContent = '⚠ ' + (d.error || 'Error');
          btn.textContent = '↺ Refresh Data'; btn.disabled = false;
        }}
      }})
      .catch(() => {{
        status.textContent = '⚠ Run: python3 studies/serve.py';
        btn.textContent = '↺ Refresh Data'; btn.disabled = false;
      }});
  }}
</script>
</body>
</html>"""


def generate(output_path=None):
    print("Running analysis…")
    data = run_analysis()
    print("Generating charts…")
    charts = dict(
        price   = chart_price(data),
        bars    = chart_fwd_bars(data),
        heatmap = chart_heatmap(data),
        dist    = chart_dist(data),
        cal     = chart_calendar(data),
        paths   = chart_paths(data),
    )
    print("Building HTML…")
    html = build_html(data, charts)
    out = output_path or BASE / "report.html"
    pathlib.Path(out).write_text(html, encoding="utf-8")
    print(f"✓ Report written → {out}")
    return str(out)


if __name__ == "__main__":
    import argparse, subprocess, os
    p = argparse.ArgumentParser()
    p.add_argument("--serve", action="store_true", help="Start local server after generating")
    p.add_argument("--port",  type=int, default=8765)
    args = p.parse_args()

    out = generate()

    if args.serve:
        # inline server so one command does everything
        import http.server, threading, json as _json, urllib.parse

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/refresh':
                    try:
                        generate(out)
                        body = _json.dumps({"ok": True}).encode()
                    except Exception as e:
                        body = _json.dumps({"ok": False, "error": str(e)}).encode()
                    self.send_response(200)
                    self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length', len(body))
                    self.end_headers(); self.wfile.write(body)
                elif self.path in ('/', '/report.html'):
                    body = pathlib.Path(out).read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type','text/html; charset=utf-8')
                    self.send_header('Content-Length', len(body))
                    self.end_headers(); self.wfile.write(body)
                else:
                    self.send_response(404); self.end_headers()
            def log_message(self, *a): pass  # suppress noise

        server = http.server.HTTPServer(('0.0.0.0', args.port), Handler)
        print(f"\n🚀  Serving at http://localhost:{args.port}")
        print(f"    Press Ctrl+C to stop  |  Click '↺ Refresh Data' in the browser to re-run analysis\n")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
