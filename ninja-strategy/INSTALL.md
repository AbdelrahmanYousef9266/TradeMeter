# NinjaTrader Install Guide

## What You Need

- NinjaTrader 8.1 or later (free or licensed)
- A running TradeMeter backend (see [docs/SETUP.md](../docs/SETUP.md))
- Your TradeMeter connection token (from the TradeMeter **Connect** page after logging in)

---

## Step 1 — Copy the Strategy File

Copy `LiveDataFeedStrategy.cs` to NinjaTrader's custom strategies folder:

```
C:\Users\<YourWindowsUsername>\Documents\NinjaTrader 8\bin\Custom\Strategies\
```

The full default path is usually:
```
C:\Users\YourName\Documents\NinjaTrader 8\bin\Custom\Strategies\LiveDataFeedStrategy.cs
```

Do **not** put it in a subfolder — NinjaTrader expects strategy files directly in the `Strategies\` directory.

---

## Step 2 — Open the NinjaScript Editor and Compile

1. Open NinjaTrader 8
2. In the top menu bar: **Tools → Edit NinjaScript → Strategy...**
3. The NinjaScript Editor window opens. In the left panel you should see `LiveDataFeedStrategy` listed under **Strategies**
4. Double-click `LiveDataFeedStrategy` to open it
5. Press **F5** (or click the **Compile** button in the toolbar)
6. In the output panel at the bottom, you should see:

   ```
   Compilation succeeded for Strategy 'LiveDataFeedStrategy'
   ```

   If you see errors, check the [Troubleshooting section in README.md](README.md#troubleshooting).

---

## Step 3 — Add the Strategy to a Chart

1. Open a **MES** (Micro E-mini S&P 500) chart in NinjaTrader — any bar type works (1 min, 5 min, tick, etc.)
2. Right-click anywhere on the chart
3. Click **Strategies → Add Strategy...**
4. In the strategy list, select **LiveDataFeedStrategy**
5. The parameter dialog opens — **do not click OK yet**, configure parameters first (Step 4)

---

## Step 4 — Configure Parameters

In the parameter dialog you will see a **TradeMeter** group with these fields:

| Parameter | What to enter |
|---|---|
| **Connection Token** | Your token from the TradeMeter Connect page (e.g. `TM-a3f9x2`) |
| **Instrument** | The contract name exactly as it appears in NinjaTrader (e.g. `MES 03-25`) |
| **TradeMeter Host** | `127.0.0.1` for local. Enter your server or Tailscale IP for remote. |
| **TradeMeter Port** | `5000` (leave default unless you changed `NT_TCP_PORT` in your `.env`) |
| **Send Data To TradeMeter** | Leave checked (`true`) to enable streaming |
| **Enable Logging** | Check this during setup so you can verify the connection in the output window |
| **Reconnect Delay (seconds)** | Leave at `5` |

### Where to find your Connection Token

1. Open TradeMeter in your browser (`http://localhost:5173`)
2. Log in with Google if prompted
3. Go to the **Connect** page
4. Your token is displayed in the code box — click **Copy** to copy it
5. Paste it into the **Connection Token** field in NinjaTrader

---

## Step 5 — Enable the Strategy

1. Click **OK** in the parameter dialog
2. In the chart, look for the strategy control panel (usually at the bottom or top of the chart)
3. Click the **Enable** button to activate the strategy
4. The strategy will immediately attempt to connect to TradeMeter

---

## Step 6 — Verify the Connection

### In NinjaTrader

Open the NinjaTrader output window: **New → Output Window**

You should see:
```
TradeMeter: Connected to 127.0.0.1:5000
```

On each bar close:
```
TradeMeter: Sent bar 2025-03-15T14:32:00Z 5843.00
```

If you see:
```
TradeMeter: Disconnected — retrying in 5s
```
→ The backend is not running or the host/port is wrong. Start the backend and check the parameters.

If you see:
```
TradeMeter: Token not set — data not sent
```
→ Open the strategy parameters and fill in the **Connection Token** field.

### In TradeMeter Dashboard

1. Open `http://localhost:5173` in your browser
2. Navigate to the **Connect** page
3. The connection status indicator should turn **green** within a few seconds of the first bar close
4. Navigate to the **Dashboard** — model cards will begin populating with signals after the first bar

---

## Disabling Without Removing

You can pause data streaming at any time by unchecking **Send Data To TradeMeter** in the strategy parameters. This keeps the strategy on the chart (and the TCP connection alive) but stops sending data. Re-check the box to resume.

To fully remove: right-click the chart → Strategies → Remove Strategy → select LiveDataFeedStrategy.

---

## Remote Access (Two Users)

If you and your brother are both running TradeMeter from the same backend server:

1. Each person logs into TradeMeter with their own Google account and gets their own unique token
2. Each NinjaTrader instance uses its own token in the **Connection Token** parameter
3. Set **TradeMeter Host** to the server's IP address (or Tailscale IP) instead of `127.0.0.1`
4. Both connections can be active simultaneously — data is fully isolated per user
