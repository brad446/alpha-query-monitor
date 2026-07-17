# Alpha Query Intelligence — Widget Library (Prototype)

A **Phase 1 proof-of-concept** for an embeddable, white-label widget platform built
on AlphaQuery's volatility & options data — the AlphaQuery answer to the FactSet
Widget Library, but focused on the vol/options specialty where AlphaQuery already
has a data moat.

This prototype exists to make the feasibility argument concrete and demoable. It is
**not production code** — charts are hand-rolled SVG and the data is deterministic
mock data — but every architectural layer the real product needs is represented and
working end-to-end.

## What it demonstrates

| Layer | Where | Status |
|-------|-------|--------|
| Drop-in embedding (Custom Elements) | `widgets/aq-widgets.js` | ✅ real |
| Style isolation (Shadow DOM) | `widgets/aq-widgets.js` | ✅ real |
| Per-instance white-label theming | `demo.html` (two brands) | ✅ real |
| Pluggable data layer (endpoint + fallback) | `widgets/aq-widgets.js` | ✅ real |
| API-key auth | `server/mock-api.js` | ✅ real mechanism, mock keys |
| CORS origin allow-listing (per key) | `server/mock-api.js` | ✅ real mechanism |
| Entitlement tiers (which datasets a key sees) | `server/mock-api.js` | ✅ real mechanism |
| Usage metering (for billing) | `server/mock-api.js` (`GET /usage`) | ✅ in-memory demo |
| The chart data | both | ⚠️ **mock** — swap for real AlphaQuery data |

## The three widgets

- `<aq-iv-term-structure>` — implied volatility across 30–180d tenors (contango/backwardation).
- `<aq-iv-history>` — historical IV time series with an interactive tenor selector.
- `<aq-pcr-gauge>` — put/call ratio sentiment gauge.

## Run it

```bash
# 1) Start the mock data API (zero dependencies)
node prototype/server/mock-api.js        # http://localhost:8787

# 2) Serve the demo page (any static server)
cd prototype && python3 -m http.server 8080
# open http://localhost:8080/demo.html
```

In the demo page, the **Data source** dropdown switches between:
- *Bundled sample data (offline)* — widgets render without any network.
- *Live API — demo-key-pro* — hits the mock API with a fully-entitled key.
- *Live API — demo-key-basic* — a key **without** the history tier, so
  `<aq-iv-history>` returns HTTP 402 and shows a graceful "data unavailable" state.

## Embedding (the customer's view)

```html
<script src="https://cdn.alphaquery.com/widgets/v1/aq-widgets.js"></script>

<aq-iv-term-structure
    ticker="AAPL"
    endpoint="https://widgets-api.alphaquery.com/v1"
    api-key="CUSTOMER_KEY"
    accent="#7c3aed"
    theme="dark"
    radius="14px">
</aq-iv-term-structure>
```

Theming attributes: `theme` (`light`|`dark`), `accent`, `background`, `text`,
`font`, `radius`. With no `endpoint` the widget renders bundled sample data — handy
for previews.

## Mock API surface

```
GET /v1/term-structure?ticker=AAPL     -> IV term structure
GET /v1/iv-history?ticker=AAPL&tenor=30 -> IV history
GET /v1/put-call?ticker=AAPL            -> put/call ratio
GET /usage                              -> usage meter (all keys)

Header: X-AQ-Api-Key: demo-key-pro | demo-key-basic
```

Responses: `401` missing/invalid key · `403` origin not allow-listed for the key ·
`402` dataset not in the key's entitlement tier · `200` data (and increments the meter).

## What Phase 2 would add

Real data wiring to VolVue/EODmetrics, a durable metered-billing store, a self-serve
customer console (issue keys, set origins/tiers, copy embed code), SSO for enterprise,
a build pipeline + CDN, and an expanded widget catalog. See the feasibility notes in
the conversation that produced this prototype.
