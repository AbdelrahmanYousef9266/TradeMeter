# NinjaTrader Strategy — TradeMeterFeed

## What It Does

TradeMeterFeed is a NinjaScript strategy that runs inside NinjaTrader 8. On every completed bar it sends the OHLCV data plus your TradeMeter connection token to the TradeMeter backend over a TCP socket. Between bar closes, it also sends real-time tick updates so the dashboard price line stays live. The strategy runs on a background thread and handles reconnection automatically — NinjaTrader will never freeze or crash due to a lost connection.

The strategy is **data-only**: it never places, modifies, or cancels any orders.

---

## Install Instructions

See [INSTALL.md](INSTALL.md) for the full step-by-step guide.

---

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `ConnectionToken` | string | *(empty)* | Your TradeMeter NT connection token (e.g. `TM-a3f9x2`). Get this from the TradeMeter **Connect** page after logging in. Case-sensitive. |
| `Instrument` | string | `MES 03-25` | Display name of the futures instrument. Included in every TCP message so the backend knows which contract you are trading. |
| `TradeMeterHost` | string | `127.0.0.1` | IP address of the TradeMeter backend. Use `127.0.0.1` for local development. Use a Tailscale IP or server IP for remote access. |
| `TradeMeterPort` | int | `5000` | TCP port the TradeMeter backend is listening on. Must match `NT_TCP_PORT` in your backend `.env`. |
| `SendDataToForm` | bool | `true` | Master enable/disable switch. Turn off to pause streaming without removing the strategy from the chart. |
| `SendHistorical` | bool | `false` | Bulk-import the chart's loaded history on enable (see below). Requires Training Mode to be ON in the dashboard first. Leave `false` for normal live use. |
| `OnlySendMissing` | bool | `true` | When bulk-importing, ask the backend what it already has (`GET /market/gaps`) and send only the missing/partial days instead of re-blasting the whole chart. Only applies when `SendHistorical` is on. Falls back to sending everything if the backend can't be reached. |
| `BackendHttpPort` | int | `8000` | HTTP/API port of the backend, used for the gap check (separate from the TCP data port; same host). Range: 1–65535. |
| `EnableLogging` | bool | `true` | Log connection events and bar-close sends to the NinjaTrader output window. Disable during active trading sessions to reduce noise. |
| `ReconnectDelaySeconds` | int | `5` | Seconds to wait before retrying after a connection failure. Range: 1–60. |

---

## Bulk-importing chart history (weeks of data in seconds)

Instead of replaying playback in real time, you can push the entire history loaded
on a chart to TradeMeter in one burst. When a strategy is enabled, NinjaTrader
feeds every historical bar through the strategy before going live — so a chart set
to "Days to load: 60" streams ~23,000 one-minute bars in a minute or two.

These bars are sent with `BAR_TYPE = hist` so the backend can tell them apart from
live bars. The backend **only accepts `hist` bars while Training Mode is ON** — this
is deliberate: it keeps a stray bulk import from polluting your live dataset or
fighting the live watermark. Historical bars are stored as training data
(`is_training = true`) and flow through the full feature/learning/trade-sim path,
exactly like real-time playback, but far faster.

**Workflow — import 60 days of MES history:**

1. In the TradeMeter dashboard, turn **Training Mode ON**.
2. Open a NinjaTrader chart for your instrument and set **Days to load** (e.g. 60)
   on the series you want (e.g. 1-minute).
3. Add/enable **TradeMeterFeed** on that chart with **`SendHistorical = true`**
   (and your `ConnectionToken` set). The strategy connects, but bars are **refused
   until you arm ingestion** — nothing stacks yet.
4. In the dashboard press **Arm Ingestion**. The gate opens and the historical
   blast begins flowing.
5. Watch the dashboard **Training banner** count the bars climbing. The NinjaTrader
   output window prints `historical transmission complete — N bars sent` when the
   chart finishes loading and goes live.
6. When done, **Disarm Ingestion** (optionally with *flush* to clear any tail),
   set **`SendHistorical = false`** (disable/re-enable or edit the parameter), and
   turn **Training Mode OFF** in the dashboard for normal live use.

> **Arm gate:** enabling the strategy no longer streams into the pipeline
> immediately. Ingestion starts **disarmed** at backend startup — incoming bars are
> refused at the TCP intake (never queued, never stored) until you press **Arm
> Ingestion** on the dashboard. This is independent of Training Mode: arming decides
> *whether* bars enter the pipeline; Training Mode decides whether accepted
> historical/out-of-order bars bypass the live watermark. For **live** use, just Arm
> Ingestion (no Training Mode).

Notes:
- The blast is throttled (a brief pause every 50 bars) so it won't overwhelm the
  socket or backend.
- If the backend can't be reached during the import, the strategy retries briefly
  then aborts with `historical transmission ABORTED …` rather than hanging — fix
  the connection (and confirm Training Mode is ON) and re-enable the strategy.
- If you forget to enable Training Mode, the backend drops the bars and logs a
  single throttled warning; nothing is imported. Turn it on and re-enable.

### Smart gap-fill (`OnlySendMissing`, default on)

By default the import is **incremental**: before the blast, the strategy calls
`GET /market/gaps?token=…` and gets back the day-level coverage the backend already
has. It then **skips bars on days that are already complete** (≥ 370 bars) up to the
newest bar stored, and sends only:

- days the backend has **no** bars for,
- days that are only **partially** filled, and
- anything **newer** than the newest bar already stored.

So a re-enable after a week sends just that week; a fresh database gets everything.
This is the same coverage the dashboard's **Data** tab shows. A per-timestamp
de-dup remains as a second safety layer, and if the gap check fails (backend down,
timeout, bad token) it logs a warning and falls back to sending everything — the
import is never blocked on the check. Set `OnlySendMissing = false` to force a full
resend.

The gap endpoint replies in a deliberately simple **plain-text** format (no JSON
parsing needed in NinjaScript), all times UTC:

```
2026-06-05,390,13:31,20:00      ← date, distinct bars, first HH:MM, last HH:MM  (one per day)
2026-06-06,412,13:31,20:00
LAST,2026-07-06T19:59:00Z        ← newest stored bar time
```

The output window logs, e.g.:
```
TradeMeter: gap check — 21 days already complete, skipping those; sending missing/partial days + everything after 2026-07-06 19:59:00Z
TradeMeter: historical transmission complete — 480 bars sent (9074 skipped as already present)
```

### Importing a continuous (back-adjusted) contract

To import a long span (e.g. a year of MES) you'll load a **continuous** series
(`MES ##-##`, *Merge Policy = Merge Back Adjusted*) that stitches multiple
quarterly contracts together. That's fully supported:

- The `Instrument` symbol is stored verbatim and may vary across the span — nothing
  keys on the symbol. **De-duplication and coverage are by timestamp only**, and
  the Data tab / gap-fill group by time regardless of symbol.
- **Use ONE consistent merge policy for the whole history.** Do not mix
  back-adjusted and non-adjusted bars in the same import — back-adjustment shifts
  historical prices, so mixing the two produces discontinuities in the price series
  the models learn from. If you switch policy, do a clean-slate reset first
  (`--include-bars`) and re-import.

Large imports are fast: the backend uses a batched COPY + throttled-broadcast path
for historical bars, so ~98k one-minute RTH bars (a year) import in a few minutes.
The training banner shows `Processing N / M` so you can watch it drain.

---

## TCP Message Format

Every message is a single UTF-8 string terminated with `\n`:

```
TOKEN|TIMESTAMP|SYMBOL|OPEN|HIGH|LOW|CLOSE|VOLUME|BAR_TYPE|TIMEFRAME\n
```

`TIMEFRAME` (the 10th field) is the chart's bar period — `1min`, `5min`, … — and
names the **independent series** the bar belongs to. It is sent on every message,
including `hist` and `tick`, so historical bars keep their period even though their
`BAR_TYPE` is `hist`. It is **optional** for backward compatibility: a 9-field
message from an older strategy defaults to `1min`.

Example (bar close, 1-min chart):
```
TM-a3f9x2|2025-03-15T14:32:00Z|MES 03-25|5841.25|5844.00|5840.50|5843.00|980|1min|1min
```

Example (bulk-imported historical bar from a 5-min chart — `BAR_TYPE=hist`, `TIMEFRAME=5min`):
```
TM-a3f9x2|2025-01-20T14:30:00Z|MES 03-25|5841.25|5847.00|5839.50|5845.00|4200|hist|5min
```

Example (tick update):
```
TM-a3f9x2|2025-03-15T14:32:04Z|MES 03-25|5841.25|5844.00|5840.50|5842.75|1043|tick|1min
```

Bar-close messages are sent once per bar (triggered by the first tick of the next bar). Tick messages are sent on every `MarketDataType.Last` event between bar closes. `hist` messages are sent once per historical bar during the initial chart load and require Training Mode to be ON (see "Bulk-importing chart history" above).

### Feeding multiple timeframes

Each timeframe is an independent series in TradeMeter — a 1-min and a 5-min bar at
the same timestamp are different rows and never dedup against each other. To feed
both, **run one chart per timeframe**, each with the strategy enabled:

- Open a **1-minute** chart of your instrument, enable TradeMeterFeed → feeds the `1min` series.
- Open a **5-minute** chart of the same instrument, enable a second TradeMeterFeed → feeds the `5min` series.

Everything is per-timeframe: gap-fill for the 5-min chart checks 5-min coverage
only, and the dashboard **Data** tab has a `1min`/`5min` toggle. (Phase 1 stores
both series; the models still learn from `1min` only — multi-timeframe modelling
is a later phase.)

---

## Troubleshooting

### Strategy won't compile

- Ensure you are using NinjaTrader 8.1 or later
- Check the NinjaScript Editor output panel for the specific error line
- Verify the file was copied to `Documents\NinjaTrader 8\bin\Custom\Strategies\` (not nested in a subfolder)
- Common issue: line-ending differences if the file was edited on macOS/Linux — re-save with Windows CRLF line endings

### Data not appearing in TradeMeter dashboard

1. Check the NinjaTrader output window for `TradeMeter: Connected to 127.0.0.1:5000` — if you see `Disconnected — retrying`, the backend is not reachable
2. Verify the TradeMeter backend is running: `uvicorn app.main:app --port 8000` and confirm the TCP listener started on port 5000
3. Check that `NT_TCP_PORT=5000` in your `.env` matches the `TradeMeterPort` parameter
4. Verify `ConnectionToken` exactly matches the token on the TradeMeter Connect page (case-sensitive, no leading/trailing spaces)
5. Check the backend log for `token validated → user_id=...`. If you see `token not found`, the token is wrong or has been rotated — generate a new one on the Settings page
6. Windows Firewall may block port 5000 — add an inbound rule: Windows Defender Firewall → Advanced Settings → Inbound Rules → New Rule → Port → TCP → 5000

### Output window shows "Token not set — data not sent"

Open the strategy's parameter dialog and fill in the `ConnectionToken` field with the token from the TradeMeter **Connect** page.

### Strategy disconnects repeatedly

- If TradeMeter is on a remote machine (Tailscale or server), confirm the host IP is reachable: run `ping <TradeMeterHost>` from the NinjaTrader machine
- Ensure no VPN or firewall is blocking outbound TCP on port 5000 from the NinjaTrader machine
