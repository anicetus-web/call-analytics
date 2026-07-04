import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../api'
import { LogoMark } from '../components/icons'
import styles from './LoginPage.module.css'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(username, password)
      navigate('/projects')
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Неверный логин или пароль')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.root}>
      <form className={styles.card} onSubmit={handleSubmit}>
        <div className={styles.logo}><LogoMark size={26} /></div>
        <h1 className={styles.title}>Call Analytics</h1>
        <p className={styles.subtitle}>Вход в систему</p>

        {error && <div className={styles.error} role="alert">{error}</div>}

        <label className={styles.label}>
          Логин
          <input
            className={styles.input}
            type="text"
            name="username"
            autoComplete="username"
            value={username}
            onChange={e => setUsername(e.target.value)}
            required
            autoFocus
          />
        </label>

        <label className={styles.label}>
          Пароль
          <input
            className={styles.input}
            type="password"
            name="password"
            autoComplete="current-password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
          />
        </label>

        <button className={styles.btn} type="submit" disabled={loading}>
          {loading ? 'Вход…' : 'Войти'}
        </button>
      </form>
    </div>
  )
}
