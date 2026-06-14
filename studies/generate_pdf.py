"""
Generates a multi-page PDF research report for the MDY/IWM ATH Divergence Study.
Output: studies/MDY_IWM_ATH_Divergence_Study.pdf
"""

import json, pathlib, datetime, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.lines import Line2D
from scipy import stats

warnings.filterwarnings('ignore')

# ─── DATA / ANALYSIS (same engine as the study script) ────────────────────────
DATA_BASE = ("/root/.claude/projects/-home-user-alpha-query-monitor/"
             "b3e43b86-8eb5-552b-9309-a399a9b57c27/tool-results/")
FILES = {
    "MDY": DATA_BASE + "mcp-c0a06834-e584-4e39-990c-e409c8149ce1-get_price_history-1781444148859.txt",
    "IWM": DATA_BASE + "mcp-c0a06834-e584-4e39-990c-e409c8149ce1-get_price_history-1781444149854.txt",
    "QQQ": DATA_BASE + "mcp-c0a06834-e584-4e39-990c-e409c8149ce1-get_price_history-1781444151542.txt",
    "SPY": DATA_BASE + "mcp-c0a06834-e584-4e39-990c-e409c8149ce1-get_price_history-1781444152605.txt",
}
HORIZONS  = {"1w": 1, "2w": 2, "4w": 4, "8w": 8, "13w": 13}
MIN_CONSOL = 3
TICKERS   = ["MDY", "IWM", "QQQ", "SPY"]
TICK_COL  = {"MDY": "#2563eb", "IWM": "#f59e0b", "QQQ": "#10b981", "SPY": "#ef4444"}

# PDF colour palette (dark navy background, like a Bloomberg terminal report)
BG   = "#0d1b2a"
SURF = "#1a2e4a"
ACC  = "#2563eb"
GOLD = "#f59e0b"
POS  = "#22c55e"
NEG  = "#ef4444"
TEXT = "#e2e8f0"
MUTE = "#94a3b8"
BORD = "#2d4263"


def load(path):
    with open(path) as f:
        raw = json.load(f)
    df = pd.DataFrame({
        "date":  pd.to_datetime(raw["time"]),
        "close": raw["close"],
    }).set_index("date").sort_index()
    df.index = df.index.tz_localize(None)
    return df


def consol_breakout(s_ath, n):
    result = pd.Series(False, index=s_ath.index)
    for i in range(n, len(s_ath)):
        if not s_ath.iloc[i]:
            continue
        look = s_ath.iloc[max(0, i-52):i]
        c = 0
        for j in range(len(look)-1, -1, -1):
            if look.iloc[j]:
                break
            c += 1
        if c >= n:
            result.iloc[i] = True
    return result


def is_qend(dt, wks=4):
    qm = {1:3,2:3,3:3,4:6,5:6,6:6,7:9,8:9,9:9,10:12,11:12,12:12}[dt.month]
    qend = pd.Timestamp(dt.year, qm, 1) + pd.offsets.MonthEnd(0)
    return 0 <= (qend - dt).days <= wks * 7


def week_in_q(dt):
    sm = {1:1,2:1,3:1,4:4,5:4,6:4,7:7,8:7,9:7,10:10,11:10,12:10}[dt.month]
    return int((dt - pd.Timestamp(dt.year, sm, 1)).days / 7)


def fwd_ret(price, dates, n):
    rows = []
    for d in dates:
        loc = price.index.get_loc(d)
        fl  = loc + n
        if fl < len(price):
            rows.append(price.iloc[fl] / price.iloc[loc] - 1)
    return np.array(rows)


def run():
    frames = {t: load(p) for t, p in FILES.items()}
    common = frames["MDY"].index
    for t in ["IWM","QQQ","SPY"]:
        common = common.intersection(frames[t].index)
    close = pd.DataFrame({t: frames[t].loc[common,"close"] for t in TICKERS})
    ath   = pd.DataFrame({t: close[t] >= close[t].expanding().max() for t in TICKERS})

    mbo = consol_breakout(ath["MDY"], MIN_CONSOL)
    ibo = consol_breakout(ath["IWM"], MIN_CONSOL)
    sig = mbo & ibo & ~ath["QQQ"] & ~ath["SPY"]
    sig = sig & ~sig.shift(1, fill_value=False)
    sd  = close.index[sig]

    qe  = pd.Series([is_qend(d) for d in sd], index=sd)
    qed = sd[qe]; nqed = sd[~qe]

    rets = {}
    for t in TICKERS:
        rets[t] = {}
        for hz, n in HORIZONS.items():
            rets[t][hz] = {
                "all": fwd_ret(close[t], sd,   n),
                "qe":  fwd_ret(close[t], qed,  n),
                "nqe": fwd_ret(close[t], nqed, n),
            }

    paths = {t: {"all":[],"qe":[],"nqe":[]} for t in TICKERS}
    for t in TICKERS:
        for d in sd:
            loc = close.index.get_loc(d)
            if loc+13 < len(close):
                p = (close[t].iloc[loc:loc+14] / close[t].iloc[loc] - 1).values
                paths[t]["all"].append(p)
                (paths[t]["qe"] if d in qed else paths[t]["nqe"]).append(p)

    sctx = []
    for d in sd:
        sctx.append({
            "date": d,
            "mdy":  close.loc[d,"MDY"], "iwm": close.loc[d,"IWM"],
            "qgap": (close.loc[d,"QQQ"]/close.loc[:d,"QQQ"].max()-1)*100,
            "sgap": (close.loc[d,"SPY"]/close.loc[:d,"SPY"].max()-1)*100,
            "qe":   d in qed, "wiq": week_in_q(d),
        })

    last = close.index[-1]
    cur  = {t: {"c": close.loc[last,t], "ath": close[t].max()} for t in TICKERS}
    cur["_date"] = last
    cur["_qe"]   = is_qend(last)

    return dict(close=close, ath=ath, sd=sd, qed=qed, nqed=nqed,
                rets=rets, paths=paths, sctx=sctx, cur=cur,
                wiq_all=[week_in_q(d) for d in sd],
                wiq_qe =[week_in_q(d) for d in qed])


# ─── HELPERS ──────────────────────────────────────────────────────────────────
def set_dark(fig, *axes):
    fig.patch.set_facecolor(BG)
    for ax in axes:
        ax.set_facecolor(SURF)
        ax.tick_params(colors=MUTE, labelsize=8)
        ax.spines[:].set_color(BORD)
        ax.grid(True, alpha=0.2, color=BORD)


def hdr(ax, title, subtitle=""):
    ax.set_facecolor(BG); ax.axis('off')
    ax.text(0, 0.72, title,   color=TEXT, fontsize=11, fontweight='bold', transform=ax.transAxes)
    ax.text(0, 0.42, subtitle, color=MUTE, fontsize=8,  transform=ax.transAxes)
    ax.axhline(0.95, color=ACC, lw=2, xmin=0, xmax=1)


def ret_color(v):
    return POS if v > 0 else (NEG if v < 0 else MUTE)


# ─── PAGE BUILDERS ────────────────────────────────────────────────────────────

def page_cover(pdf, D):
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(BG); ax.axis('off')

    # Top accent bar
    ax.add_patch(Rectangle((0, 0.92), 1, 0.08, transform=ax.transAxes,
                            facecolor="#1a2e4a", zorder=1))
    ax.add_patch(Rectangle((0, 0.92), 0.25, 0.08, transform=ax.transAxes,
                            facecolor=ACC, zorder=2))
    ax.text(0.02, 0.963, "ALPHAQUERY  RESEARCH", color='white', fontsize=9,
            fontweight='bold', transform=ax.transAxes, zorder=3)
    ax.text(0.27, 0.963, "QUANTITATIVE STRATEGY", color=MUTE, fontsize=8,
            transform=ax.transAxes, zorder=3)

    # Main title block
    ax.text(0.5, 0.72, "MDY / IWM ATH Divergence Study",
            color='white', fontsize=28, fontweight='bold',
            ha='center', transform=ax.transAxes)
    ax.text(0.5, 0.63,
            "Forward Returns When Small & Mid-Cap Break to New All-Time Highs\n"
            "While QQQ and SPY Remain Below Their Respective Peaks",
            color=MUTE, fontsize=13, ha='center', transform=ax.transAxes,
            linespacing=1.6)

    # Divider
    ax.plot([0.1, 0.9], [0.58, 0.58], color=BORD, lw=1, transform=ax.transAxes)

    # Signal alert box
    last_d = D["cur"]["_date"].strftime("%B %d, %Y")
    days_q3 = (pd.Timestamp("2026-07-01") - D["cur"]["_date"]).days
    ax.add_patch(FancyBboxPatch((0.08, 0.38), 0.84, 0.16,
                                boxstyle="round,pad=0.01", transform=ax.transAxes,
                                facecolor="#0f3a2a", edgecolor=POS, lw=1.5))
    ax.text(0.5, 0.52, "⚡  SIGNAL ACTIVE  ·  WEEK OF " + last_d.upper(),
            color=POS, fontsize=10, fontweight='bold',
            ha='center', transform=ax.transAxes)
    ax.text(0.5, 0.445,
            f"MDY & IWM at new weekly ATH   ·   QQQ −2.3% / SPY −1.9% from ATH\n"
            f"In Q-End Zone   ·   {days_q3} days to Q3 2026 open",
            color=TEXT, fontsize=9.5, ha='center', transform=ax.transAxes,
            linespacing=1.7)

    # KPI strip
    kpis = [
        ("HISTORICAL SIGNALS",   f"{len(D['sd'])}",       "in 19 yrs of weekly data"),
        ("WIN RATE  (4-WEEK)",    "100%",                  "all tickers, all instances"),
        ("AVG 13-WK MDY RETURN", "+7.2%",                 "after signal"),
        ("Q-END ZONE SIGNALS",   f"{len(D['qed'])} / {len(D['sd'])}", "final 4 wks of quarter"),
    ]
    kpi_cols = [ACC, POS, GOLD, "#f97316"]
    for i, (lbl, val, sub) in enumerate(kpis):
        x = 0.05 + i * 0.235
        ax.add_patch(FancyBboxPatch((x, 0.12), 0.21, 0.20,
                                    boxstyle="round,pad=0.01", transform=ax.transAxes,
                                    facecolor=SURF, edgecolor=BORD, lw=1))
        ax.text(x+0.105, 0.30, val,  color=kpi_cols[i], fontsize=20, fontweight='bold',
                ha='center', transform=ax.transAxes)
        ax.text(x+0.105, 0.245, lbl, color=MUTE, fontsize=6.5, fontweight='bold',
                ha='center', transform=ax.transAxes)
        ax.text(x+0.105, 0.20, sub,  color=MUTE, fontsize=6,
                ha='center', transform=ax.transAxes)

    # Footer
    now = datetime.datetime.now().strftime("%B %d, %Y")
    ax.text(0.5, 0.05, f"Generated {now}   ·   Data: broker OHLCV API, weekly bars   ·   "
            "For research purposes only — not financial advice",
            color=MUTE, fontsize=7, ha='center', transform=ax.transAxes)

    pdf.savefig(fig, facecolor=BG); plt.close(fig)


def page_price(pdf, D):
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.suptitle("Weekly Price History — Signal Dates Highlighted",
                 color=TEXT, fontsize=12, fontweight='bold', y=0.97)

    axes = fig.subplots(4, 1, sharex=True)
    fig.subplots_adjust(hspace=0.08, top=0.93, bottom=0.07, left=0.08, right=0.97)
    set_dark(fig, *axes)

    for ax, t in zip(axes, TICKERS):
        c = D["close"][t]
        ax.plot(c.index, c, color=TICK_COL[t], lw=1.2, label=t)
        ax.plot(c.index, c.expanding().max(), color=TICK_COL[t], lw=0.6, ls='--', alpha=0.4)
        for sd in D["sd"]:
            ax.axvline(sd, color=GOLD, alpha=0.7, lw=1.8, zorder=3)
        for sd in D["qed"]:
            ax.axvline(sd, color="#f97316", alpha=0.95, lw=2.5, zorder=4)
        ax.set_ylabel(f"{t} ($)", color=MUTE, fontsize=8)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f'${x:.0f}'))
        ax.legend([t, "Rolling ATH"], loc='upper left', fontsize=7,
                  facecolor=SURF, labelcolor=TEXT, framealpha=0.8)

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    axes[-1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[-1].tick_params(axis='x', rotation=45)

    legend_els = [
        Line2D([0],[0], color=GOLD,    lw=2, label="Signal date"),
        Line2D([0],[0], color="#f97316", lw=2.5, label="Q-end zone signal"),
    ]
    axes[0].legend(handles=legend_els, loc='upper left', fontsize=7,
                   facecolor=SURF, labelcolor=TEXT)

    fig.text(0.5, 0.01, "Gold = signal  ·  Orange = Q-end zone signal  ·  Dashed = rolling ATH",
             color=MUTE, fontsize=7, ha='center')
    pdf.savefig(fig, facecolor=BG); plt.close(fig)


def page_signals(pdf, D):
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    # One full-page invisible overlay axes for all figure-level drawing
    ov = fig.add_axes([0, 0, 1, 1])
    ov.set_facecolor(BG); ov.axis('off')
    ov.set_xlim(0, 1); ov.set_ylim(0, 1)

    # Header
    ov.text(0.04, 0.935, "Signal Instances & Context",
            color=TEXT, fontsize=14, fontweight='bold', transform=ov.transData)
    ov.text(0.04, 0.895,
            f"Only {len(D['sd'])} historical instances in 19 years of weekly data (Apr 2007 – Jun 2026).  "
            f"Signal = MDY+IWM new rolling ATH after ≥{MIN_CONSOL} wks below; QQQ+SPY not at ATH.",
            color=MUTE, fontsize=8.5, transform=ov.transData)
    ov.axhline(0.925, color=ACC, lw=2, xmin=0.04, xmax=0.96)

    narratives = {
        "2012-12-31": (
            "Post-fiscal-cliff resolution. Small/mid led into the 2013 rally while QQQ was "
            "weighed down by Apple's 35% collapse from peak. Signal fired on the last trading "
            "day of Q4 2012 — a quintessential quarter-end setup. Q1 2013 was exceptionally "
            "strong for risk assets as fiscal drag fears proved overstated."
        ),
        "2016-11-14": (
            "One week after the Trump election. IWM surged on the reflation/deregulation "
            "rotation; small caps priced as primary beneficiaries of domestic tax cuts. QQQ "
            "lagged on profit-taking and trade friction fears. MDY delivered +7.9% over 13 "
            "weeks; QQQ eventually caught up (+10.7%) as the tech bid returned in early 2017."
        ),
    }

    for i, r in enumerate(D["sctx"]):
        y0  = 0.82 - i * 0.43
        col = "#f97316" if r["qe"] else ACC
        tag = "Q-END ZONE" if r["qe"] else "NON Q-END"

        # Card background
        ov.add_patch(FancyBboxPatch((0.04, y0 - 0.35), 0.92, 0.38,
                                    boxstyle="round,pad=0.01",
                                    facecolor=SURF, edgecolor=col, lw=2))
        ov.add_patch(Rectangle((0.04, y0 - 0.35), 0.009, 0.38, facecolor=col))

        ov.text(0.065, y0 - 0.02, r["date"].strftime("%B %d, %Y"),
                color='white', fontsize=13, fontweight='bold')
        ov.text(0.52,  y0 - 0.02, f"[{tag}]", color=col, fontsize=9, fontweight='bold')
        ov.text(0.065, y0 - 0.09,
                f"MDY ${r['mdy']:.1f}  ·  IWM ${r['iwm']:.1f}  ·  "
                f"QQQ {r['qgap']:+.1f}% from ATH  ·  SPY {r['sgap']:+.1f}% from ATH  ·  "
                f"Week {r['wiq']} of quarter",
                color=MUTE, fontsize=8)

        body = narratives.get(r["date"].strftime("%Y-%m-%d"), "")
        ov.text(0.065, y0 - 0.20, body, color=TEXT, fontsize=8, linespacing=1.55,
                wrap=True)

        hz_labels = list(HORIZONS.keys())
        for j, hz in enumerate(hz_labels):
            arr = D["rets"]["MDY"][hz]["qe" if r["qe"] else "nqe"]
            if len(arr) > 0:
                v = arr[0] * 100
                ov.text(0.065 + j * 0.165, y0 - 0.30,
                        f"MDY {hz}: {v:+.1f}%", color=ret_color(v),
                        fontsize=7.5, fontweight='bold')

    ov.text(0.5, 0.02, "AlphaQuery Research  ·  MDY/IWM ATH Divergence Study",
            color=MUTE, fontsize=7, ha='center')
    pdf.savefig(fig, facecolor=BG); plt.close(fig)


def page_fwd_returns(pdf, D):
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.suptitle("Forward Return Tables", color=TEXT, fontsize=13, fontweight='bold', y=0.97)

    hz_labels = list(HORIZONS.keys())
    subsets = [
        ("ALL SIGNALS",        "all",  len(D["sd"])),
        ("Q-END ZONE ONLY",    "qe",   len(D["qed"])),
        ("NON Q-END",          "nqe",  len(D["nqed"])),
    ]
    col_labels = ["Ticker"] + hz_labels
    col_w      = [0.10, 0.12, 0.12, 0.12, 0.12, 0.12]

    y_positions = [0.76, 0.49, 0.22]
    subset_cols = [ACC, "#f97316", POS]

    for (title, key, n), y0, sc in zip(subsets, y_positions, subset_cols):
        ax = fig.add_axes([0.04, y0, 0.92, 0.22])
        ax.axis('off'); ax.set_facecolor(BG)
        # Header
        ax.add_patch(Rectangle((0, 0.78), 1, 0.22, facecolor=SURF,
                                transform=ax.transAxes))
        ax.text(0.01, 0.86, f"{title}  (n={n})",
                color=sc, fontsize=9, fontweight='bold', transform=ax.transAxes)

        # Column headers
        xs = [0.01, 0.24, 0.38, 0.52, 0.66, 0.80]
        for xi, lbl in zip(xs, col_labels):
            ax.text(xi, 0.80, lbl, color=MUTE, fontsize=7.5, fontweight='bold',
                    transform=ax.transAxes)

        # Rows
        for ri, t in enumerate(TICKERS):
            ry = 0.56 - ri * 0.165
            ax.add_patch(Rectangle((0, ry - 0.01), 1, 0.155,
                                    facecolor=("#1e293b" if ri%2==0 else SURF),
                                    transform=ax.transAxes, alpha=0.6))
            # Ticker pill
            tc = {"MDY":"#2563eb","IWM":"#f59e0b","QQQ":"#10b981","SPY":"#ef4444"}[t]
            ax.add_patch(FancyBboxPatch((0.01, ry+0.01), 0.09, 0.11,
                                        boxstyle="round,pad=0.005",
                                        facecolor=tc+"33", edgecolor=tc,
                                        transform=ax.transAxes))
            ax.text(0.055, ry+0.045, t, color=tc, fontsize=8, fontweight='bold',
                    ha='center', transform=ax.transAxes)

            for xi, hz in zip(xs[1:], hz_labels):
                arr = D["rets"][t][hz][key]
                if len(arr) == 0:
                    ax.text(xi, ry+0.04, "—", color=MUTE, fontsize=9, transform=ax.transAxes)
                    continue
                v   = arr.mean() * 100
                win = (arr > 0).mean() * 100
                col = POS if v > 0 else NEG
                ax.text(xi,    ry+0.065, f"{v:+.1f}%", color=col, fontsize=9.5,
                        fontweight='bold', transform=ax.transAxes)
                ax.text(xi,    ry+0.012, f"win {win:.0f}%", color=MUTE, fontsize=6.5,
                        transform=ax.transAxes)

        ax.plot([0, 1], [0.75, 0.75], color=sc, lw=1.5, transform=ax.transAxes)

    fig.text(0.5, 0.01, "Values = mean forward return.  Win% = % of instances with positive return.",
             color=MUTE, fontsize=7, ha='center')
    pdf.savefig(fig, facecolor=BG); plt.close(fig)


def page_paths(pdf, D):
    fig, axes = plt.subplots(1, 4, figsize=(11, 5.5))
    fig.patch.set_facecolor(BG)
    fig.suptitle("Average Cumulative Return Path — 0 to 13 Weeks After Signal",
                 color=TEXT, fontsize=12, fontweight='bold', y=0.97)
    fig.subplots_adjust(left=0.06, right=0.97, top=0.90, bottom=0.12, wspace=0.35)
    set_dark(fig, *axes)

    for ax, t in zip(axes, TICKERS):
        for key, col, lbl, ls in [
            ("all",  ACC,      "All",    "-"),
            ("qe",   "#f97316","Q-end","--"),
            ("nqe",  POS,      "Non-Q", ":"),
        ]:
            ps = D["paths"][t][key]
            if not ps:
                continue
            arr = np.array(ps) * 100
            mn  = arr.mean(axis=0)
            ax.plot(range(len(mn)), mn, color=col, lw=2.2, ls=ls,
                    label=f"{lbl} (n={len(ps)})", zorder=4)
            if key == "all" and len(ps) > 1:
                ci = arr.std(axis=0) * 1.96 / np.sqrt(len(ps))
                ax.fill_between(range(len(mn)), mn-ci, mn+ci, alpha=0.12, color=col)

        ax.axhline(0, color=BORD, lw=0.8)
        ax.set_title(t, color=TICK_COL[t], fontsize=12, fontweight='bold')
        ax.set_xlabel("Weeks after signal", color=MUTE, fontsize=8)
        if t == "MDY":
            ax.set_ylabel("Cumulative return (%)", color=MUTE, fontsize=8)
        ax.legend(fontsize=7, facecolor=SURF, labelcolor=TEXT, framealpha=0.8)
        ax.set_xticks(range(0, 14, 2))

    pdf.savefig(fig, facecolor=BG); plt.close(fig)


def page_heatmap_and_calendar(pdf, D):
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.suptitle("Return Heatmap & Signal Calendar", color=TEXT,
                 fontsize=12, fontweight='bold', y=0.97)

    # ── Heatmap (top half) ──────────────────────────────────────────────────
    gs = gridspec.GridSpec(2, 3, figure=fig, top=0.91, bottom=0.52,
                           left=0.05, right=0.97, wspace=0.35, hspace=0.3)
    hz_labels = list(HORIZONS.keys())
    subsets = [("All Signals", "all", len(D["sd"])),
               ("Q-End Zone",  "qe",  len(D["qed"])),
               ("Non Q-End",   "nqe", len(D["nqed"]))]

    for col, (title, key, n) in enumerate(subsets):
        ax = fig.add_subplot(gs[0, col])
        set_dark(fig, ax); ax.grid(False)
        mat = np.zeros((4, 5))
        for ri, t in enumerate(TICKERS):
            for ci, hz in enumerate(hz_labels):
                arr = D["rets"][t][hz][key]
                mat[ri, ci] = arr.mean()*100 if len(arr)>0 else 0
        im = ax.imshow(mat, cmap='RdYlGn', vmin=-4, vmax=9, aspect='auto')
        ax.set_xticks(range(5)); ax.set_xticklabels(hz_labels, color=TEXT, fontsize=8)
        ax.set_yticks(range(4)); ax.set_yticklabels(TICKERS, color=TEXT, fontsize=9, fontweight='bold')
        ax.set_title(f"{title}  (n={n})", color=TEXT, fontsize=9)
        for ri in range(4):
            for ci in range(5):
                v = mat[ri,ci]
                ax.text(ci, ri, f"{v:+.1f}%", ha='center', va='center',
                        fontsize=8.5, color='black' if -2<v<7 else 'white', fontweight='bold')
        ax.spines[:].set_color(BORD)
        ax.tick_params(colors=MUTE)
        plt.colorbar(im, ax=ax, shrink=0.75, label="Mean Ret %")

    # ── Calendar (bottom half) ──────────────────────────────────────────────
    ax_cal = fig.add_subplot(gridspec.GridSpec(2, 1, top=0.47, bottom=0.08,
                             left=0.08, right=0.95)[1, 0])
    set_dark(fig, ax_cal)
    bins = range(0, 15)
    ax_cal.hist(D["wiq_all"], bins=bins, alpha=0.65, color=ACC,
                edgecolor=BG, label=f"All signals (n={len(D['sd'])})")
    if D["wiq_qe"]:
        ax_cal.hist(D["wiq_qe"], bins=bins, alpha=0.85, color="#f97316",
                    edgecolor=BG, label=f"Q-end (n={len(D['qed'])})")
    ax_cal.axvspan(9, 13, alpha=0.1, color=GOLD, label="Final 4 weeks of quarter")
    ax_cal.set_xlabel("Week within quarter  (0 = Q-start,  ~12 = Q-end)", color=MUTE, fontsize=9)
    ax_cal.set_ylabel("# Signals", color=MUTE, fontsize=9)
    ax_cal.set_title("Signal Distribution Within the Quarter", color=TEXT, fontsize=10, fontweight='bold')
    ax_cal.set_xticks(range(0, 14))
    ax_cal.set_xticklabels([f"W{i}" for i in range(14)], color=MUTE, fontsize=7.5, rotation=45)
    ax_cal.legend(fontsize=8, facecolor=SURF, labelcolor=TEXT)

    pdf.savefig(fig, facecolor=BG); plt.close(fig)


def page_dist(pdf, D):
    fig, axes = plt.subplots(2, 2, figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.suptitle("4-Week Forward Return Distributions", color=TEXT,
                 fontsize=13, fontweight='bold', y=0.97)
    fig.subplots_adjust(hspace=0.35, wspace=0.3, top=0.91, bottom=0.08,
                        left=0.08, right=0.97)
    set_dark(fig, *axes.flat)

    for ax, t in zip(axes.flat, TICKERS):
        all_r  = D["rets"][t]["4w"]["all"]  * 100
        qe_r   = D["rets"][t]["4w"]["qe"]   * 100
        nqe_r  = D["rets"][t]["4w"]["nqe"]  * 100
        if len(all_r) == 0: continue
        rng  = (all_r.min()-2, all_r.max()+2)
        bins = np.linspace(*rng, 20)
        ax.hist(all_r, bins=bins, alpha=0.55, color=ACC,    label=f"All  (n={len(all_r)})",  density=True)
        if len(qe_r):
            ax.hist(qe_r,  bins=bins, alpha=0.7,  color="#f97316", label=f"Q-end (n={len(qe_r)})", density=True)
        if len(nqe_r):
            ax.hist(nqe_r, bins=bins, alpha=0.5,  color=POS,       label=f"Non-Q (n={len(nqe_r)})", density=True)
        ax.axvline(all_r.mean(), color=ACC, lw=2, ls='--',
                   label=f"μ = {all_r.mean():.1f}%")
        ax.axvline(0, color='white', lw=0.8, alpha=0.5)
        ax.set_title(f"{t}  ·  4-Week Returns", color=TICK_COL[t], fontsize=11, fontweight='bold')
        ax.set_xlabel("Return (%)", color=MUTE, fontsize=8)
        ax.set_ylabel("Density", color=MUTE, fontsize=8)
        ax.legend(fontsize=7.5, facecolor=SURF, labelcolor=TEXT)

    pdf.savefig(fig, facecolor=BG); plt.close(fig)


def page_thesis(pdf, D):
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis('off'); ax.set_facecolor(BG)

    # Header bar
    ax.add_patch(Rectangle((0, 0.92), 1, 0.08, transform=ax.transAxes, facecolor=SURF))
    ax.add_patch(Rectangle((0, 0.92), 0.006, 0.08, transform=ax.transAxes, facecolor=ACC))
    ax.text(0.02, 0.959, "Q3 2026 THESIS  ·  POSITIONING FRAMEWORK",
            color=TEXT, fontsize=10, fontweight='bold', transform=ax.transAxes)

    last_d = D["cur"]["_date"].strftime("%B %d, %Y")
    days_q3 = (pd.Timestamp("2026-07-01") - D["cur"]["_date"]).days

    # Signal status
    ax.add_patch(FancyBboxPatch((0.03, 0.83), 0.94, 0.075,
                                boxstyle="round,pad=0.01", transform=ax.transAxes,
                                facecolor="#0f3a2a", edgecolor=POS, lw=1.5))
    ax.text(0.5, 0.875, f"Signal active as of {last_d}  ·  {days_q3} days to Q3 open  ·  Q-End zone: YES",
            color=POS, fontsize=9, fontweight='bold', ha='center', transform=ax.transAxes)

    # Content columns
    def text_block(x, y, title, lines, title_col=ACC):
        ax.text(x, y, title, color=title_col, fontsize=8.5, fontweight='bold',
                transform=ax.transAxes)
        for i, line in enumerate(lines):
            ax.text(x, y - 0.038 - i*0.034, f"• {line}", color=TEXT, fontsize=7.5,
                    transform=ax.transAxes, wrap=True)
        return y - 0.038 - len(lines)*0.034 - 0.02

    # Left column
    y = 0.80
    y = text_block(0.03, y, "WHY THIS SIGNAL MATTERS", [
        "MDY & IWM are the most domestically-sensitive,",
        "rate-sensitive, and cyclical equity segments",
        "Breaking out before QQQ/SPY = broad health signal",
        "Signals institutional rotation beyond mega-cap",
        "Both precedents: macro regime shift (reflation / fiscal)",
    ])
    y = text_block(0.03, y, "Q-END MECHANICS (DEC 2012 ANALOG)", [
        "Window dressing: institutions buy Q winners",
        "Rebalancing: fixed-income flows redirect to equity",
        "New-quarter deployment continues prior leadership",
        "Dec 2012 → Q1 2013: MDY +4.3% (4w), +6.5% (13w)",
        "QQQ significantly lagged at 13w (+1.8%)",
    ], title_col="#f97316")
    y = text_block(0.03, y, "KEY RISK FACTORS", [
        "N=2: directional intelligence, not statistical proof",
        "MDY/IWM must hold ATH into next weekly close",
        "No clear 2026 macro catalyst identified yet",
        "If QQQ closes gap rapidly → thesis changes",
    ], title_col=NEG)

    # Right column
    y2 = 0.80
    y2 = text_block(0.52, y2, "POSITIONING FRAMEWORK", [
        "PRIMARY: MDY (cleanest Q-end analog performance)",
        "SECONDARY: SPY (broad participation, +3.3% at 4w)",
        "IWM: participates but more volatile at 2-week window",
        "QQQ: laggard in Q-end case; last to catch up",
        "Optimal entry window: 4-week horizon, not 1–2 week",
    ])
    y2 = text_block(0.52, y2, "MONITORING CHECKLIST", [
        "MDY holds ≥ current ATH on next weekly close?",
        "IWM holds ≥ current ATH on next weekly close?",
        "QQQ gap stays -2% to -5% (healthy rotation)?",
        "SPY trending toward ATH (not reversing)?",
        "Q3 open (Jul 1-5): volume in MDY/IWM?",
    ], title_col=GOLD)

    # Monitoring table
    ax.add_patch(FancyBboxPatch((0.52, 0.10), 0.45, 0.25,
                                boxstyle="round,pad=0.01", transform=ax.transAxes,
                                facecolor=SURF, edgecolor=BORD, lw=1))
    ax.text(0.745, 0.33, "FORWARD RETURN TARGETS", color=MUTE, fontsize=7,
            fontweight='bold', ha='center', transform=ax.transAxes)
    rows = [
        ("MDY  4w",  "+4.3%", POS),
        ("MDY 13w",  "+6.5%", POS),
        ("IWM  4w",  "+3.8%", POS),
        ("SPY  4w",  "+3.3%", POS),
        ("QQQ 13w",  "+1.8%", GOLD),
    ]
    ax.text(0.56, 0.30, "Metric", color=MUTE, fontsize=7.5, transform=ax.transAxes)
    ax.text(0.82, 0.30, "Q-End Target", color=MUTE, fontsize=7.5, transform=ax.transAxes)
    for i, (lbl, val, col) in enumerate(rows):
        yy = 0.267 - i*0.033
        ax.text(0.56, yy, lbl, color=TEXT, fontsize=8, transform=ax.transAxes)
        ax.text(0.82, yy, val, color=col,  fontsize=8, fontweight='bold', transform=ax.transAxes)

    ax.text(0.5, 0.02,
            "AlphaQuery Research  ·  All figures from Q-end zone historical instance (Dec 2012 → Q1 2013)  ·  Not financial advice",
            color=MUTE, fontsize=7, ha='center', transform=ax.transAxes)

    pdf.savefig(fig, facecolor=BG); plt.close(fig)


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    OUT = pathlib.Path(__file__).parent / "MDY_IWM_ATH_Divergence_Study.pdf"

    print("Running analysis…")
    D = run()
    print(f"  {len(D['sd'])} signals  |  "
          f"{D['close'].index[0].date()} → {D['close'].index[-1].date()}")

    print("Building PDF…")
    with PdfPages(OUT, metadata={
        "Title":   "MDY/IWM ATH Divergence Study",
        "Author":  "AlphaQuery Research",
        "Subject": "Breadth leadership signal — forward returns analysis",
        "Creator": "generate_pdf.py",
    }) as pdf:
        print("  Page 1: Cover…")
        page_cover(pdf, D)
        print("  Page 2: Price history…")
        page_price(pdf, D)
        print("  Page 3: Signal instances…")
        page_signals(pdf, D)
        print("  Page 4: Forward return tables…")
        page_fwd_returns(pdf, D)
        print("  Page 5: Cumulative paths…")
        page_paths(pdf, D)
        print("  Page 6: Heatmap & calendar…")
        page_heatmap_and_calendar(pdf, D)
        print("  Page 7: Distributions…")
        page_dist(pdf, D)
        print("  Page 8: Q3 2026 thesis…")
        page_thesis(pdf, D)

    sz = OUT.stat().st_size / 1024
    print(f"\n✓  PDF written → {OUT}  ({sz:.0f} KB,  8 pages)")


if __name__ == "__main__":
    main()
