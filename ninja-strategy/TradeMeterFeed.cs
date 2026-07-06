#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.IO;
using System.Net;
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

        // ── Historical bulk-import state ────────────────────────────────────────
        private int      _histBarsSent;        // count of UNIQUE historical bars streamed
        private int      _histSkipped;         // bars skipped because the backend already has them
        private bool     _histConnLogged;      // one-time "connected" log for the blast
        private bool     _histAborted;         // connection gave up — stop trying
        private DateTime _lastHistBarTime = DateTime.MinValue;  // dedup guard: last bar time sent

        // ── Gap-fill state (populated from GET /market/gaps before the blast) ───
        private const int HIST_COMPLETE_BARS = 370;   // a day with >= this many bars is "complete"
        private HashSet<string> _completeDays = new HashSet<string>();   // "yyyy-MM-dd" (UTC) already complete
        private DateTime _gapLastBarTime = DateTime.MinValue;            // newest bar the backend already has (UTC)
        private bool     _gapCheckFailed;      // true → couldn't reach backend, send everything (fallback)

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
                SendHistorical        = false;
                OnlySendMissing       = true;
                BackendHttpPort       = 8000;
                EnableLogging         = true;
                ReconnectDelaySeconds = 5;
            }
            else if (State == State.Configure)
            {
                // Reset historical-import counters so a disable/re-enable starts a
                // fresh blast (and a fresh dedup + gap baseline) rather than resuming.
                _histBarsSent    = 0;
                _histSkipped     = 0;
                _histConnLogged  = false;
                _histAborted     = false;
                _lastHistBarTime = DateTime.MinValue;
                _completeDays    = new HashSet<string>();
                _gapLastBarTime  = DateTime.MinValue;
                _gapCheckFailed  = false;
            }
            else if (State == State.DataLoaded)
            {
                // Ask the backend what it already has BEFORE the historical bars
                // start flowing, so the send loop can skip complete days. Runs on
                // the strategy thread; a failure falls back to sending everything.
                if (SendHistorical && OnlySendMissing)
                    RunGapCheck();
            }
            else if (State == State.Realtime)
            {
                // If we were bulk-sending chart history, that phase ends here.
                // Report the total and drop the historical connection; the live
                // reconnect loop opens its own fresh connection below.
                if (SendHistorical)
                {
                    if (EnableLogging && !_histAborted)
                        Print(string.Format(
                            "TradeMeter: historical transmission complete — {0} bars sent ({1} skipped as already present)",
                            _histBarsSent, _histSkipped));
                    Disconnect();
                }
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

        // ── Gap check ──────────────────────────────────────────────────────────

        // Ask the backend (GET /market/gaps) what bar coverage already exists so
        // the historical loop can skip complete days. Plain-text response, parsed
        // with simple string splits (no JSON lib). On ANY failure we set
        // _gapCheckFailed and fall back to sending everything — never block.
        private void RunGapCheck()
        {
            _completeDays   = new HashSet<string>();
            _gapLastBarTime = DateTime.MinValue;
            _gapCheckFailed = false;

            if (string.IsNullOrEmpty(ConnectionToken))
            {
                _gapCheckFailed = true;   // no token → can't ask; send everything
                return;
            }

            try
            {
                string url = string.Format(
                    "http://{0}:{1}/market/gaps?token={2}",
                    TradeMeterHost, BackendHttpPort, Uri.EscapeDataString(ConnectionToken));

                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
                req.Method          = "GET";
                req.Timeout         = 5000;   // don't hang the strategy enable
                req.ReadWriteTimeout = 5000;

                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                using (StreamReader reader = new StreamReader(resp.GetResponseStream()))
                {
                    ParseGapResponse(reader.ReadToEnd());
                }

                if (EnableLogging)
                    Print(string.Format(
                        "TradeMeter: gap check — {0} days already complete, skipping those; sending missing/partial days + everything after {1}",
                        _completeDays.Count,
                        _gapLastBarTime == DateTime.MinValue ? "(nothing yet)" : _gapLastBarTime.ToString("u", CultureInfo.InvariantCulture)));
            }
            catch (Exception ex)
            {
                _gapCheckFailed = true;
                _completeDays.Clear();
                _gapLastBarTime = DateTime.MinValue;
                if (EnableLogging)
                    Print(string.Format(
                        "TradeMeter: gap check failed ({0}) — sending ALL historical bars (fallback). Is the backend HTTP port {1} reachable and Training Mode ON?",
                        ex.Message, BackendHttpPort));
            }
        }

        // Parse the plain-text gap response:
        //   <yyyy-MM-dd>,<bars>,<firstHH:MM>,<lastHH:MM>   one per day (UTC)
        //   LAST,<yyyy-MM-ddTHH:mm:ssZ>                    newest stored bar (UTC)
        private void ParseGapResponse(string body)
        {
            if (string.IsNullOrEmpty(body))
                return;

            foreach (string rawLine in body.Split('\n'))
            {
                string line = rawLine.Trim();
                if (line.Length == 0)
                    continue;

                string[] p = line.Split(',');
                if (p[0] == "LAST")
                {
                    if (p.Length >= 2)
                        DateTime.TryParse(
                            p[1], CultureInfo.InvariantCulture,
                            DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal,
                            out _gapLastBarTime);
                }
                else if (p.Length >= 2)
                {
                    int bars;
                    if (int.TryParse(p[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out bars)
                        && bars >= HIST_COMPLETE_BARS)
                    {
                        _completeDays.Add(p[0]);   // "yyyy-MM-dd" (UTC)
                    }
                }
            }
        }

        // ── Historical bulk send ───────────────────────────────────────────────

        // Stream one historical bar as a "hist" close, opening a dedicated
        // connection on demand and throttling so the socket/backend aren't
        // overwhelmed by a 23k-bar blast. Runs on the historical calculation
        // thread, where brief sleeps are acceptable.
        private void SendHistoricalBar()
        {
            // Defensive de-duplication. OnBarUpdate can fire more than once for the
            // same bar timestamp (e.g. Tick Replay enabled on the series, or an
            // OnEachTick intrabar rebuild), which is what caused ~2.75 copies per
            // bar. Historical bars are delivered in ascending time order, so skip
            // anything that is not strictly newer than the last bar we sent. This
            // guarantees exactly one send per unique bar timestamp — and the counter
            // below (used in the completion log) then reflects unique bars only.
            DateTime barTime = Time[0];

            // Layer 1 — gap skip. Don't resend a bar the backend already has: its
            // day is known complete (>= 370 bars) AND the bar is at or before the
            // newest bar already stored. Bars on missing/partial days, and anything
            // newer than what the backend has, still send. Skipped when the gap
            // check failed (fallback = send everything) or OnlySendMissing is off.
            if (OnlySendMissing && !_gapCheckFailed && _gapLastBarTime != DateTime.MinValue)
            {
                DateTime barUtc = barTime.ToUniversalTime();
                string   dayKey = barUtc.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
                if (_completeDays.Contains(dayKey) && barUtc <= _gapLastBarTime)
                {
                    _histSkipped++;
                    return;
                }
            }

            // Layer 2 — per-timestamp dedup. OnBarUpdate can fire more than once for
            // the same bar timestamp (Tick Replay, or an OnEachTick intrabar rebuild),
            // which caused ~2.75 copies per bar. Historical bars arrive in ascending
            // time order, so skip anything not strictly newer than the last bar sent.
            if (barTime <= _lastHistBarTime)
                return;

            if (!EnsureHistoricalConnection())
                return;   // could not connect / aborted — message already logged

            SendBarData("hist", barTime, Open[0], High[0], Low[0], Close[0],
                        (long)Volume[0], logSend: false);
            _lastHistBarTime = barTime;
            _histBarsSent++;

            // Batch throttle: a short pause every 50 bars keeps ~23k bars flowing
            // in a minute or two without saturating the TCP socket or the backend.
            if (_histBarsSent % 50 == 0)
            {
                try { Thread.Sleep(5); }
                catch (ThreadInterruptedException) { }
            }
        }

        // Ensure a TCP connection exists for the historical blast. Retries a few
        // times on failure, then aborts (rather than hanging the strategy enable)
        // with a clear message. The realtime reconnect thread is not running yet
        // during State.Historical, so it is safe to use _tcpClient/_stream here.
        private bool EnsureHistoricalConnection()
        {
            if (_histAborted)
                return false;

            lock (_lock)
            {
                if (_tcpClient != null && _tcpClient.Connected)
                    return true;
            }

            for (int attempt = 1; attempt <= 3; attempt++)
            {
                try
                {
                    TcpClient client = new TcpClient();
                    client.Connect(TradeMeterHost, TradeMeterPort);

                    lock (_lock)
                    {
                        _tcpClient = client;
                        _stream    = client.GetStream();
                    }

                    if (EnableLogging && !_histConnLogged)
                    {
                        Print(string.Format(
                            "TradeMeter: historical import connected to {0}:{1} — streaming chart history",
                            TradeMeterHost, TradeMeterPort));
                        _histConnLogged = true;
                    }
                    return true;
                }
                catch (Exception ex)
                {
                    if (EnableLogging)
                        Print(string.Format(
                            "TradeMeter: historical connect attempt {0}/3 failed — {1}",
                            attempt, ex.Message));
                    try { Thread.Sleep(500); }
                    catch (ThreadInterruptedException) { return false; }
                }
            }

            _histAborted = true;
            if (EnableLogging)
                Print("TradeMeter: historical transmission ABORTED — could not reach the backend. "
                      + "Check the backend is running and Training Mode is ON, then re-enable the strategy.");
            return false;
        }

        // ── NinjaScript event handlers ─────────────────────────────────────────

        protected override void OnBarUpdate()
        {
            // Only process the primary bar series.
            if (BarsInProgress != 0)
                return;

            // ── Historical bulk import ──────────────────────────────────────
            // While the chart's historical bars load (State.Historical), stream
            // each one as a "hist" bar close IF the user asked for it. Every
            // historical bar is already final, so we send the current bar [0]
            // exactly once. Default (SendHistorical=false) skips history, so
            // normal live-only behavior is unchanged.
            if (State == State.Historical)
            {
                if (SendHistorical && CurrentBar >= 0)
                    SendHistoricalBar();
                return;
            }

            // REQUIRES Calculate = Calculate.OnEachTick (set in SetDefaults). Under
            // that mode IsFirstTickOfBar is true on exactly ONE tick per bar — the
            // first tick of the new bar — meaning the previous bar (index [1]) has
            // just closed and is final. That is what guarantees exactly one live
            // send per closed bar (combined with the BarsInProgress==0 guard above).
            // Do NOT change Calculate to OnBarClose: it would stop OnMarketData from
            // firing (no live tick line). If Calculate is ever changed, this
            // one-send-per-bar guarantee must be re-verified.
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
        [Display(Name = "Send Historical Bars",
                 Description = "Bulk-import the chart's loaded history (bar_type 'hist') on enable, instead of only live/playback bars. "
                             + "Turn ON Training Mode in the dashboard FIRST — the backend rejects historical bars when training mode is off. "
                             + "Set the chart's 'Days to load', enable the strategy, watch the training banner count bars, then turn this OFF for live use.",
                 Order = 6, GroupName = "TradeMeter")]
        public bool SendHistorical { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Only Send Missing",
                 Description = "When bulk-importing, first ask the backend (GET /market/gaps) what it already has and send only the missing/partial days "
                             + "instead of re-blasting the whole chart. A re-enable after a week sends just that week; a fresh database gets everything. "
                             + "Only applies when 'Send Historical Bars' is on. If the backend can't be reached it falls back to sending everything.",
                 Order = 7, GroupName = "TradeMeter")]
        public bool OnlySendMissing { get; set; }

        [NinjaScriptProperty]
        [Range(1, 65535)]
        [Display(Name = "Backend HTTP Port",
                 Description = "HTTP/API port of the TradeMeter backend (default 8000), used for the gap check. Separate from the TCP data port above. "
                             + "Uses the same TradeMeter Host.",
                 Order = 8, GroupName = "TradeMeter")]
        public int BackendHttpPort { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Enable Logging",
                 Description = "Log connection events and bar sends to the NinjaTrader output window. Disable during live trading to reduce noise.",
                 Order = 9, GroupName = "TradeMeter")]
        public bool EnableLogging { get; set; }

        [NinjaScriptProperty]
        [Range(1, 60)]
        [Display(Name = "Reconnect Delay (seconds)",
                 Description = "How long to wait before retrying after a connection failure.",
                 Order = 10, GroupName = "TradeMeter")]
        public int ReconnectDelaySeconds { get; set; }

        #endregion
    }
}
