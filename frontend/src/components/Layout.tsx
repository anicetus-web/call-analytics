import { useEffect, useState } from 'react'
import { Outlet, NavLink } from 'react-router-dom'
import { logout, getMe, CurrentUser } from '../api'
import { LogoMark, IconFolder, IconUsers, IconPhoneWave, IconLogout } from './icons'
import Avatar from './Avatar'
import styles from './Layout.module.css'

export default function Layout() {
  const [me, setMe] = useState<CurrentUser | null>(null)

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
          <NavLink to="/managers" className={({ isActive }) => isActive ? styles.active : ''}>
            <IconUsers size={18} /> Менеджеры
          </NavLink>
          <NavLink to="/calls" className={({ isActive }) => isActive ? styles.active : ''}>
            <IconPhoneWave size={18} /> Звонки
          </NavLink>
        </nav>

        {me && (
          <div className={styles.profile}>
            <Avatar name={me.name} size={34} />
            <div className={styles.profileInfo}>
              <div className={styles.profileName}>{me.name}</div>
              <div className={styles.profileRole}>Администратор</div>
            </div>
          </div>
        )}
        <button className={styles.logoutBtn} onClick={logout}>
          <IconLogout size={16} /> Выйти
        </button>
      </aside>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  )
}
