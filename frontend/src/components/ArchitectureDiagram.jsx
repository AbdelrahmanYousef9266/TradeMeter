/**
 * Animated architecture diagram — TradeMeter dual-timeframe data flow (Phase 2).
 *
 * Depicts the real system: two NinjaTrader charts (1-min + 5-min) → Redis →
 * FastAPI, which fans out into TWO parallel pipelines. The 5-min pipeline is the
 * primary (trading) series — 9 online models + LSTM (10) — and is emphasised in
 * teal with a glow; the 1-min pipeline is context — 9 online models — in purple.
 * Both persist per-timeframe to TimescaleDB + MLflow and feed the 19-model
 * dashboard. 19 competitors total (9×1-min + 10×5-min).
 *
 * Self-contained: inline SVG + scoped CSS animations, using the app's CSS
 * variables so it adapts to the theme. The SVG markup is kept visually identical
 * to the standalone version at /architecture.html (only attribute casing differs
 * — JSX requires camelCase). Animations use only stroke-dashoffset, opacity and
 * transform (GPU-friendly) and are gated behind prefers-reduced-motion.
 *
 * The diagram is right-aligned within its container (compact mode hugs the right
 * edge so it sits on the right of the AFK panel / stream column).
 */
export default function ArchitectureDiagram({ compact = false }) {
  return (
    <div style={{
      width: '100%',
      maxWidth: compact ? '100%' : '720px',
      height: compact ? '100%' : 'auto',
      margin: '0 0 0 auto',                 // right-align within its container
      display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
    }}>
      <style>{`
        @keyframes tm-dash { to { stroke-dashoffset: -16; } }
        @keyframes tm-pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        @keyframes tm-glow { 0%,100%{opacity:.18} 50%{opacity:.55} }
        @keyframes tm-travel {
          0%   { opacity:0; transform: translateY(0); }
          12%  { opacity:1; }
          88%  { opacity:1; }
          100% { opacity:0; transform: translateY(var(--tm-dist, 30px)); }
        }
        @media (prefers-reduced-motion: no-preference) {
          .tm-flow  { stroke-dasharray:6 6; animation: tm-dash 1.2s linear infinite; }
          .tm-loop  { stroke-dasharray:5 7; animation: tm-dash 2s linear infinite; }
          .tm-dot   { animation: tm-pulse 1.8s ease-in-out infinite; }
          .tm-glow  { animation: tm-glow 2.6s ease-in-out infinite; }
          .tm-bar   { animation: tm-travel 2.4s linear infinite; }
        }
      `}</style>

      <svg viewBox="0 0 720 660" width="100%" role="img"
           preserveAspectRatio={compact ? 'xMaxYMid meet' : 'xMidYMid meet'}
           style={{ display: 'block', maxWidth: '100%', maxHeight: '100%', height: compact ? '100%' : 'auto' }}
           aria-label="TradeMeter dual-timeframe architecture: two NinjaTrader charts (1-min and 5-min) tag each bar's timeframe, flow through Redis and a timeframe-routing FastAPI backend into two parallel pipelines — a 1-min context pipeline of 9 online models and a primary 5-min pipeline of 9 online models plus an LSTM — then persist per timeframe to TimescaleDB and MLflow and feed the 19-model dashboard.">
        <defs>
          <marker id="tm-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="context-stroke" />
          </marker>
          {/* Soft blur used for the glow-pulse behind key nodes */}
          <filter id="tm-soft" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="5" />
          </filter>
        </defs>

        {/* ══════════════ DATA IN — two NinjaTrader charts ══════════════ */}

        {/* 1-min chart (context — purple) */}
        <rect x="55" y="24" width="270" height="52" rx="11"
              fill="var(--surface-2)" stroke="#7F77DD" strokeWidth="1.5" />
        <text x="190" y="46" textAnchor="middle" fontSize="12.5" fontWeight="600" fill="var(--text-primary)">NinjaTrader · 1-min chart</text>
        <text x="190" y="63" textAnchor="middle" fontSize="9.5" fill="var(--text-muted)">tags TIMEFRAME=1min</text>

        {/* 5-min chart (primary — teal, glow) */}
        <rect className="tm-glow" x="395" y="24" width="270" height="52" rx="11"
              fill="none" stroke="#1D9E75" strokeWidth="3" filter="url(#tm-soft)" />
        <rect x="395" y="24" width="270" height="52" rx="11"
              fill="var(--surface-2)" stroke="#1D9E75" strokeWidth="2" />
        <text x="530" y="46" textAnchor="middle" fontSize="12.5" fontWeight="700" fill="var(--text-primary)">NinjaTrader · 5-min chart</text>
        <text x="530" y="63" textAnchor="middle" fontSize="9.5" fill="var(--text-muted)">tags TIMEFRAME=5min · primary</text>

        {/* Both charts → Redis (converge) */}
        <line x1="190" y1="76" x2="300" y2="114" className="tm-flow" stroke="#7F77DD" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <line x1="530" y1="76" x2="420" y2="114" className="tm-flow" stroke="#1D9E75" strokeWidth="2" markerEnd="url(#tm-arrow)" />

        {/* Redis Streams */}
        <rect x="210" y="116" width="300" height="54" rx="11"
              fill="var(--surface-2)" stroke="#5271ff" strokeWidth="1.5" />
        <text x="360" y="138" textAnchor="middle" fontSize="12.5" fontWeight="600" fill="var(--text-primary)">TCP :5000 → Redis Streams</text>
        <text x="360" y="156" textAnchor="middle" fontSize="9.5" fill="var(--text-muted)">arm gate · consumer groups</text>

        {/* Redis → backend */}
        <line x1="360" y1="170" x2="360" y2="196" className="tm-flow" stroke="#5271ff" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <circle className="tm-bar" cx="360" cy="172" r="3" fill="#5271ff" style={{ ['--tm-dist']: '22px' }} />
        <circle className="tm-bar" cx="360" cy="172" r="3" fill="#5271ff" style={{ ['--tm-dist']: '22px', animationDelay: '1.2s' }} />

        {/* FastAPI backend */}
        <rect x="210" y="198" width="300" height="52" rx="11"
              fill="var(--surface-2)" stroke="#5271ff" strokeWidth="1.5" />
        <text x="360" y="220" textAnchor="middle" fontSize="12.5" fontWeight="600" fill="var(--text-primary)">FastAPI backend</text>
        <text x="360" y="237" textAnchor="middle" fontSize="9.5" fill="var(--text-muted)">routes by timeframe</text>

        {/* Backend → split into two pipelines */}
        <line x1="330" y1="250" x2="200" y2="286" className="tm-flow" stroke="#7F77DD" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <line x1="390" y1="250" x2="520" y2="286" className="tm-flow" stroke="#1D9E75" strokeWidth="2" markerEnd="url(#tm-arrow)" />

        {/* ══════════════ LEFT — 1-min pipeline (context, purple) ══════════════ */}
        <rect x="40" y="288" width="300" height="182" rx="14"
              fill="var(--surface-2)" stroke="#7F77DD" strokeWidth="1.2" />
        <text x="190" y="308" textAnchor="middle" fontSize="10" fontWeight="700" letterSpacing="1.2" fill="#7F77DD">1-MIN PIPELINE · CONTEXT</text>

        <rect x="60" y="316" width="260" height="40" rx="9" fill="var(--bg)" stroke="var(--border-strong)" strokeWidth="1" />
        <text x="190" y="334" textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--text-primary)">Feature engine</text>
        <text x="190" y="348" textAnchor="middle" fontSize="9" fill="var(--text-muted)">16 features per bar</text>
        <line x1="190" y1="356" x2="190" y2="364" className="tm-flow" stroke="#7F77DD" strokeWidth="1.5" markerEnd="url(#tm-arrow)" />

        <rect x="60" y="366" width="260" height="40" rx="9" fill="var(--bg)" stroke="var(--border-strong)" strokeWidth="1" />
        <text x="190" y="384" textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--text-primary)">9 online models</text>
        <text x="190" y="398" textAnchor="middle" fontSize="9" fill="var(--text-muted)">River online-learners</text>
        <line x1="190" y1="406" x2="190" y2="414" className="tm-flow" stroke="#7F77DD" strokeWidth="1.5" markerEnd="url(#tm-arrow)" />

        <rect x="60" y="416" width="260" height="42" rx="9" fill="var(--bg)" stroke="var(--border-strong)" strokeWidth="1" />
        <text x="190" y="435" textAnchor="middle" fontSize="10.5" fontWeight="600" fill="var(--text-primary)">predict → trade → learn</text>
        <text x="190" y="449" textAnchor="middle" fontSize="9" fill="#7F77DD">↻ continuous loop</text>

        {/* ══════════════ RIGHT — 5-min pipeline (primary, teal, glow) ══════════════ */}
        <rect className="tm-glow" x="380" y="288" width="300" height="182" rx="14"
              fill="none" stroke="#1D9E75" strokeWidth="2.5" filter="url(#tm-soft)" />
        <rect x="380" y="288" width="300" height="182" rx="14"
              fill="var(--surface-2)" stroke="#1D9E75" strokeWidth="2" />
        <text x="530" y="308" textAnchor="middle" fontSize="10" fontWeight="700" letterSpacing="1.2" fill="#1D9E75">5-MIN PIPELINE · PRIMARY</text>

        <rect x="400" y="316" width="260" height="40" rx="9" fill="var(--bg)" stroke="var(--border-strong)" strokeWidth="1" />
        <text x="530" y="334" textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--text-primary)">Feature engine</text>
        <text x="530" y="348" textAnchor="middle" fontSize="9" fill="var(--text-muted)">16 features per bar</text>
        <line x1="530" y1="356" x2="530" y2="364" className="tm-flow" stroke="#1D9E75" strokeWidth="1.5" markerEnd="url(#tm-arrow)" />

        <rect x="400" y="366" width="260" height="40" rx="9" fill="var(--bg)" stroke="var(--border-strong)" strokeWidth="1" />
        <text x="530" y="384" textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--text-primary)">9 online + LSTM = 10 models</text>
        <text x="530" y="398" textAnchor="middle" fontSize="9" fill="var(--text-muted)">River online-learners · Deep LSTM</text>
        <line x1="530" y1="406" x2="530" y2="414" className="tm-flow" stroke="#1D9E75" strokeWidth="1.5" markerEnd="url(#tm-arrow)" />

        <rect x="400" y="416" width="260" height="42" rx="9" fill="var(--bg)" stroke="var(--border-strong)" strokeWidth="1" />
        <text x="530" y="435" textAnchor="middle" fontSize="10.5" fontWeight="600" fill="var(--text-primary)">predict → trade → learn</text>
        <text x="530" y="449" textAnchor="middle" fontSize="9" fill="#1D9E75">↻ continuous loop</text>

        {/* Both pipelines → TimescaleDB + MLflow (converge) */}
        <line x1="190" y1="470" x2="300" y2="504" className="tm-flow" stroke="#7F77DD" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <line x1="530" y1="470" x2="420" y2="504" className="tm-flow" stroke="#1D9E75" strokeWidth="2" markerEnd="url(#tm-arrow)" />

        {/* TimescaleDB + MLflow */}
        <rect x="210" y="506" width="300" height="54" rx="11"
              fill="var(--surface-2)" stroke="#5271ff" strokeWidth="1.5" />
        <text x="360" y="528" textAnchor="middle" fontSize="12.5" fontWeight="600" fill="var(--text-primary)">TimescaleDB + MLflow</text>
        <text x="360" y="546" textAnchor="middle" fontSize="9.5" fill="var(--text-muted)">bars · weights · levels — per timeframe</text>

        {/* DB → Dashboard */}
        <line x1="360" y1="560" x2="360" y2="586" className="tm-flow" stroke="#5271ff" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <circle className="tm-bar" cx="360" cy="562" r="3" fill="#5271ff" style={{ ['--tm-dist']: '22px' }} />
        <circle className="tm-bar" cx="360" cy="562" r="3" fill="#5271ff" style={{ ['--tm-dist']: '22px', animationDelay: '1.2s' }} />

        {/* React dashboard (output — glow) */}
        <rect className="tm-glow" x="210" y="588" width="300" height="54" rx="11"
              fill="none" stroke="#2dd4bf" strokeWidth="3" filter="url(#tm-soft)" />
        <rect x="210" y="588" width="300" height="54" rx="11"
              fill="var(--surface-2)" stroke="#2dd4bf" strokeWidth="1.5" />
        <text x="360" y="610" textAnchor="middle" fontSize="12.5" fontWeight="600" fill="var(--text-primary)">React dashboard · WebSocket</text>
        <text x="360" y="628" textAnchor="middle" fontSize="9.5" fill="var(--text-muted)">19 models · combined leaderboard</text>
      </svg>
    </div>
  )
}
