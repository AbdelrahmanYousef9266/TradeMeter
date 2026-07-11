/**
 * Animated system-design diagram — TradeMeter deployment topology (STREAM-SAFE).
 *
 * Broadcast publicly on the AFK stream, so this is deliberately operational-recon
 * free: NO port numbers, NO specific auth scheme names (OAuth/JWT/cookie), NO
 * IP/host details. It shows structure and service names only — "what was built",
 * nothing an attacker could use. Data-feed and API auth are labelled generically
 * ("secure data feed", "authenticated").
 *
 * Three layers: Client machine → Backend (FastAPI) → Docker containers.
 * Matches ArchitectureDiagram's aesthetic (inline themed SVG, animated dashed
 * connectors, glow nodes, prefers-reduced-motion fallback, compact mode). SVG
 * element ids are prefixed `sd-` so both diagrams can render on the same page
 * without id collisions. Kept in sync with /system-design.html.
 */
export default function SystemDesignDiagram({ compact = false }) {
  return (
    <div style={{
      width: '100%',
      maxWidth: compact ? '100%' : '680px',
      height: compact ? '100%' : 'auto',
      margin: compact ? '0 0 0 auto' : '0 auto',
      display: 'flex', alignItems: 'center', justifyContent: compact ? 'flex-end' : 'center',
    }}>
      <style>{`
        @keyframes tm-dash { to { stroke-dashoffset: -16; } }
        @keyframes tm-glow { 0%,100%{opacity:.18} 50%{opacity:.55} }
        @keyframes tm-travel {
          0%   { opacity:0; transform: translateY(0); }
          12%  { opacity:1; }
          88%  { opacity:1; }
          100% { opacity:0; transform: translateY(var(--tm-dist, 30px)); }
        }
        @media (prefers-reduced-motion: no-preference) {
          .sd-flow { stroke-dasharray:6 6; animation: tm-dash 1.2s linear infinite; }
          .sd-glow { animation: tm-glow 2.6s ease-in-out infinite; }
          .sd-bar  { animation: tm-travel 2.4s linear infinite; }
        }
      `}</style>

      <svg viewBox="0 0 680 620" width="100%" role="img"
           preserveAspectRatio={compact ? 'xMaxYMid meet' : 'xMidYMid meet'}
           style={{ display: 'block', maxWidth: '100%', maxHeight: '100%', height: compact ? '100%' : 'auto' }}
           aria-label="TradeMeter system design across three layers: a client machine running the NinjaTrader strategy and the React dashboard; a FastAPI backend with a secure data-feed listener, a per-timeframe ingestion consumer, and an authenticated REST plus WebSocket API; and Docker containers for a Redis stream queue, a TimescaleDB store of bars and model state, and MLflow model snapshots.">
        <defs>
          <marker id="sd-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="context-stroke" />
          </marker>
          <filter id="sd-soft" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="5" />
          </filter>
        </defs>

        {/* ══════════════ LAYER 1 — Client machine ══════════════ */}
        <rect x="40" y="28" width="600" height="104" rx="14"
              fill="none" stroke="var(--border)" strokeWidth="1" strokeDasharray="4 6" />
        <text x="340" y="47" textAnchor="middle" fontSize="10" fontWeight="700" letterSpacing="1.2" fill="var(--text-muted)">CLIENT MACHINE</text>

        <rect x="90" y="56" width="170" height="64" rx="10" fill="var(--surface-2)" stroke="#5271ff" strokeWidth="1.5" />
        <text x="175" y="84" textAnchor="middle" fontSize="11.5" fontWeight="600" fill="var(--text-primary)">NinjaTrader 8</text>
        <text x="175" y="100" textAnchor="middle" fontSize="9" fill="var(--text-muted)">strategy</text>

        <rect x="460" y="56" width="170" height="64" rx="10" fill="var(--surface-2)" stroke="#2dd4bf" strokeWidth="1.5" />
        <text x="545" y="84" textAnchor="middle" fontSize="11.5" fontWeight="600" fill="var(--text-primary)">Browser</text>
        <text x="545" y="100" textAnchor="middle" fontSize="9" fill="var(--text-muted)">React dashboard</text>

        {/* Client → Backend */}
        <line x1="175" y1="120" x2="175" y2="198" className="sd-flow" stroke="#5271ff" strokeWidth="2" markerEnd="url(#sd-arrow)" />
        <text x="183" y="163" fontSize="8.5" fill="var(--text-muted)">data feed</text>
        <circle className="sd-bar" cx="175" cy="122" r="3" fill="#5271ff" style={{ ['--tm-dist']: '74px' }} />
        <circle className="sd-bar" cx="175" cy="122" r="3" fill="#5271ff" style={{ ['--tm-dist']: '74px', animationDelay: '1.2s' }} />

        <line x1="545" y1="120" x2="545" y2="198" className="sd-flow" stroke="#2dd4bf" strokeWidth="2" markerStart="url(#sd-arrow)" markerEnd="url(#sd-arrow)" />
        <text x="553" y="163" fontSize="8.5" fill="var(--text-muted)">authenticated</text>

        {/* ══════════════ LAYER 2 — Backend · FastAPI ══════════════ */}
        <rect x="40" y="168" width="600" height="150" rx="14"
              fill="none" stroke="var(--border)" strokeWidth="1" strokeDasharray="4 6" />
        <text x="340" y="187" textAnchor="middle" fontSize="10" fontWeight="700" letterSpacing="1.2" fill="var(--text-muted)">BACKEND · FastAPI</text>

        <rect x="90" y="198" width="170" height="74" rx="10" fill="var(--surface-2)" stroke="#5271ff" strokeWidth="1.5" />
        <text x="175" y="228" textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--text-primary)">TCP listener</text>
        <text x="175" y="244" textAnchor="middle" fontSize="9" fill="var(--text-muted)">secure data feed</text>

        {/* Ingestion consumer — the hub (glow) */}
        <rect className="sd-glow" x="275" y="198" width="170" height="74" rx="10"
              fill="none" stroke="#5271ff" strokeWidth="3" filter="url(#sd-soft)" />
        <rect x="275" y="198" width="170" height="74" rx="10" fill="var(--surface-2)" stroke="#5271ff" strokeWidth="1.5" />
        <text x="360" y="226" textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--text-primary)">Ingestion consumer</text>
        <text x="360" y="244" textAnchor="middle" fontSize="9" fill="var(--text-muted)">per-timeframe pipelines</text>

        <rect x="460" y="198" width="170" height="74" rx="10" fill="var(--surface-2)" stroke="#2dd4bf" strokeWidth="1.5" />
        <text x="545" y="224" textAnchor="middle" fontSize="10.5" fontWeight="600" fill="var(--text-primary)">REST + WebSocket</text>
        <text x="545" y="240" textAnchor="middle" fontSize="8.5" fill="var(--text-muted)">authenticated · live push</text>

        {/* TCP listener → Ingestion consumer */}
        <line x1="260" y1="235" x2="273" y2="235" className="sd-flow" stroke="#5271ff" strokeWidth="2" markerEnd="url(#sd-arrow)" />

        {/* Backend → Docker */}
        <line x1="330" y1="272" x2="210" y2="458" className="sd-flow" stroke="#E0912F" strokeWidth="2" markerStart="url(#sd-arrow)" markerEnd="url(#sd-arrow)" />
        <text x="236" y="372" fontSize="8.5" fill="#E0912F">queue</text>

        <line x1="360" y1="272" x2="360" y2="458" className="sd-flow" stroke="#5271ff" strokeWidth="2" markerEnd="url(#sd-arrow)" />
        <text x="368" y="372" fontSize="8.5" fill="var(--text-muted)">store</text>
        <circle className="sd-bar" cx="360" cy="274" r="3" fill="#5271ff" style={{ ['--tm-dist']: '182px' }} />

        <line x1="395" y1="272" x2="515" y2="458" className="sd-flow" stroke="#7F77DD" strokeWidth="2" markerEnd="url(#sd-arrow)" />
        <text x="452" y="372" fontSize="8.5" fill="#7F77DD">snapshots</text>

        {/* ══════════════ LAYER 3 — Docker containers ══════════════ */}
        <rect x="40" y="430" width="600" height="160" rx="14"
              fill="none" stroke="var(--border)" strokeWidth="1" />
        <rect className="sd-glow" x="40" y="430" width="600" height="160" rx="14"
              fill="none" stroke="#2496ED" strokeWidth="1.2" strokeDasharray="4 6" />
        <text x="340" y="450" textAnchor="middle" fontSize="10" fontWeight="700" letterSpacing="1.2" fill="#2496ED">DOCKER CONTAINERS</text>

        <rect x="90" y="460" width="170" height="98" rx="10" fill="var(--surface-2)" stroke="#E0912F" strokeWidth="1.5" />
        <text x="175" y="500" textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--text-primary)">Redis</text>
        <text x="175" y="517" textAnchor="middle" fontSize="9" fill="var(--text-muted)">stream queue</text>

        <rect x="275" y="460" width="170" height="98" rx="10" fill="var(--surface-2)" stroke="#5271ff" strokeWidth="1.5" />
        <text x="360" y="500" textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--text-primary)">TimescaleDB</text>
        <text x="360" y="517" textAnchor="middle" fontSize="9" fill="var(--text-muted)">bars &amp; model state</text>

        <rect x="460" y="460" width="170" height="98" rx="10" fill="var(--surface-2)" stroke="#7F77DD" strokeWidth="1.5" />
        <text x="545" y="500" textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--text-primary)">MLflow</text>
        <text x="545" y="517" textAnchor="middle" fontSize="9" fill="var(--text-muted)">model snapshots</text>
      </svg>
    </div>
  )
}
