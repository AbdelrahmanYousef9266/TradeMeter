// NinjaTrader 8 strategy — sends OHLCV bars + ConnectionToken to TradeMeter backend via TCP on port 5000.
// Message format: TOKEN|TIMESTAMP|SYMBOL|OPEN|HIGH|LOW|CLOSE|VOLUME|BAR_TYPE\n
// ConnectionToken parameter is pasted by user from TradeMeter Connect page.
// Runs on every tick (Calculate.OnEachTick). Sends bar data on bar close (OnBarUpdate)
// and tick updates (OnMarketData). Uses background thread for TCP — no async/await (.NET 4.8).
// Reconnects automatically after ReconnectDelaySeconds on connection failure.
// DLL references: C:\Program Files\NinjaTrader 8\bin\NinjaTrader.Core.dll, NinjaTrader.Client.dll, NinjaTrader.Gui.dll
