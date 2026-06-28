export default function GoogleLoginButton() {
  return (
    <button
      onClick={() => { window.location.href = '/auth/google' }}
      style={{
        width: 280,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        padding: '11px 20px',
        background: '#ffffff',
        color: '#202124',
        border: '1px solid #dadce0',
        borderRadius: 8,
        fontSize: 14,
        fontWeight: 500,
        cursor: 'pointer',
        transition: 'box-shadow 0.15s',
      }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = '0 1px 4px rgba(0,0,0,0.25)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}
    >
      {/* Google "G" */}
      <span style={{
        width: 20, height: 20,
        borderRadius: '50%',
        background: 'linear-gradient(135deg, #4285F4 0%, #34A853 33%, #FBBC05 66%, #EA4335 100%)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, fontWeight: 700, color: '#fff', flexShrink: 0,
      }}>
        G
      </span>
      Sign in with Google
    </button>
  )
}
