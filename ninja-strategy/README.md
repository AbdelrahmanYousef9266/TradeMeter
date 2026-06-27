# NinjaTrader Strategy — LiveDataFeedStrategy

## What It Does

LiveDataFeedStrategy is a NinjaScript strategy that runs inside NinjaTrader 8. On every completed bar it serializes the OHLCV data plus your TradeMeter connection token into a single JSON line and sends it to the TradeMeter backend over a TCP socket on port 5000. The strategy handles reconnection automatically if the connection drops mid-session.

---

## Install Instructions

1. **Open NinjaTrader 8**

2. **Open NinjaScript Editor**
   - Menu bar → Tools → Edit NinjaScript → Strategy

3. **Import the strategy file**
   - In the NinjaScript Editor, go to File → Open
   - Navigate to and open `LiveDataFeedStrategy.cs` from this folder
   - Alternatively: copy `LiveDataFeedStrategy.cs` into:
     ```
     C:\Users\<YourName>\Documents\NinjaTrader 8\bin\Custom\Strategies\
     ```

4. **Compile**
   - Click the **Compile** button (F5) in the NinjaScript Editor
   - Verify there are no compilation errors in the output panel

5. **Add to Chart**
   - Open a MES (Micro E-mini S&P 500) chart
   - Right-click the chart → Strategies → Add Strategy
   - Select **LiveDataFeedStrategy** from the list

6. **Configure Parameters** (see table below)

7. **Enable the Strategy**
   - Click **OK** to add the strategy
   - Toggle it to **Enabled** in the strategy control panel

---

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `ConnectionToken` | string | *(empty)* | Your TradeMeter NT connection token (e.g. `TM-a3f9x2`). Get this from the TradeMeter **Connect** page after logging in. |
| `Instrument` | string | `MES 09-24` | The futures instrument to stream. Must match the chart instrument. |
| `SendDataToForm` | bool | `true` | Enable/disable sending data. Turn off without removing the strategy. |
| `EnableLogging` | bool | `false` | Log each sent bar to the NinjaTrader output window. Useful for debugging. |

---

## Troubleshooting

### Strategy won't compile

- Ensure you are using NinjaTrader 8.1 or later
- Check the NinjaScript Editor output panel for the specific error line
- Common issue: missing `using` directives — verify the top of the file includes `using System.Net.Sockets;`

### Data not appearing in TradeMeter dashboard

1. Verify the TradeMeter backend is running (`uvicorn app.main:app --port 8000`)
2. Check that `NT_TCP_PORT=5000` in your `.env` matches port 5000 (the default)
3. Verify your `ConnectionToken` parameter is set correctly — it must exactly match the token shown on the Connect page (case-sensitive)
4. Enable `EnableLogging=true` in the strategy parameters and watch the NinjaTrader output window — you should see a log line for each bar sent
5. Check the backend log for: `token resolved to user_id=...` — if you see `token not found`, the token is wrong or has been rotated
6. Windows Firewall may be blocking port 5000 — add an inbound rule to allow TCP on port 5000 from localhost
