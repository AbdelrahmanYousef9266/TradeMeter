import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import GoogleLoginButton from '../components/auth/GoogleLoginButton'
import api from '../services/api'

export default function Login() {
  const navigate = useNavigate()

  useEffect(() => {
    // Reset the post-login landing one-shot so the next successful sign-in
    // re-evaluates whether to show the Connect choice screen (NT off) or go
    // straight to the dashboard (NT on).
    sessionStorage.removeItem('tm_login_landing')

    // If already authenticated, skip the login page
    api.get('/auth/me')
      .then(() => navigate('/dashboard', { replace: true }))
      .catch(() => {}) // not logged in — stay here, do nothing
  }, [])

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

      <p style={{ marginTop: 12, fontSize: 11, color: 'var(--text-tertiary)', textAlign: 'center', maxWidth: 320 }}>
        Your data is private and isolated to your account.
      </p>
    </div>
  )
}
