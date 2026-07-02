/**
 * Animated architecture diagram — TradeMeter data flow + learning loop.
 *
 * Self-contained: inline SVG + scoped CSS animations. Uses the app's CSS
 * variables so it adapts to the theme. The SVG markup is kept visually
 * identical to the standalone version at /architecture.html (only attribute
 * casing differs — JSX requires camelCase).
 *
 * Animations use only stroke-dashoffset, opacity and transform (GPU-friendly)
 * and are gated behind prefers-reduced-motion so a static frame is shown when
 * the viewer opts out.
 */
export default function ArchitectureDiagram({ compact = false }) {
  return (
    <div style={{
      width: '100%',
      maxWidth: compact ? '100%' : '680px',
      height: compact ? '100%' : 'auto',
      margin: '0 auto',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
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

      <svg viewBox="0 0 680 700" width="100%" role="img"
           preserveAspectRatio="xMidYMid meet"
           style={{ display: 'block', maxWidth: '100%', maxHeight: '100%', height: compact ? '100%' : 'auto' }}
           aria-label="TradeMeter architecture: live bars flow from NinjaTrader through Redis, TimescaleDB and the feature engine into 11 ML models that predict, trade, learn and feed the dashboard.">
        <defs>
          <marker id="tm-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="context-stroke" />
          </marker>
        </defs>

        {/* ══════════════ DATA FLOW ══════════════ */}

        {/* NinjaTrader */}
        <rect x="220" y="24" width="240" height="52" rx="11"
              fill="var(--surface-2)" stroke="var(--border)" strokeWidth="1" />
        <text x="340" y="46" textAnchor="middle" fontSize="13" fontWeight="600" fill="var(--text-primary)">NinjaTrader 8</text>
        <text x="340" y="63" textAnchor="middle" fontSize="10" fill="var(--text-muted)">Live 1-min bars</text>

        {/* NT → Redis */}
        <line x1="340" y1="76" x2="340" y2="112" className="tm-flow" stroke="#5271ff" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <text x="352" y="98" fontSize="9" fill="var(--text-muted)">TCP :5000</text>
        <circle className="tm-bar" cx="340" cy="78" r="3" fill="#5271ff" style={{ ['--tm-dist']: '32px' }} />
        <circle className="tm-bar" cx="340" cy="78" r="3" fill="#5271ff" style={{ ['--tm-dist']: '32px', animationDelay: '1.2s' }} />

        {/* Redis */}
        <rect x="220" y="112" width="240" height="52" rx="11"
              fill="var(--surface-2)" stroke="var(--border)" strokeWidth="1" />
        <text x="340" y="134" textAnchor="middle" fontSize="13" fontWeight="600" fill="var(--text-primary)">Redis Streams</text>
        <text x="340" y="151" textAnchor="middle" fontSize="10" fill="var(--text-muted)">Token auth · crash-safe buffer</text>

        {/* Redis → TimescaleDB / Feature Engine (split) */}
        <line x1="330" y1="166" x2="200" y2="198" className="tm-flow" stroke="#5271ff" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <line x1="350" y1="166" x2="480" y2="198" className="tm-flow" stroke="#7F77DD" strokeWidth="2" markerEnd="url(#tm-arrow)" />

        {/* TimescaleDB */}
        <rect x="70" y="200" width="250" height="56" rx="11"
              fill="var(--surface-2)" stroke="var(--border)" strokeWidth="1" />
        <text x="195" y="224" textAnchor="middle" fontSize="13" fontWeight="600" fill="var(--text-primary)">TimescaleDB</text>
        <text x="195" y="241" textAnchor="middle" fontSize="10" fill="var(--text-muted)">Stores every bar</text>

        {/* Feature Engine */}
        <rect x="360" y="200" width="250" height="56" rx="11"
              fill="var(--surface-2)" stroke="var(--border)" strokeWidth="1" />
        <text x="485" y="224" textAnchor="middle" fontSize="13" fontWeight="600" fill="var(--text-primary)">Feature Engine</text>
        <text x="485" y="241" textAnchor="middle" fontSize="10" fill="var(--text-muted)">16 features per bar</text>

        {/* → Models (merge) */}
        <line x1="195" y1="256" x2="330" y2="290" className="tm-flow" stroke="#5271ff" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <line x1="485" y1="256" x2="350" y2="290" className="tm-flow" stroke="#7F77DD" strokeWidth="2" markerEnd="url(#tm-arrow)" />

        {/* 11 ML models */}
        <rect x="60" y="292" width="560" height="104" rx="12"
              fill="var(--surface-2)" stroke="var(--border)" strokeWidth="1" />
        <text x="340" y="312" textAnchor="middle" fontSize="13" fontWeight="600" fill="var(--text-primary)">11 ML Models — predict in parallel</text>
        <text x="340" y="327" textAnchor="middle" fontSize="10" fill="var(--text-muted)">8 River online-learners · You · Brother · Deep LSTM</text>

        {/* Row 1 chips */}
        <ModelChip x={86}  label="Scalper" />
        <ModelChip x={172} label="Momentum" />
        <ModelChip x={258} label="Mean Rev" />
        <ModelChip x={344} label="Breakout" />
        <ModelChip x={430} label="Conserv." />
        <ModelChip x={516} label="Aggress." />
        {/* Row 2 chips */}
        <ModelChip x={129} y={364} label="Volume" />
        <ModelChip x={215} y={364} label="Contrar." />
        <ModelChip x={301} y={364} label="You" />
        <ModelChip x={387} y={364} label="Brother" />
        <ModelChip x={473} y={364} label="LSTM" />

        {/* Models → Loop */}
        <line x1="340" y1="396" x2="340" y2="424" className="tm-flow" stroke="#5271ff" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <circle className="tm-bar" cx="340" cy="398" r="3" fill="#5271ff" style={{ ['--tm-dist']: '24px' }} />

        {/* ══════════════ LEARNING LOOP ══════════════ */}

        {/* Container + glow overlay */}
        <rect x="95" y="424" width="490" height="176" rx="14"
              fill="var(--surface-2)" stroke="var(--border)" strokeWidth="1" />
        <rect className="tm-glow" x="95" y="424" width="490" height="176" rx="14"
              fill="none" stroke="#2dd4bf" strokeWidth="1.5" strokeDasharray="4 6" />
        <text x="340" y="444" textAnchor="middle" fontSize="10" fontWeight="600"
              letterSpacing="1.5" fill="#2dd4bf">LEARNING LOOP</text>

        {/* Predict */}
        <rect x="135" y="452" width="170" height="48" rx="10"
              fill="var(--bg)" stroke="var(--border-strong)" strokeWidth="1" />
        <text x="220" y="472" textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--text-primary)">Predict</text>
        <text x="220" y="488" textAnchor="middle" fontSize="9" fill="var(--text-muted)">BUY · SELL · HOLD</text>

        {/* Open trade */}
        <rect x="375" y="452" width="170" height="48" rx="10"
              fill="var(--bg)" stroke="var(--border-strong)" strokeWidth="1" />
        <text x="460" y="472" textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--text-primary)">Open trade</text>
        <text x="460" y="488" textAnchor="middle" fontSize="9" fill="var(--text-muted)">ATR stop &amp; target</text>

        {/* Outcome */}
        <rect x="375" y="524" width="170" height="48" rx="10"
              fill="var(--bg)" stroke="var(--border-strong)" strokeWidth="1" />
        <text x="460" y="544" textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--text-primary)">Outcome</text>
        <text x="460" y="560" textAnchor="middle" fontSize="9" fill="var(--text-muted)">Real P&amp;L · win / loss</text>

        {/* Learn */}
        <rect x="135" y="524" width="170" height="48" rx="10"
              fill="var(--bg)" stroke="var(--border-strong)" strokeWidth="1" />
        <text x="220" y="544" textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--text-primary)">Learn</text>
        <text x="220" y="560" textAnchor="middle" fontSize="9" fill="var(--text-muted)">.learn_one → weights</text>

        {/* Loop arrows (clockwise) */}
        <line x1="307" y1="470" x2="373" y2="470" className="tm-loop" stroke="#2dd4bf" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <line x1="460" y1="502" x2="460" y2="522" className="tm-loop" stroke="#fbbf24" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <line x1="373" y1="554" x2="307" y2="554" className="tm-loop" stroke="#E24B4A" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <line x1="220" y1="522" x2="220" y2="502" className="tm-loop" stroke="#7F77DD" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <text x="150" y="514" fontSize="9" fill="#7F77DD">↺ improve</text>

        {/* Loop → Dashboard */}
        <line x1="340" y1="600" x2="340" y2="628" className="tm-flow" stroke="#5271ff" strokeWidth="2" markerEnd="url(#tm-arrow)" />
        <circle className="tm-bar" cx="340" cy="602" r="3" fill="#5271ff" style={{ ['--tm-dist']: '24px' }} />

        {/* Dashboard */}
        <rect x="200" y="628" width="280" height="54" rx="11"
              fill="var(--surface-2)" stroke="var(--border)" strokeWidth="1" />
        <text x="340" y="651" textAnchor="middle" fontSize="13" fontWeight="600" fill="var(--text-primary)">Dashboard</text>
        <text x="340" y="668" textAnchor="middle" fontSize="10" fill="var(--text-muted)">WebSocket · signals · P&amp;L · levels</text>
      </svg>
    </div>
  )
}

// Small rounded model chip inside the "11 models" container.
function ModelChip({ x, y = 340, label }) {
  return (
    <g>
      <rect x={x} y={y} width="78" height="18" rx="5"
            fill="var(--bg)" stroke="var(--border-strong)" strokeWidth="0.75" />
      <text x={x + 39} y={y + 13} textAnchor="middle" fontSize="9" fill="var(--text-primary)">{label}</text>
    </g>
  )
}
