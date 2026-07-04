import { useEffect, useState, FormEvent } from 'react'
import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { logout, getMe, updateMe, CurrentUser } from '../api'
import { LogoMark, IconFolder, IconUsers, IconPhoneWave, IconChart, IconLogout } from './icons'
import Avatar from './Avatar'
import Modal from './Modal'
import styles from './Layout.module.css'
import formStyles from './Form.module.css'

export default function Layout() {
  const [me, setMe] = useState<CurrentUser | null>(null)
  const [editingProfile, setEditingProfile] = useState(false)
  const location = useLocation()

  useEffect(() => {
    getMe().then(setMe).catch(() => {})
  }, [])

  return (
    <div className={styles.root}>
      <aside className={styles.sidebar}>
        <div className={styles.logo}>
          <span className={styles.logoIcon}><LogoMark size={20} /></span>
          Call Analytics
        </div>
        <nav className={styles.nav}>
          <NavLink to="/projects" className={({ isActive }) => isActive ? styles.active : ''}>
            <IconFolder size={18} /> Проекты
          </NavLink>
          <NavLink to="/analytics" className={({ isActive }) => isActive ? styles.active : ''}>
            <IconChart size={18} /> Аналитика
          </NavLink>
          <NavLink to="/managers" className={({ isActive }) => isActive ? styles.active : ''}>
            <IconUsers size={18} /> Менеджеры
          </NavLink>
          <NavLink to="/calls" className={({ isActive }) => isActive ? styles.active : ''}>
            <IconPhoneWave size={18} /> Звонки
          </NavLink>
        </nav>

        {me && (
          <button className={styles.profile} onClick={() => setEditingProfile(true)}>
            <Avatar name={me.name} size={34} />
            <div className={styles.profileInfo}>
              <div className={styles.profileName}>{me.name}</div>
              <div className={styles.profileRole}>Администратор</div>
            </div>
          </button>
        )}
        <button className={styles.logoutBtn} onClick={logout}>
          <IconLogout size={16} /> Выйти
        </button>
      </aside>
      <main className={styles.main}>
        {/* Keyed by pathname so page content re-runs its fade-in on every
            navigation, giving routes a light entrance transition. */}
        <div key={location.pathname} className={styles.page}>
          <Outlet />
        </div>
      </main>

      {editingProfile && me && (
        <EditProfileModal
          me={me}
          onClose={() => setEditingProfile(false)}
          onSaved={updated => { setMe(updated); setEditingProfile(false) }}
        />
      )}
    </div>
  )
}

function EditProfileModal({
  me, onClose, onSaved,
}: { me: CurrentUser; onClose: () => void; onSaved: (u: CurrentUser) => void }) {
  const [name, setName] = useState(me.name)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      const updated = await updateMe(name)
      onSaved(updated)
    } catch {
      setError('Не удалось сохранить имя')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="Профиль" onClose={onClose}>
      <form className={formStyles.form} onSubmit={handleSubmit}>
        {error && <div className={formStyles.error} role="alert">{error}</div>}
        <label className={formStyles.label}>
          Имя
          <input
            className={formStyles.input}
            value={name}
            onChange={e => setName(e.target.value)}
            required
            autoFocus
          />
        </label>
        {me.login && (
          <label className={formStyles.label}>
            Логин
            <input className={formStyles.input} value={me.login} disabled />
          </label>
        )}
        <div className={formStyles.actions}>
          <button className={formStyles.btnPrimary} type="submit" disabled={saving}>
            {saving ? 'Сохранение…' : 'Сохранить'}
          </button>
          <button className={formStyles.btnSecondary} type="button" onClick={onClose}>
            Отмена
          </button>
        </div>
      </form>
    </Modal>
  )
}
