import { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  getProject, getCalls, getMetricSummary, getManagerSummary, getTimeline,
  Project, CallListItem, MetricSummary, ManagerSummary, TimelinePoint,
} from '../api'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import styles from './ProjectDetailPage.module.css'

type Tab = 'calls' | 'analytics'

const STATUS_LABELS: Record<string, string> = {
  uploaded: 'Загружен',
  converting: 'Конвертация',
  transcribing: 'Транскрипция',
  analyzing: 'Анализ',
  done: 'Готов',
  error: 'Ошибка',
}

const STATUS_COLORS: Record<string, string> = {
  uploaded: '#95a5a6',
  converting: '#3498db',
  transcribing: '#9b59b6',
  analyzing: '#e67e22',
  done: '#27ae60',
  error: '#e74c3c',
}

const PAGE_SIZE = 50

function fmtDuration(sec: number | null): string {
  if (!sec) return '—'
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)

  const [project, setProject] = useState<Project | null>(null)
  const [tab, setTab] = useState<Tab>('calls')
  const [calls, setCalls] = useState<CallListItem[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [offset, setOffset] = useState(0)
  const [metrics, setMetrics] = useState<MetricSummary[]>([])
  const [managers, setManagers] = useState<ManagerSummary[]>([])
  const [timeline, setTimeline] = useState<TimelinePoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadCalls = useCallback(async (off: number) => {
    const data = await getCalls({ project_id: projectId, limit: PAGE_SIZE, offset: off })
    if (off === 0) {
      setCalls(data)
    } else {
      setCalls(prev => [...prev, ...data])
    }
    setHasMore(data.length === PAGE_SIZE)
    setOffset(off + data.length)
  }, [projectId])

  useEffect(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      getProject(projectId).then(setProject),
      loadCalls(0),
      getMetricSummary(projectId).then(setMetrics),
      getManagerSummary(projectId).then(setManagers),
      getTimeline(projectId).then(setTimeline),
    ])
      .catch(() => setError('Не удалось загрузить данные проекта'))
      .finally(() => setLoading(false))
  }, [projectId, loadCalls])

  if (loading) return <div className={styles.state}>Загрузка...</div>
  if (error) return <div className={`${styles.state} ${styles.error}`}>{error}</div>
  if (!project) return <div className={styles.state}>Проект не найден</div>

  return (
    <div>
      <div className={styles.header}>
        <div>
          <Link to="/projects" className={styles.breadcrumb}>← Проекты</Link>
          <h1 className={styles.title}>{project.name}</h1>
          {project.description && <p className={styles.desc}>{project.description}</p>}
        </div>
      </div>

      <div className={styles.tabs}>
        <button
          className={tab === 'calls' ? styles.activeTab : styles.tab}
          onClick={() => setTab('calls')}
        >
          Звонки ({calls.length}{hasMore ? '+' : ''})
        </button>
        <button
          className={tab === 'analytics' ? styles.activeTab : styles.tab}
          onClick={() => setTab('analytics')}
        >
          Аналитика
        </button>
      </div>

      {tab === 'calls' && (
        <div className={styles.callsList}>
          {calls.length === 0 ? (
            <div className={styles.empty}>Звонков пока нет</div>
          ) : (
            <>
              {calls.map(call => (
                <Link to={`/calls/${call.id}`} key={call.id} className={styles.callRow}>
                  <div className={styles.callName}>
                    {call.original_filename || `Звонок #${call.id}`}
                  </div>
                  <div className={styles.callMeta}>
                    <span className={styles.duration}>{fmtDuration(call.duration_seconds)}</span>
                    <span
                      className={styles.badge}
                      style={{ background: STATUS_COLORS[call.status] + '22', color: STATUS_COLORS[call.status] }}
                    >
                      {STATUS_LABELS[call.status] || call.status}
                    </span>
                    <span className={styles.date}>
                      {new Date(call.created_at).toLocaleDateString('ru-RU')}
                    </span>
                  </div>
                </Link>
              ))}
              {hasMore && (
                <button
                  className={styles.loadMore}
                  onClick={() => loadCalls(offset)}
                >
                  Загрузить ещё
                </button>
              )}
            </>
          )}
        </div>
      )}

      {tab === 'analytics' && (
        <div className={styles.analytics}>
          {timeline.length > 0 && (
            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Средний балл по дням</h2>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={timeline}>
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: number) => `${(v * 100).toFixed(0)}%`} />
                  <Line type="monotone" dataKey="avg_score" stroke="#3498db" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {metrics.length > 0 && (
            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>По критериям</h2>
              <div className={styles.metricTable}>
                {metrics.map(m => (
                  <div key={m.metric_item_id} className={styles.metricRow}>
                    <span className={styles.metricName}>{m.name}</span>
                    <div className={styles.scoreBar}>
                      <div
                        className={styles.scoreBarFill}
                        style={{ width: `${m.avg_score * 100}%` }}
                      />
                    </div>
                    <span className={styles.scoreVal}>{(m.avg_score * 100).toFixed(0)}%</span>
                    <span className={styles.callCnt}>{m.call_count} зв.</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {managers.length > 0 && (
            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>По менеджерам</h2>
              <div className={styles.metricTable}>
                {managers.map(m => (
                  <div key={m.user_id} className={styles.metricRow}>
                    <span className={styles.metricName}>{m.name}</span>
                    <div className={styles.scoreBar}>
                      <div
                        className={styles.scoreBarFill}
                        style={{ width: `${m.avg_score * 100}%` }}
                      />
                    </div>
                    <span className={styles.scoreVal}>{(m.avg_score * 100).toFixed(0)}%</span>
                    <span className={styles.callCnt}>{m.call_count} зв.</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {metrics.length === 0 && managers.length === 0 && timeline.length === 0 && (
            <div className={styles.empty}>Нет данных для аналитики</div>
          )}
        </div>
      )}
    </div>
  )
}
