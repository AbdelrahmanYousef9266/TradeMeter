import GoogleLoginButton from '../components/auth/GoogleLoginButton'

export default function Login() {
  return (
    <div style={{
      height: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '0',
    }}>
      {/* Logo mark */}
      <div style={{
        width: 48, height: 48,
        background: 'var(--accent)',
        borderRadius: 12,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 22, fontWeight: 500, color: '#fff',
        marginBottom: 20,
      }}>
        T
      </div>

      <h1 style={{ fontSize: 26, fontWeight: 500, color: 'var(--text-primary)', marginBottom: 8 }}>
        TradeMeter
      </h1>

      <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 40, textAlign: 'center' }}>
        Live ML trading dashboard for NinjaTrader 8
      </p>

      <GoogleLoginButton />

      <p style={{ marginTop: 20, fontSize: 12, color: 'var(--text-tertiary)', textAlign: 'center' }}>
        Connect your NinjaTrader account after signing in
      </p>
    </div>
  )
}
