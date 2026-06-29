import { useEffect, useRef } from 'react'
import useStore from '../store'

const MOCK = import.meta.env.VITE_MOCK_WS === 'true'
const MODEL_NAMES = [
  'scalper', 'momentum', 'mean_reversion', 'breakout',
  'conservative', 'aggressive', 'volume', 'contrarian', 'personal',
]
const SIGNALS = ['BUY', 'SELL', 'HOLD']

function mockBar(price) {
  const open  = price
  const close = price + (Math.random() - 0.48) * 4
  const high  = Math.max(open, close) + Math.random() * 2
  const low   = Math.min(open, close) - Math.random() * 2
  const volume = Math.floor(800 + Math.random() * 400)
  const rsi    = 40 + Math.random() * 30
  const ema9   = price - 2 + Math.random() * 4
  const ema21  = price - 5 + Math.random() * 3
  const ema50  = price - 8 + Math.random() * 3
  const models = {}
  const levels = {}
  for (const name of MODEL_NAMES) {
    const sig  = SIGNALS[Math.floor(Math.random() * 3)]
    const conf = 0.50 + Math.random() * 0.45
    const up   = sig === 'BUY' ? conf : sig === 'SELL' ? 1 - conf : 0.5
    models[name] = {
      signal: sig, confidence: conf,
      direction_up: up, direction_down: 1 - up,
      predicted_high: close + 4, predicted_low: close - 4,
    }
    levels[name] = {
      level: 5 + Math.floor(Math.random() * 20),
      xp: Math.floor(Math.random() * 300),
      streak: Math.floor(Math.random() * 8),
      rank: 'Rookie',
      xp_progress_pct: Math.random(),
      unlocked_settings: ['Base settings'],
    }
  }
  return {
    type: 'bar',
    time: new Date().toISOString(),
    bar:  { open, high, low, close, volume },
    features: { rsi_14: rsi, ema_9: ema9, ema_21: ema21, ema_50: ema50, macd: 1.2, macd_signal: 0.8, atr_14: 3, volume_delta: 0.1, bar_range: high - low, close_position: (close - low) / (high - low || 1) },
    models,
    levels,
  }
}

function startMock({ setBar, updateModelSignal, updateModelLevel, pushLevelUp, setNtConnected, setWarmup }) {
  let price = 5840
  setNtConnected(true)
  setWarmup({ isWarmingUp: false, ntConnected: true })

  const barInterval = setInterval(() => {
    price += (Math.random() - 0.48) * 2
    const msg = mockBar(price)
    setBar({ ...msg.bar, time: msg.time, features: msg.features })
    Object.entries(msg.models).forEach(([n, s]) => updateModelSignal(n, s))
    Object.entries(msg.levels).forEach(([n, l]) => updateModelLevel(n, l))
  }, 2000)

  const lueInterval = setInterval(() => {
    const name = MODEL_NAMES[Math.floor(Math.random() * MODEL_NAMES.length)]
    pushLevelUp({ type: 'level_up', model_name: name, new_level: Math.floor(Math.random() * 50) + 5, new_rank: 'Apprentice', unlocked: null })
  }, 30000)

  return () => { clearInterval(barInterval); clearInterval(lueInterval) }
}

export function useWebSocket() {
  const ws = useRef(null)
  const reconnectDelay = useRef(1000)
  const { setBar, setCurrentBar, updateModelSignal, updateModelLevel, pushLevelUp, setNtConnected, setWarmup } = useStore()

  useEffect(() => {
    if (MOCK) return startMock({ setBar, updateModelSignal, updateModelLevel, pushLevelUp, setNtConnected, setWarmup })

    function connect() {
      const url = (import.meta.env.VITE_WS_URL || 'ws://localhost:8000') + '/market/live'
      ws.current = new WebSocket(url)

      ws.current.onopen = () => {
        reconnectDelay.current = 1000
        setNtConnected(true)
      }

      ws.current.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          console.log('[WS] message:', msg.type, `(${Object.keys(msg).length})`, Object.keys(msg))

          if (msg.type === 'tick') {
            // Real-time price update (inter-bar tick or warmup bar close).
            // Updates the live price display only — does NOT create a new chart candle.
            setCurrentBar({ time: msg.time, ...msg.bar })
            // Warmup progress is embedded in tick messages during the 50-bar warmup period
            if (msg.warmup?.warming_up) {
              setWarmup({
                barsReceived: msg.warmup.bars_received,
                barsNeeded:   msg.warmup.bars_needed,
                isWarmingUp:  true,
                ntConnected:  true,
              })
            }
          }

          if (msg.type === 'bar') {
            // Bar close with ML predictions — append new candle + update model cards
            setBar({ ...msg.bar, time: msg.time, features: msg.features })
            setWarmup({ isWarmingUp: false, ntConnected: true })
            if (msg.models) {
              Object.entries(msg.models).forEach(([name, signal]) => updateModelSignal(name, signal))
            }
            if (msg.levels) {
              Object.entries(msg.levels).forEach(([name, level]) => updateModelLevel(name, level))
            }
          }

          if (msg.type === 'level_up') pushLevelUp(msg)
        } catch (err) {
          console.error('[WS] parse error:', err)
        }
      }

      ws.current.onclose = () => {
        setNtConnected(false)
        setTimeout(connect, Math.min(reconnectDelay.current, 30000))
        reconnectDelay.current = Math.min(reconnectDelay.current * 2, 30000)
      }

      ws.current.onerror = () => ws.current?.close()
    }

    connect()
    return () => ws.current?.close()
  }, [])
}
