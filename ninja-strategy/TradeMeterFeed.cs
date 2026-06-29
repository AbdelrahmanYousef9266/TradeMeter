#region Using declarations
using System;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Xml.Serialization;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.DrawingTools;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class TradeMeterFeed : Strategy
    {
        // ── Private state ───────────────────────────────────────────────────────
        private TcpClient    _tcpClient;
        private NetworkStream _stream;
        private Thread       _reconnectThread;
        private readonly object _lock = new object();

        // volatile so the reconnect thread always reads the latest value without a lock
        private volatile bool _shouldRun;

        // suppress repeated "token not set" spam — reset when a valid token is seen
        private bool _tokenWarningLogged;

        // ── Lifecycle ──────────────────────────────────────────────────────────
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description                  = "Streams live OHLCV bar data to the TradeMeter backend via TCP. Data-only — places no orders.";
                Name                         = "TradeMeterFeed";
                Calculate                    = Calculate.OnEachTick;
                BarsRequiredToTrade          = 1;
                IsExitOnSessionCloseStrategy = false;

                ConnectionToken       = "";
                Instrument            = "MES 03-25";
                TradeMeterHost        = "127.0.0.1";
                TradeMeterPort        = 5000;
                SendDataToForm        = true;
                EnableLogging         = true;
                ReconnectDelaySeconds = 5;
            }
            else if (State == State.Configure)
            {
                // Nothing required here.
            }
            else if (State == State.Realtime)
            {
                ConnectToTradeMeter();
            }
            else if (State == State.Terminated)
            {
                _shouldRun = false;
                InterruptReconnectThread();
                Disconnect();
            }
            else if (State == State.Finalized)
            {
                // Finalized can fire without Terminated in some edge cases.
                _shouldRun = false;
                InterruptReconnectThread();
                Disconnect();
            }
        }

        // ── Connection management ──────────────────────────────────────────────

        private void ConnectToTradeMeter()
        {
            if (_reconnectThread != null && _reconnectThread.IsAlive)
                return;

            _shouldRun          = true;
            _reconnectThread    = new Thread(ReconnectLoop);
            _reconnectThread.IsBackground = true;
            _reconnectThread.Name         = "TradeMeter_Reconnect";
            _reconnectThread.Start();
        }

        private void ReconnectLoop()
        {
            while (_shouldRun)
            {
                try
                {
                    TcpClient     client = new TcpClient();
                    NetworkStream stream = null;

                    // Attempt to connect. This blocks until connected or throws.
                    client.Connect(TradeMeterHost, TradeMeterPort);
                    stream = client.GetStream();

                    lock (_lock)
                    {
                        _tcpClient = client;
                        _stream    = stream;
                    }

                    if (EnableLogging)
                        Print(string.Format("TradeMeter: Connected to {0}:{1}", TradeMeterHost, TradeMeterPort));

                    // Poll until the connection drops or _shouldRun becomes false.
                    while (_shouldRun)
                    {
                        bool connected;
                        lock (_lock)
                            connected = _tcpClient != null && _tcpClient.Connected;

                        if (!connected)
                            break;

                        try { Thread.Sleep(500); }
                        catch (ThreadInterruptedException) { return; }
                    }

                    if (!_shouldRun)
                        return;

                    if (EnableLogging)
                        Print(string.Format("TradeMeter: Disconnected — retrying in {0}s", ReconnectDelaySeconds));
                }
                catch (ThreadInterruptedException)
                {
                    return;
                }
                catch (Exception)
                {
                    // Clean up any partial connection before retrying.
                    lock (_lock)
                    {
                        if (_stream    != null) { try { _stream.Close();    } catch { } _stream    = null; }
                        if (_tcpClient != null) { try { _tcpClient.Close(); } catch { } _tcpClient = null; }
                    }

                    if (!_shouldRun)
                        return;

                    if (EnableLogging)
                        Print(string.Format("TradeMeter: Disconnected — retrying in {0}s", ReconnectDelaySeconds));
                }

                if (_shouldRun)
                {
                    try { Thread.Sleep(ReconnectDelaySeconds * 1000); }
                    catch (ThreadInterruptedException) { return; }
                }
            }
        }

        private void InterruptReconnectThread()
        {
            try
            {
                if (_reconnectThread != null && _reconnectThread.IsAlive)
                    _reconnectThread.Interrupt();
            }
            catch { }
        }

        private void Disconnect()
        {
            lock (_lock)
            {
                if (_stream != null)
                {
                    try { _stream.Close(); } catch { }
                    _stream = null;
                }
                if (_tcpClient != null)
                {
                    try { _tcpClient.Close(); } catch { }
                    _tcpClient = null;
                }
            }
        }

        // ── Data sending ───────────────────────────────────────────────────────

        // logSend is false for high-frequency tick updates to keep the output window readable.
        private void SendBarData(string barType, DateTime time, double open, double high,
                                 double low, double close, long volume, bool logSend = true)
        {
            if (string.IsNullOrEmpty(ConnectionToken))
            {
                if (EnableLogging && !_tokenWarningLogged)
                {
                    Print("TradeMeter: Token not set — data not sent");
                    _tokenWarningLogged = true;
                }
                return;
            }

            // Reset the warning flag so it fires again if the token is cleared and re-set.
            _tokenWarningLogged = false;

            if (!SendDataToForm)
                return;

            string timestamp = time.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ");

            // TOKEN|TIMESTAMP|SYMBOL|OPEN|HIGH|LOW|CLOSE|VOLUME|BAR_TYPE\n
            string message = string.Format(
                "{0}|{1}|{2}|{3:F2}|{4:F2}|{5:F2}|{6:F2}|{7}|{8}\n",
                ConnectionToken,
                timestamp,
                Instrument,
                open, high, low, close,
                volume,
                barType);

            byte[] bytes = Encoding.UTF8.GetBytes(message);

            try
            {
                lock (_lock)
                {
                    if (_stream == null || _tcpClient == null || !_tcpClient.Connected)
                        return;

                    _stream.Write(bytes, 0, bytes.Length);
                }

                if (EnableLogging && logSend)
                    Print(string.Format("TradeMeter: Sent bar {0} {1:F2}", timestamp, close));
            }
            catch (Exception ex)
            {
                if (EnableLogging)
                    Print(string.Format("TradeMeter: Send failed — {0}", ex.Message));

                // Null out the connection so the reconnect loop detects the drop
                // on its next poll and starts a fresh connection attempt.
                lock (_lock)
                {
                    if (_stream    != null) { try { _stream.Close();    } catch { } _stream    = null; }
                    if (_tcpClient != null) { try { _tcpClient.Close(); } catch { } _tcpClient = null; }
                }
            }
        }

        // ── NinjaScript event handlers ─────────────────────────────────────────

        protected override void OnBarUpdate()
        {
            // Only process the primary bar series.
            if (BarsInProgress != 0)
                return;

            // With Calculate.OnEachTick, IsFirstTickOfBar is true on the very first
            // tick that belongs to the new (current) bar — meaning the previous bar
            // (index [1]) has just closed and its data is final. This is the standard
            // NinjaScript pattern for detecting a bar close without switching to
            // Calculate.OnBarClose (which would prevent OnMarketData from firing).
            if (!IsFirstTickOfBar)
                return;

            // Need at least one completed bar before reading index [1].
            if (CurrentBar < 1)
                return;

            SendBarData(GetBarTypeString(), Time[1], Open[1], High[1], Low[1], Close[1], (long)Volume[1],
                        logSend: true);
        }

        protected override void OnMarketData(MarketDataEventArgs marketDataUpdate)
        {
            // Only handle last-trade ticks for real-time between-bar updates.
            if (marketDataUpdate.MarketDataType != MarketDataType.Last)
                return;

            // Guard against accessing the bar series before any bars have formed.
            if (CurrentBar < 0)
                return;

            // Send the current bar-in-progress state at the tick's price.
            // High[0] and Low[0] already reflect the running high/low of the forming bar.
            // Do not log individual ticks — this fires dozens of times per second.
            SendBarData(
                "tick",
                marketDataUpdate.Time,
                Open[0],
                High[0],
                Low[0],
                marketDataUpdate.Price,
                (long)Volume[0],
                logSend: false);
        }

        // ── Helpers ────────────────────────────────────────────────────────────

        private string GetBarTypeString()
        {
            switch (BarsPeriod.BarsPeriodType)
            {
                case BarsPeriodType.Minute:  return BarsPeriod.Value + "min";
                case BarsPeriodType.Tick:    return BarsPeriod.Value + "tick";
                case BarsPeriodType.Second:  return BarsPeriod.Value + "sec";
                case BarsPeriodType.Day:     return BarsPeriod.Value + "day";
                case BarsPeriodType.Volume:  return BarsPeriod.Value + "vol";
                case BarsPeriodType.Range:   return BarsPeriod.Value + "rng";
                default:                     return BarsPeriod.BarsPeriodType.ToString().ToLower();
            }
        }

        // ── Parameters ─────────────────────────────────────────────────────────
        #region Properties

        [NinjaScriptProperty]
        [Display(Name = "Connection Token",
                 Description = "Your TradeMeter NT connection token from the Connect page (e.g. TM-a3f9x2). Case-sensitive.",
                 Order = 1, GroupName = "TradeMeter")]
        public string ConnectionToken { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Instrument",
                 Description = "Display name of the instrument being streamed (e.g. MES 03-25). Included in every message.",
                 Order = 2, GroupName = "TradeMeter")]
        public string Instrument { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "TradeMeter Host",
                 Description = "IP address of the TradeMeter backend. Use 127.0.0.1 for local, or a Tailscale/server IP for remote.",
                 Order = 3, GroupName = "TradeMeter")]
        public string TradeMeterHost { get; set; }

        [NinjaScriptProperty]
        [Range(1, 65535)]
        [Display(Name = "TradeMeter Port",
                 Description = "TCP port the TradeMeter backend is listening on (default 5000).",
                 Order = 4, GroupName = "TradeMeter")]
        public int TradeMeterPort { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Send Data To TradeMeter",
                 Description = "Master enable/disable switch. Turn off to pause streaming without removing the strategy.",
                 Order = 5, GroupName = "TradeMeter")]
        public bool SendDataToForm { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Enable Logging",
                 Description = "Log connection events and bar sends to the NinjaTrader output window. Disable during live trading to reduce noise.",
                 Order = 6, GroupName = "TradeMeter")]
        public bool EnableLogging { get; set; }

        [NinjaScriptProperty]
        [Range(1, 60)]
        [Display(Name = "Reconnect Delay (seconds)",
                 Description = "How long to wait before retrying after a connection failure.",
                 Order = 7, GroupName = "TradeMeter")]
        public int ReconnectDelaySeconds { get; set; }

        #endregion
    }
}
