/*
 * Alpha Query Intelligence — Mock Widget Data API (PROTOTYPE)
 * ----------------------------------------------------------
 * Zero-dependency Node server that stands in for the real AlphaQuery
 * widget-data backend. It exists to demonstrate the platform plumbing a
 * widget business needs beyond the charts themselves:
 *
 *   1. API-key auth        — X-AQ-Api-Key header, per-customer keys.
 *   2. CORS allow-listing  — a key only works from its registered origins.
 *   3. Entitlement tiers    — which datasets a key may access.
 *   4. Usage metering       — every billable call is counted + logged.
 *
 * The data itself is mock (same deterministic generator the widgets bundle).
 * Swap `generate()` for real AlphaQuery data and this becomes the actual
 * edge service. Run:  node prototype/server/mock-api.js   (default :8787)
 */
'use strict';
const http = require('http');
const { URL } = require('url');

const PORT = process.env.PORT || 8787;

// --- Customer registry (would live in a DB / control plane) --------------
const CUSTOMERS = {
  'demo-key-basic': {
    name: 'Acme Brokerage (Basic)',
    origins: ['http://localhost:8080', 'http://127.0.0.1:8080', 'null'], // 'null' = file:// during dev
    tiers: ['term-structure', 'put-call'], // no history on basic tier
  },
  'demo-key-pro': {
    name: 'Vertex Wealth (Pro)',
    origins: ['*'], // demo convenience; real config would enumerate domains
    tiers: ['term-structure', 'iv-history', 'put-call'],
  },
};

// --- In-memory usage meter (would be a durable counter for billing) ------
const usage = {};
function meter(key, dataset) {
  usage[key] = usage[key] || { total: 0, byDataset: {} };
  usage[key].total++;
  usage[key].byDataset[dataset] = (usage[key].byDataset[dataset] || 0) + 1;
  console.log('[meter] key=%s dataset=%s total=%d', key, dataset, usage[key].total);
}

// --- Mock data (mirrors widgets/aq-widgets.js so demos stay consistent) --
function seededRng(str) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return function () {
    h += 0x6d2b79f5;
    let t = Math.imul(h ^ (h >>> 15), 1 | h);
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const TENORS = [30, 60, 90, 120, 150, 180];
function generate(dataset, ticker, tenor) {
  ticker = (ticker || 'AAPL').toUpperCase();
  if (dataset === 'term-structure') {
    const rnd = seededRng(ticker + ':ts');
    const base = 0.18 + rnd() * 0.35, slope = (rnd() - 0.45) * 0.06;
    return { ticker, dataset, unit: 'iv', points: TENORS.map((t, i) => ({
      tenor: t, iv: Math.max(0.05, base + slope * i + (rnd() - 0.5) * 0.02) })) };
  }
  if (dataset === 'iv-history') {
    tenor = +tenor || 30;
    const rnd = seededRng(ticker + ':h' + tenor);
    let iv = 0.2 + rnd() * 0.25; const points = []; const end = 20260717;
    for (let i = 179; i >= 0; i--) { iv = Math.min(1.2, Math.max(0.06, iv + (rnd() - 0.5) * 0.012)); points.push({ t: end - i, iv }); }
    return { ticker, dataset, tenor, unit: 'iv', points };
  }
  if (dataset === 'put-call') {
    const rnd = seededRng(ticker + ':pcr');
    return { ticker, dataset, ratio: +(0.55 + rnd() * 0.9).toFixed(2), asOf: '2026-07-17' };
  }
  return null;
}

// --- Request handling ----------------------------------------------------
function send(res, status, body, origin) {
  const headers = {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': origin || '*',
    'Access-Control-Allow-Headers': 'X-AQ-Api-Key',
    'Vary': 'Origin',
  };
  res.writeHead(status, headers);
  res.end(JSON.stringify(body));
}

const server = http.createServer((req, res) => {
  const origin = req.headers.origin || '';
  const url = new URL(req.url, 'http://localhost');

  if (req.method === 'OPTIONS') return send(res, 204, {}, origin);

  // Ops endpoint: inspect the usage meter (would be gated in production).
  if (url.pathname === '/usage') return send(res, 200, { usage }, origin);

  const m = url.pathname.match(/^\/v1\/([a-z-]+)$/);
  if (!m) return send(res, 404, { error: 'not found' }, origin);
  const dataset = m[1];

  // 1) Auth
  const key = req.headers['x-aq-api-key'];
  const cust = key && CUSTOMERS[key];
  if (!cust) return send(res, 401, { error: 'missing or invalid API key' }, origin);

  // 2) CORS allow-list (origin bound to the key)
  const originOk = cust.origins.includes('*') || cust.origins.includes(origin) || (!origin && cust.origins.includes('null'));
  if (!originOk) return send(res, 403, { error: 'origin ' + (origin || '(none)') + ' not permitted for this key' }, origin);

  // 3) Entitlement tier
  if (!cust.tiers.includes(dataset)) {
    return send(res, 402, { error: "dataset '" + dataset + "' not in your plan", upgrade: true }, origin);
  }

  const data = generate(dataset, url.searchParams.get('ticker'), url.searchParams.get('tenor'));
  if (!data) return send(res, 404, { error: 'unknown dataset' }, origin);

  // 4) Meter the billable call
  meter(key, dataset);
  return send(res, 200, data, origin);
});

server.listen(PORT, () => {
  console.log('Alpha Query Intelligence mock API on http://localhost:' + PORT);
  console.log('  datasets:  /v1/term-structure  /v1/iv-history  /v1/put-call');
  console.log('  keys:      demo-key-basic (no history) | demo-key-pro (all)');
  console.log('  meter:     GET /usage');
});
