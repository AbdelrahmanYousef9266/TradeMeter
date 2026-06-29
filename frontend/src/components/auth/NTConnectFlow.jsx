import { useState } from 'react'

const STEPS = [
  'Open NinjaTrader 8',
  'Go to Strategies → Add Strategy → LiveDataFeedStrategy',
  'Paste your token into the ConnectionToken parameter',
  'Enable the strategy on your chart',
  'Set TradeMeterHost to 127.0.0.1 and TradeMeterPort to 5000',
]

export default function NTConnectFlow({ tokenData, connected, onContinue }) {
  const [copied, setCopied] = useState(false)

  // tokenData: { token, prefix, connected, first_issue }
  const displayToken  = tokenData?.first_issue ? tokenData.token  : null
  const displayPrefix = tokenData?.prefix || ''

  const handleCopy = () => {
    const text = displayToken || displayPrefix
    if (!text) return
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
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
          {displayToken ? displayToken : displayPrefix ? `${displayPrefix}···` : '···'}
        </code>
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
      </div>

      {/* First-issue warning */}
      {tokenData?.first_issue && (
        <div style={{
          marginBottom: 16, padding: '8px 12px', borderRadius: 8,
          background: 'var(--bg-warning)', border: '1px solid rgba(251,191,36,0.3)',
        }}>
          <p style={{ fontSize: 12, color: 'var(--text-warning)', margin: 0 }}>
            This token is shown once only. Save it somewhere safe.
          </p>
        </div>
      )}

      {/* Repeat-issue note */}
      {!tokenData?.first_issue && displayPrefix && (
        <p style={{ fontSize: 12, color: 'var(--text-tertiary)', marginBottom: 16 }}>
          Token already issued. Contact support to reset.
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
