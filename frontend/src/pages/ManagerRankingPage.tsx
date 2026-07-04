import { useEffect, useState, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import { getGlobalManagerSummary, getProjects, ManagerSummary, Project } from '../api'
import Avatar from '../components/Avatar'
import styles from './ManagerRankingPage.module.css'

function fmtPct(v: number): string {
  return `${Math.round(v * 100)}%`
}

function scoreColor(v: number): string {
  if (v >= 0.8) return '#10b981'
  if (v >= 0.5) return '#eab308'
  return '#f43f5e'
}

export default function ManagerRankingPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [managers, setManagers] = useState<ManagerSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const requestIdRef = useRef(0)

  useEffect(() => {
    getProjects(true).then(setProjects).catch(() => {})
  }, [])

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    const requestId = ++requestIdRef.current
    getGlobalManagerSummary({
      projectId: projectId ? Number(projectId) : undefined,
      dateFrom: dateFrom || undefined,
      dateTo: dateTo || undefined,
    })
      .then(data => {
        if (requestId !== requestIdRef.current) return
        setManagers(data)
      })
      .catch(() => {
        if (requestId !== requestIdRef.current) return
        setError('Не удалось загрузить рейтинг')
      })
      .finally(() => {
        if (requestId === requestIdRef.current) setLoading(false)
      })
  }, [projectId, dateFrom, dateTo])

  useEffect(() => { load() }, [load])

  return (
    <div>
      <Link to="/analytics" className={styles.breadcrumb}>← Аналитика</Link>

      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Рейтинг менеджеров</h1>
          <p className={styles.subtitle}>Все менеджеры по средней оценке AI, от лучшего к худшему</p>
        </div>
      </div>

      <div className={styles.filters}>
        <select className={styles.filterSelect} value={projectId} onChange={e => setProjectId(e.target.value)}>
          <option value="">Все проекты</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <input type="date" className={styles.filterDate} value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
        <span className={styles.dash}>—</span>
        <input type="date" className={styles.filterDate} value={dateTo} onChange={e => setDateTo(e.target.value)} />
      </div>

      {loading ? (
        <div className={styles.state}>Загрузка…</div>
      ) : error ? (
        <div className={`${styles.state} ${styles.error}`}>{error}</div>
      ) : managers.length === 0 ? (
        <div className={styles.empty}>Нет оценённых звонков за выбранный период</div>
      ) : (
        <div className={styles.list}>
          {managers.map((m, i) => (
            <Link to={`/managers/${m.user_id}`} key={m.user_id} className={styles.row}>
              <span className={styles.rank}>{i + 1}</span>
              <Avatar name={m.name} size={36} />
              <span className={styles.name}>{m.name}</span>
              <div className={styles.barTrack}>
                <div
                  className={styles.barFill}
                  style={{ width: `${m.avg_score * 100}%`, background: scoreColor(m.avg_score) }}
                />
              </div>
              <span className={styles.pct}>{fmtPct(m.avg_score)}</span>
              <span className={styles.count}>{m.call_count} зв.</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
