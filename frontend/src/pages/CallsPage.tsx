import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getCalls, getProjects, getManagers, CallListItem, CallStatus, Project, Manager } from '../api'
import { IconAlert } from '../components/icons'
import styles from './CallsPage.module.css'

const STATUS_LABELS: Record<CallStatus, string> = {
  uploaded: 'Загружен',
  converting: 'Конвертация',
  transcribing: 'Транскрипция',
  analyzing: 'Анализ',
  done: 'Готов',
  error: 'Ошибка',
}

const STATUS_COLORS: Record<CallStatus, string> = {
  uploaded: '#95a5a6',
  converting: '#6366f1',
  transcribing: '#8b5cf6',
  analyzing: '#f59e0b',
  done: '#10b981',
  error: '#ef4444',
}

const PAGE_SIZE = 50

function fmtDuration(sec: number | null): string {
  if (!sec) return '—'
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function CallsPage() {
  const [searchParams] = useSearchParams()
  const [calls, setCalls] = useState<CallListItem[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [managers, setManagers] = useState<Manager[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [offset, setOffset] = useState(0)

  const [projectId, setProjectId] = useState(searchParams.get('project_id') ?? '')
  const [userId, setUserId] = useState(searchParams.get('user_id') ?? '')
  const [status, setStatus] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [onlyErrors, setOnlyErrors] = useState(false)

  const effectiveStatus = onlyErrors ? 'error' : status

  // Guards against out-of-order responses: if filters change again while a
  // request is in flight, a slower earlier response must not overwrite the
  // list with stale data once the newer request resolves.
  const requestIdRef = useRef(0)

  const load = useCallback((off: number) => {
    if (off === 0) setLoading(true)
    setError(null)
    const requestId = ++requestIdRef.current
    return getCalls({
      project_id: projectId ? Number(projectId) : undefined,
      user_id: userId ? Number(userId) : undefined,
      status: (effectiveStatus || undefined) as CallStatus | undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      limit: PAGE_SIZE,
      offset: off,
    })
      .then(data => {
        if (requestId !== requestIdRef.current) return
        setCalls(prev => (off === 0 ? data : [...prev, ...data]))
        setHasMore(data.length === PAGE_SIZE)
        setOffset(off + data.length)
      })
      .catch(() => {
        if (requestId !== requestIdRef.current) return
        setError('Не удалось загрузить звонки')
      })
      .finally(() => {
        if (requestId === requestIdRef.current) setLoading(false)
      })
  }, [projectId, userId, effectiveStatus, dateFrom, dateTo])

  useEffect(() => {
    Promise.all([getProjects(true), getManagers()])
      .then(([p, m]) => { setProjects(p); setManagers(m) })
      .catch(() => {})
  }, [])

  useEffect(() => { load(0) }, [load])

  const projectName = useMemo(() => {
    const map = new Map(projects.map(p => [p.id, p.name]))
    return (id: number) => map.get(id) ?? `Проект #${id}`
  }, [projects])

  const managerName = useMemo(() => {
    const map = new Map(managers.map(m => [m.id, m.name]))
    return (id: number) => map.get(id) ?? `Менеджер #${id}`
  }, [managers])

  // Cascade: once a project is picked, only offer managers who actually belong to
  // it — selecting a manager from a different project would just silently return
  // zero calls otherwise.
  const managerOptions = useMemo(() => {
    if (!projectId) return managers
    const project = projects.find(p => String(p.id) === projectId)
    if (!project) return managers
    const memberIds = new Set(project.members.map(m => m.id))
    return managers.filter(m => memberIds.has(m.id))
  }, [managers, projects, projectId])

  function handleProjectChange(value: string) {
    setProjectId(value)
    if (value && userId) {
      const project = projects.find(p => String(p.id) === value)
      if (project && !project.members.some(m => String(m.id) === userId)) {
        setUserId('')
      }
    }
  }

  const statusCounts = useMemo(() => {
    const counts: Partial<Record<CallStatus, number>> = {}
    for (const c of calls) counts[c.status] = (counts[c.status] ?? 0) + 1
    return counts
  }, [calls])

  return (
    <div>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Звонки</h1>
          <p className={styles.subtitle}>Все записи со всех проектов в одном месте</p>
        </div>
      </div>

      <div className={styles.filters}>
        <select className={styles.filterSelect} aria-label="Проект" value={projectId} onChange={e => handleProjectChange(e.target.value)}>
          <option value="">Все проекты</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select className={styles.filterSelect} aria-label="Менеджер" value={userId} onChange={e => setUserId(e.target.value)}>
          <option value="">Все менеджеры</option>
          {managerOptions.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        <select
          className={styles.filterSelect}
          aria-label="Статус"
          value={status}
          onChange={e => { setStatus(e.target.value); setOnlyErrors(false) }}
          disabled={onlyErrors}
        >
          <option value="">Все статусы</option>
          {Object.entries(STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <input
          type="date"
          className={styles.filterDate}
          aria-label="Дата от"
          value={dateFrom}
          onChange={e => setDateFrom(e.target.value)}
        />
        <span className={styles.dash}>—</span>
        <input
          type="date"
          className={styles.filterDate}
          aria-label="Дата до"
          value={dateTo}
          onChange={e => setDateTo(e.target.value)}
        />
        <button
          className={onlyErrors ? styles.errorToggleActive : styles.errorToggle}
          onClick={() => { setOnlyErrors(v => !v); setStatus('') }}
        >
          <IconAlert size={14} />
          Только ошибки
        </button>
      </div>

      {!loading && calls.length > 0 && (
        <div className={styles.statsRow}>
          {(Object.keys(STATUS_LABELS) as CallStatus[]).map(s => (
            statusCounts[s] ? (
              <span key={s} className={styles.statChip} style={{ color: STATUS_COLORS[s] }}>
                {statusCounts[s]} {STATUS_LABELS[s].toLowerCase()}
              </span>
            ) : null
          ))}
        </div>
      )}

      {loading ? (
        <div className={styles.state}>Загрузка…</div>
      ) : error ? (
        <div className={`${styles.state} ${styles.error}`}>{error}</div>
      ) : calls.length === 0 ? (
        <div className={styles.empty}>Звонков не найдено</div>
      ) : (
        <div className={styles.list}>
          {calls.map(call => (
            <Link to={`/calls/${call.id}`} key={call.id} className={styles.row} state={{ from: 'calls' }}>
              <span className={styles.projectBadge}>{projectName(call.project_id)}</span>
              <div className={styles.rowName}>
                {call.original_filename || `Звонок #${call.id}`}
              </div>
              <span className={styles.rowManager}>{managerName(call.user_id)}</span>
              <span className={styles.rowDuration}>{fmtDuration(call.duration_seconds)}</span>
              <span
                className={styles.badge}
                style={{ background: STATUS_COLORS[call.status] + '22', color: STATUS_COLORS[call.status] }}
              >
                {STATUS_LABELS[call.status] || call.status}
              </span>
              <span className={styles.rowDate}>
                {new Date(call.created_at).toLocaleDateString('ru-RU')}
              </span>
            </Link>
          ))}
          {hasMore && (
            <button className={styles.loadMore} onClick={() => load(offset)}>
              Загрузить ещё
            </button>
          )}
        </div>
      )}
    </div>
  )
}
