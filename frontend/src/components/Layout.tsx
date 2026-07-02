import { Outlet, NavLink } from 'react-router-dom'
import { logout } from '../api'
import styles from './Layout.module.css'

export default function Layout() {
  return (
    <div className={styles.root}>
      <aside className={styles.sidebar}>
        <div className={styles.logo}>📞 Call Analytics</div>
        <nav className={styles.nav}>
          <NavLink to="/projects" className={({ isActive }) => isActive ? styles.active : ''}>
            Проекты
          </NavLink>
        </nav>
        <button className={styles.logoutBtn} onClick={logout}>Выйти</button>
      </aside>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  )
}
