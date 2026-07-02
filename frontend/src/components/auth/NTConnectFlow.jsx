import { useState } from 'react'

const STEPS = [
  'Open NinjaTrader 8',
  'Go to Strategies → Add Strategy → LiveDataFeedStrategy',
  'Paste your token into the ConnectionToken parameter',
  'Enable the strategy on your chart',
  'Set TradeMeterHost to 127.0.0.1 and TradeMeterPort to 5000',
]

export default function NTConnectFlow({ tokenData, connected, resetting, onReset, onContinue }) {
  const [copied, setCopied] = useState(false)

  // tokenData: { token, prefix, connected, first_issue }
  // The full plaintext token is present ONLY in the response that issued it
  // (first_issue). On every later load only the masked prefix is available.
  const freshToken    = tokenData?.token || null      // full token, shown once
  const displayPrefix = tokenData?.prefix || 'TM-••••' // masked fallback

  const handleCopy = () => {
    if (!freshToken) return
    navigator.clipboard.writeText(freshToken).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const handleReset = () => {
    if (resetting) return
    const ok = window.confirm(
      'Reset your connection token?\n\n' +
      'This immediately invalidates your current token. If NinjaTrader is ' +
      'already running, you will need to paste the new token into the ' +
      'ConnectionToken parameter and restart the strategy.'
    )
    if (ok) onReset?.()
  }

  const card = {
    background: 'var(--surface-2)',
    border: '0.5px solid var(--border)',
    borderRadius: 12,
    padding: '20px 24px',
    width: '100%',
    maxWidth: 480,
  }

  if (connected) {
    return (
      <div style={{ ...card, textAlign: 'center' }}>
        <div style={{
          width: 48, height: 48, borderRadius: '50%',
          background: 'var(--bg-success)', border: '2px solid var(--text-success)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 22, margin: '0 auto 16px',
        }}>
          ✓
        </div>
        <p style={{ fontWeight: 500, fontSize: 15, marginBottom: 6 }}>NinjaTrader Connected</p>
        <p style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 24 }}>
          Live data is streaming successfully.
        </p>
        <button
          onClick={onContinue}
          style={{
            width: '100%', padding: '10px', borderRadius: 8,
            background: 'var(--accent)', color: '#fff', fontWeight: 500, border: 'none',
          }}
        >
          Continue to Dashboard
        </button>
      </div>
    )
  }

  return (
    <div style={{ ...card }}>
      {/* Token display */}
      <p style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        Your Connection Token
      </p>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8,
        background: 'var(--surface-3)', borderRadius: 8, padding: '10px 14px',
        border: '1px solid var(--border)',
      }}>
        <code style={{
          flex: 1, fontFamily: 'monospace', fontSize: 16,
          letterSpacing: '0.12em', color: 'var(--text-primary)',
        }}>
          {freshToken || displayPrefix}
        </code>
        {freshToken ? (
          <button
            onClick={handleCopy}
            style={{
              padding: '4px 10px', borderRadius: 6,
              border: '1px solid var(--border)',
              color: copied ? 'var(--text-success)' : 'var(--text-secondary)',
              background: copied ? 'var(--bg-success)' : 'transparent',
              fontSize: 12,
            }}
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        ) : (
          <button
            onClick={handleReset}
            disabled={resetting}
            style={{
              padding: '4px 10px', borderRadius: 6,
              border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
              background: 'transparent', fontSize: 12,
              cursor: resetting ? 'not-allowed' : 'pointer',
            }}
          >
            {resetting ? 'Resetting…' : 'Reset token'}
          </button>
        )}
      </div>

      {/* Fresh-token warning — the ONLY time the full token is visible */}
      {freshToken && (
        <div style={{
          marginBottom: 16, padding: '8px 12px', borderRadius: 8,
          background: 'var(--bg-warning)', border: '1px solid rgba(251,191,36,0.3)',
        }}>
          <p style={{ fontSize: 12, color: 'var(--text-warning)', margin: 0 }}>
            Copy this now — you won't be able to see it again. If you lose it,
            use “Reset token” to generate a new one.
          </p>
        </div>
      )}

      {/* Masked state — token already issued, offer a rotate */}
      {!freshToken && (
        <p style={{ fontSize: 12, color: 'var(--text-tertiary)', marginBottom: 16 }}>
          Your token is hidden for security and can’t be shown again. Lost it?
          Use “Reset token” to issue a fresh one (it’ll display once).
        </p>
      )}

      {/* Connection status */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20,
        padding: '8px 12px', borderRadius: 8,
        background: 'var(--surface-3)', border: '1px solid var(--border)',
      }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: 'var(--text-danger)',
          animation: 'pulse-dot 1.6s ease-in-out infinite',
          display: 'inline-block', flexShrink: 0,
        }} />
        <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          Waiting for NinjaTrader to connect…
        </span>
      </div>

      {/* Steps */}
      <p style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        Setup Steps
      </p>
      <ol style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {STEPS.map((step, i) => (
          <li key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
            <span style={{
              width: 20, height: 20, borderRadius: '50%', flexShrink: 0,
              background: 'var(--surface-3)', border: '1px solid var(--border)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 11, color: 'var(--text-secondary)',
            }}>
              {i + 1}
            </span>
            <span style={{ fontSize: 13, color: 'var(--text-primary)', paddingTop: 2 }}>
              {step}
            </span>
          </li>
        ))}
      </ol>

      {/* Continue button (disabled until connected) */}
      <button
        disabled
        style={{
          marginTop: 24, width: '100%', padding: '10px', borderRadius: 8,
          background: 'var(--surface-3)', color: 'var(--text-tertiary)',
          border: '1px solid var(--border)', cursor: 'not-allowed',
        }}
      >
        Continue to Dashboard
      </button>
    </div>
  )
}
