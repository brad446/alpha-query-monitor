/*
 * Alpha Query Intelligence — Embeddable Widget Library (PROTOTYPE)
 * ----------------------------------------------------------------
 * A dependency-free set of Custom Elements that render AlphaQuery
 * volatility / options intelligence inside ANY third-party web page.
 *
 * Value prop demonstrated here:
 *   - Drop-in embedding:  <aq-iv-term-structure ticker="AAPL"></aq-iv-term-structure>
 *   - Style isolation:    Shadow DOM — host-page CSS can't leak in, ours can't leak out.
 *   - White-label theming: per-instance brand tokens (accent / bg / text / font / radius).
 *   - Pluggable data:     `endpoint` + `api-key` attributes hit the AlphaQuery API;
 *                         with no endpoint the widget falls back to bundled mock data,
 *                         so the catalog is demoable offline.
 *
 * This is a PROTOTYPE: charts are hand-rolled SVG (no chart lib), and the
 * default data is deterministic mock data. Wire `endpoint` to the mock API
 * server (../server/mock-api.js) or a real AlphaQuery API to see live plumbing.
 */
(function () {
  'use strict';

  /* ----------------------------- data layer ----------------------------- */

  // Deterministic PRNG so a given ticker always renders the same mock shape.
  // (Demo stability only — real data comes from `endpoint`.)
  function seededRng(str) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return function () {
      h += 0x6d2b79f5;
      let t = Math.imul(h ^ (h >>> 15), 1 | h);
      t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const TENORS = [30, 60, 90, 120, 150, 180];

  const MockData = {
    'term-structure': function (ticker) {
      const rnd = seededRng(ticker + ':ts');
      const base = 0.18 + rnd() * 0.35; // 18%–53% front-month IV
      const slope = (rnd() - 0.45) * 0.06; // contango or backwardation
      const points = TENORS.map(function (t, i) {
        const noise = (rnd() - 0.5) * 0.02;
        return { tenor: t, iv: Math.max(0.05, base + slope * i + noise) };
      });
      return { ticker: ticker, dataset: 'term-structure', unit: 'iv', points: points };
    },
    'iv-history': function (ticker, tenor) {
      tenor = tenor || 30;
      const rnd = seededRng(ticker + ':h' + tenor);
      const n = 180;
      let iv = 0.2 + rnd() * 0.25;
      const series = [];
      const end = 20260717; // fixed reference date (yyyymmdd) — deterministic demo
      for (let i = n - 1; i >= 0; i--) {
        iv += (rnd() - 0.5) * 0.012;
        iv = Math.min(1.2, Math.max(0.06, iv));
        series.push({ t: end - i, iv: iv });
      }
      return { ticker: ticker, dataset: 'iv-history', tenor: tenor, unit: 'iv', points: series };
    },
    'put-call': function (ticker) {
      const rnd = seededRng(ticker + ':pcr');
      return {
        ticker: ticker,
        dataset: 'put-call',
        ratio: +(0.55 + rnd() * 0.9).toFixed(2), // 0.55–1.45
        asOf: '2026-07-17',
      };
    },
  };

  // Fetch from a configured endpoint, else fall back to mock. Never throws to the caller.
  async function loadData(cfg, dataset, params) {
    params = params || {};
    if (cfg.endpoint) {
      try {
        const url = new URL(cfg.endpoint.replace(/\/$/, '') + '/' + dataset);
        url.searchParams.set('ticker', cfg.ticker);
        Object.keys(params).forEach(function (k) { url.searchParams.set(k, params[k]); });
        const res = await fetch(url.toString(), {
          headers: cfg.apiKey ? { 'X-AQ-Api-Key': cfg.apiKey } : {},
        });
        if (!res.ok) {
          const body = await res.json().catch(function () { return {}; });
          throw new Error(body.error || ('HTTP ' + res.status));
        }
        return { source: 'api', data: await res.json() };
      } catch (err) {
        return { source: 'error', error: err.message };
      }
    }
    const gen = MockData[dataset];
    return { source: 'mock', data: gen(cfg.ticker, params.tenor) };
  }

  /* --------------------------- theming + shell -------------------------- */

  const PRESETS = {
    light: { bg: '#ffffff', text: '#0f172a', muted: '#64748b', grid: '#e2e8f0', accent: '#2563eb' },
    dark: { bg: '#0b1120', text: '#e2e8f0', muted: '#94a3b8', grid: '#1e293b', accent: '#38bdf8' },
  };

  // Base class: config parsing, theming, loading/error chrome, lifecycle.
  class AQWidget extends HTMLElement {
    static get observedAttributes() {
      return ['ticker', 'endpoint', 'api-key', 'theme', 'accent', 'background', 'text', 'font', 'radius'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._raf = null;
    }

    connectedCallback() { this._render(); }
    attributeChangedCallback() { if (this.isConnected) this._scheduleRender(); }

    _scheduleRender() {
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => { this._raf = null; this._render(); });
    }

    get config() {
      return {
        ticker: (this.getAttribute('ticker') || 'AAPL').toUpperCase(),
        endpoint: this.getAttribute('endpoint') || '',
        apiKey: this.getAttribute('api-key') || '',
      };
    }

    _theme() {
      const preset = PRESETS[this.getAttribute('theme')] || PRESETS.light;
      return {
        bg: this.getAttribute('background') || preset.bg,
        text: this.getAttribute('text') || preset.text,
        muted: preset.muted,
        grid: preset.grid,
        accent: this.getAttribute('accent') || preset.accent,
        font: this.getAttribute('font') || 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
        radius: this.getAttribute('radius') || '12px',
      };
    }

    _shell(title, subtitle, bodyHtml) {
      const t = this._theme();
      this.shadowRoot.innerHTML =
        '<style>' +
        ':host{display:block;contain:content}' +
        '.card{background:' + t.bg + ';color:' + t.text + ';font-family:' + t.font + ';' +
          'border:1px solid ' + t.grid + ';border-radius:' + t.radius + ';padding:16px 18px;' +
          'box-shadow:0 1px 2px rgba(0,0,0,.04);box-sizing:border-box}' +
        '.hd{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:4px}' +
        '.ttl{font-size:14px;font-weight:650;letter-spacing:.01em}' +
        '.tk{font-size:12px;font-weight:600;color:' + t.accent + '}' +
        '.sub{font-size:11px;color:' + t.muted + ';margin-bottom:10px}' +
        '.bd{position:relative}' +
        '.wm{position:absolute;right:0;bottom:-6px;font-size:9px;color:' + t.muted + ';opacity:.7}' +
        '.msg{font-size:12px;color:' + t.muted + ';padding:24px 0;text-align:center}' +
        '.err{color:#dc2626}' +
        '.btns{display:flex;gap:4px;margin:2px 0 10px}' +
        '.btn{font:600 11px/1 ' + t.font + ';color:' + t.muted + ';background:transparent;cursor:pointer;' +
          'border:1px solid ' + t.grid + ';border-radius:999px;padding:5px 9px}' +
        '.btn[aria-pressed=true]{color:#fff;background:' + t.accent + ';border-color:' + t.accent + '}' +
        'svg{display:block;width:100%;height:auto;overflow:visible}' +
        '.dot{fill:' + t.accent + '}' +
        '</style>' +
        '<div class="card">' +
          '<div class="hd"><span class="ttl">' + title + '</span><span class="tk">' + this.config.ticker + '</span></div>' +
          '<div class="sub">' + (subtitle || '') + '</div>' +
          '<div class="bd">' + bodyHtml + '<span class="wm">Alpha Query Intelligence</span></div>' +
        '</div>';
    }

    _loading(title) { this._shell(title, '', '<div class="msg">Loading…</div>'); }
    _error(title, msg) {
      this._shell(title, '', '<div class="msg err">Data unavailable — ' + esc(msg) + '</div>');
    }

    _sourceNote(res) {
      return res.source === 'mock' ? 'Sample data · connect an endpoint for live data'
           : res.source === 'api' ? 'Live · AlphaQuery API'
           : '';
    }
  }

  /* ------------------------------ helpers ------------------------------- */

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function pct(x) { return (x * 100).toFixed(1) + '%'; }

  // Minimal SVG line chart. data: [{x,y}] in data space. Returns markup string.
  function lineChart(data, opts) {
    const W = 320, H = 150, P = { l: 34, r: 10, t: 8, b: 20 };
    const xs = data.map(function (d) { return d.x; });
    const ys = data.map(function (d) { return d.y; });
    const xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs);
    const ymin = Math.min.apply(null, ys) * 0.97, ymax = Math.max.apply(null, ys) * 1.03;
    const sx = function (x) { return P.l + (xmax === xmin ? 0 : (x - xmin) / (xmax - xmin)) * (W - P.l - P.r); };
    const sy = function (y) { return H - P.b - (ymax === ymin ? 0 : (y - ymin) / (ymax - ymin)) * (H - P.t - P.b); };

    let grid = '', ylab = '';
    const rows = 4;
    for (let i = 0; i <= rows; i++) {
      const yv = ymin + (i / rows) * (ymax - ymin);
      const yy = sy(yv);
      grid += '<line x1="' + P.l + '" y1="' + yy + '" x2="' + (W - P.r) + '" y2="' + yy +
        '" stroke="' + opts.grid + '" stroke-width="1"/>';
      ylab += '<text x="' + (P.l - 5) + '" y="' + (yy + 3) + '" text-anchor="end" font-size="9" fill="' +
        opts.muted + '">' + (yv * 100).toFixed(0) + '%</text>';
    }
    let xlab = '';
    (opts.xticks || []).forEach(function (xt) {
      xlab += '<text x="' + sx(xt.x) + '" y="' + (H - P.b + 13) + '" text-anchor="middle" font-size="9" fill="' +
        opts.muted + '">' + esc(xt.label) + '</text>';
    });

    const path = data.map(function (d, i) { return (i ? 'L' : 'M') + sx(d.x).toFixed(1) + ' ' + sy(d.y).toFixed(1); }).join(' ');
    const area = 'M' + sx(data[0].x) + ' ' + sy(ymin) + ' ' +
      data.map(function (d) { return 'L' + sx(d.x).toFixed(1) + ' ' + sy(d.y).toFixed(1); }).join(' ') +
      ' L' + sx(data[data.length - 1].x) + ' ' + sy(ymin) + ' Z';
    const dots = opts.dots ? data.map(function (d) {
      return '<circle class="dot" cx="' + sx(d.x).toFixed(1) + '" cy="' + sy(d.y).toFixed(1) + '" r="2.5"/>'; }).join('') : '';

    return '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(opts.aria || 'chart') + '">' +
      '<defs><linearGradient id="aqfill" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="' + opts.accent + '" stop-opacity="0.18"/>' +
      '<stop offset="1" stop-color="' + opts.accent + '" stop-opacity="0"/></linearGradient></defs>' +
      grid + ylab + xlab +
      '<path d="' + area + '" fill="url(#aqfill)"/>' +
      '<path d="' + path + '" fill="none" stroke="' + opts.accent + '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>' +
      dots + '</svg>';
  }

  /* ------------------------------ widgets ------------------------------- */

  // 1) IV Term Structure — implied vol across standard tenors.
  class AQTermStructure extends AQWidget {
    async _render() {
      this._loading('IV Term Structure');
      const res = await loadData(this.config, 'term-structure');
      if (res.source === 'error') return this._error('IV Term Structure', res.error);
      const t = this._theme();
      const pts = res.data.points;
      const data = pts.map(function (p) { return { x: p.tenor, y: p.iv }; });
      const chart = lineChart(data, {
        accent: t.accent, grid: t.grid, muted: t.muted, dots: true,
        xticks: pts.map(function (p) { return { x: p.tenor, label: p.tenor + 'd' }; }),
        aria: this.config.ticker + ' implied volatility term structure',
      });
      const front = pts[0].iv, back = pts[pts.length - 1].iv;
      const shape = back > front ? 'Contango' : 'Backwardation';
      this._shell('IV Term Structure', shape + ' · ' + pct(front) + ' → ' + pct(back) + ' · ' + this._sourceNote(res), chart);
    }
  }

  // 2) IV History — historical implied vol time series with a tenor selector.
  class AQIvHistory extends AQWidget {
    constructor() { super(); this._tenor = 30; }
    async _render() {
      const title = 'Implied Volatility History';
      this._loading(title);
      const res = await loadData(this.config, 'iv-history', { tenor: this._tenor });
      if (res.source === 'error') return this._error(title, res.error);
      const t = this._theme();
      const pts = res.data.points;
      const data = pts.map(function (p, i) { return { x: i, y: p.iv }; });
      const last = pts[pts.length - 1].iv, first = pts[0].iv;
      const chg = ((last - first) / first) * 100;
      const chart = lineChart(data, {
        accent: t.accent, grid: t.grid, muted: t.muted,
        xticks: [{ x: 0, label: '~6mo ago' }, { x: data.length - 1, label: 'today' }],
        aria: this.config.ticker + ' ' + this._tenor + '-day implied volatility history',
      });
      const btns = '<div class="btns">' + TENORS.map((tn) =>
        '<button class="btn" data-tenor="' + tn + '" aria-pressed="' + (tn === this._tenor) + '">' + tn + 'd</button>'
      ).join('') + '</div>';
      this._shell(title,
        this._tenor + '-day · now ' + pct(last) + ' · ' + (chg >= 0 ? '+' : '') + chg.toFixed(1) + '% over window · ' + this._sourceNote(res),
        btns + chart);
      this.shadowRoot.querySelectorAll('.btn').forEach((b) => {
        b.addEventListener('click', () => { this._tenor = +b.getAttribute('data-tenor'); this._render(); });
      });
    }
  }

  // 3) Put/Call Ratio — sentiment gauge.
  class AQPutCallGauge extends AQWidget {
    async _render() {
      const title = 'Put / Call Ratio';
      this._loading(title);
      const res = await loadData(this.config, 'put-call');
      if (res.source === 'error') return this._error(title, res.error);
      const t = this._theme();
      const r = res.data.ratio;
      const max = 2, frac = Math.min(1, r / max);
      const W = 320, cx = W / 2, cy = 120, rad = 92;
      // Top semicircle: sweep left (π) up and over to right (2π) so increasing
      // angle traces the visible gauge track. sin is negative over the top half.
      const a0 = Math.PI, a1 = 2 * Math.PI;
      const ang = a0 + (a1 - a0) * frac;
      const arc = function (from, to, color, width) {
        const x1 = cx + rad * Math.cos(from), y1 = cy + rad * Math.sin(from);
        const x2 = cx + rad * Math.cos(to), y2 = cy + rad * Math.sin(to);
        const large = Math.abs(to - from) > Math.PI ? 1 : 0;
        return '<path d="M' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' A' + rad + ' ' + rad + ' 0 ' + large + ' 1 ' +
          x2.toFixed(1) + ' ' + y2.toFixed(1) + '" fill="none" stroke="' + color + '" stroke-width="' + width + '" stroke-linecap="round"/>';
      };
      const needleX = cx + (rad - 6) * Math.cos(ang), needleY = cy + (rad - 6) * Math.sin(ang);
      const sentiment = r < 0.7 ? 'Bullish skew' : r > 1.0 ? 'Bearish skew' : 'Neutral';
      const svg = '<svg viewBox="0 0 ' + W + ' 150" role="img" aria-label="put call ratio ' + r + '">' +
        arc(a0, a1, t.grid, 12) +
        arc(a0, ang, t.accent, 12) +
        '<line x1="' + cx + '" y1="' + cy + '" x2="' + needleX.toFixed(1) + '" y2="' + needleY.toFixed(1) +
          '" stroke="' + t.text + '" stroke-width="2.5" stroke-linecap="round"/>' +
        '<circle cx="' + cx + '" cy="' + cy + '" r="4" fill="' + t.text + '"/>' +
        '<text x="' + cx + '" y="' + (cy - 22) + '" text-anchor="middle" font-size="30" font-weight="700" fill="' + t.text + '">' + r.toFixed(2) + '</text>' +
        '<text x="' + (cx - rad) + '" y="' + (cy + 18) + '" text-anchor="middle" font-size="9" fill="' + t.muted + '">0</text>' +
        '<text x="' + (cx + rad) + '" y="' + (cy + 18) + '" text-anchor="middle" font-size="9" fill="' + t.muted + '">2.0</text>' +
        '</svg>';
      this._shell(title, sentiment + ' · as of ' + res.data.asOf + ' · ' + this._sourceNote(res), svg);
    }
  }

  /* ---------------------------- registration ---------------------------- */

  const defs = [
    ['aq-iv-term-structure', AQTermStructure],
    ['aq-iv-history', AQIvHistory],
    ['aq-pcr-gauge', AQPutCallGauge],
  ];
  defs.forEach(function (d) { if (!customElements.get(d[0])) customElements.define(d[0], d[1]); });

  // Expose catalog metadata for an embed-code generator / catalog UI.
  window.AQWidgets = {
    version: '0.1.0-prototype',
    catalog: [
      { tag: 'aq-iv-term-structure', name: 'IV Term Structure', dataset: 'term-structure' },
      { tag: 'aq-iv-history', name: 'Implied Volatility History', dataset: 'iv-history' },
      { tag: 'aq-pcr-gauge', name: 'Put / Call Ratio', dataset: 'put-call' },
    ],
  };
})();
