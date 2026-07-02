import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getProjects, Project } from '../api'
import styles from './ProjectsPage.module.css'

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getProjects()
      .then(setProjects)
      .catch(() => setError('Не удалось загрузить проекты'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className={styles.state}>Загрузка...</div>
  if (error) return <div className={styles.state + ' ' + styles.error}>{error}</div>

  return (
    <div>
      <h1 className={styles.title}>Проекты</h1>

      {projects.length === 0 ? (
        <div className={styles.empty}>Нет активных проектов</div>
      ) : (
        <div className={styles.grid}>
          {projects.map(p => (
            <Link to={`/projects/${p.id}`} key={p.id} className={styles.card}>
              <div className={styles.cardName}>{p.name}</div>
              {p.description && (
                <div className={styles.cardDesc}>{p.description}</div>
              )}
              <div className={styles.cardMeta}>
                {p.members.length} {pluralMembers(p.members.length)}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

function pluralMembers(n: number): string {
  if (n % 10 === 1 && n % 100 !== 11) return 'менеджер'
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return 'менеджера'
  return 'менеджеров'
}
