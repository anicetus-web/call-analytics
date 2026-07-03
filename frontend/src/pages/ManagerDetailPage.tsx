import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  getManagers, getProjects, getCalls,
  getManagerOverview, getManagerMetrics, getManagerTimeline, getManagerHeatmap,
  Manager, Project, CallListItem, ManagerOverview, MetricSummary, CallsTimelinePoint, HeatmapCell,
} from '../api'
import { IconPhoneWave, IconClock, IconTarget, IconTrend } from '../components/icons'
import Avatar from '../components/Avatar'
import Heatmap from '../components/Heatmap'
import styles from './ManagerDetailPage.module.css'

const ACTIVITY_WINDOW_DAYS = 30

const STATUS_LABELS: Record<string, string> = {
  uploaded: 'Загружен', converting: 'Конвертация', transcribing: 'Транскрипция',
  analyzing: 'Анализ', done: 'Готов', error: 'Ошибка',
}
const STATUS_COLORS: Record<string, string> = {
  uploaded: '#95a5a6', converting: '#6366f1', transcribing: '#8b5cf6',
  analyzing: '#f59e0b', done: '#10b981', error: '#ef4444',
}

function fmtDuration(sec: number): string {
  if (!sec) return '0:00'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

function fmtRelative(iso: string | null): string {
  if (!iso) return 'ещё не было'
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)
  if (days <= 0) return 'сегодня'
  if (days === 1) return 'вчера'
  if (days < 7) return `${days} дн. назад`
  return new Date(iso).toLocaleDateString('ru-RU')
}

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

export default function ManagerDetailPage() {
  const { id } = useParams<{ id: string }>()
  const userId = Number(id)

  const [manager, setManager] = useState<Manager | null>(null)
  const [managerLoaded, setManagerLoaded] = useState(false)
  const [projects, setProjects] = useState<Project[]>([])
  const [tab, setTab] = useState<'all' | number>('all')

  const [overview, setOverview] = useState<ManagerOverview | null>(null)
  const [metrics, setMetrics] = useState<MetricSummary[]>([])
  const [timeline, setTimeline] = useState<CallsTimelinePoint[]>([])
  const [heatmap, setHeatmap] = useState<HeatmapCell[]>([])
  const [calls, setCalls] = useState<CallListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [managerError, setManagerError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const requestIdRef = useRef(0)
  const dateFrom = useMemo(() => isoDaysAgo(ACTIVITY_WINDOW_DAYS), [])

  useEffect(() => {
    Promise.all([getManagers(), getProjects(true)])
      .then(([managers, allProjects]) => {
        setManager(managers.find(m => m.id === userId) ?? null)
        setProjects(allProjects.filter(p => p.members.some(m => m.id === userId)))
      })
      .catch(() => setManagerError('Не удалось загрузить менеджера'))
      .finally(() => setManagerLoaded(true))
  }, [userId])

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    const requestId = ++requestIdRef.current
    const projectId = tab === 'all' ? undefined : tab
    const params = { projectId, dateFrom }

    const metricsPromise = tab === 'all'
      ? Promise.resolve([])
      : getManagerMetrics(userId, tab, dateFrom)

    Promise.all([
      getManagerOverview(userId, params),
      metricsPromise,
      getManagerTimeline(userId, params),
      getManagerHeatmap(userId, params),
      getCalls({ user_id: userId, project_id: projectId, limit: 20 }),
    ])
      .then(([ov, mt, tl, hm, cl]) => {
        if (requestId !== requestIdRef.current) return
        setOverview(ov)
        setMetrics(mt)
        setTimeline(tl)
        setHeatmap(hm)
        setCalls(cl)
      })
      .catch(() => {
        if (requestId !== requestIdRef.current) return
        setError('Не удалось загрузить аналитику менеджера')
      })
      .finally(() => {
        if (requestId === requestIdRef.current) setLoading(false)
      })
  }, [userId, tab, dateFrom])

  useEffect(() => { load() }, [load])

  const activeDatesSet = useMemo(() => new Set(timeline.map(t => t.date)), [timeline])

  const activityStrip = useMemo(() => {
    const days: { date: string; active: boolean }[] = []
    for (let i = ACTIVITY_WINDOW_DAYS - 1; i >= 0; i--) {
      const date = isoDaysAgo(i)
      days.push({ date, active: activeDatesSet.has(date) })
    }
    return days
  }, [activeDatesSet])

  const missedDaysCount = activityStrip.filter(d => !d.active).length

  if (!managerLoaded) return <div className={styles.state}>Загрузка...</div>
  if (managerError) return <div className={`${styles.state} ${styles.error}`}>{managerError}</div>
  if (!manager) return <div className={`${styles.state} ${styles.error}`}>Менеджер не найден</div>

  return (
    <div>
      <Link to="/managers" className={styles.breadcrumb}>← Менеджеры</Link>

      <div className={styles.header}>
        <Avatar name={manager.name} size={48} />
        <div>
          <h1 className={styles.title}>{manager.name}</h1>
          <p className={styles.subtitle}>
            Telegram ID: {manager.telegram_id ?? '—'}
            {manager.login && <> · логин: {manager.login}</>}
          </p>
        </div>
      </div>

      <div className={styles.tabs}>
        <button className={tab === 'all' ? styles.activeTab : styles.tab} onClick={() => setTab('all')}>
          Все проекты
        </button>
        {projects.map(p => (
          <button
            key={p.id}
            className={tab === p.id ? styles.activeTab : styles.tab}
            onClick={() => setTab(p.id)}
          >
            {p.name}
          </button>
        ))}
      </div>

      {error ? (
        <div className={`${styles.state} ${styles.error}`}>{error}</div>
      ) : loading || !overview ? (
        <div className={styles.state}>Загрузка...</div>
      ) : (
        <>
          <div className={styles.tiles}>
            <div className={styles.tile}>
              <span className={styles.tileIcon}><IconPhoneWave size={18} /></span>
              <div>
                <div className={styles.tileValue}>{overview.total_calls}</div>
                <div className={styles.tileLabel}>Звонков за 30 дней</div>
              </div>
            </div>
            <div className={styles.tile}>
              <span className={styles.tileIcon}><IconClock size={18} /></span>
              <div>
                <div className={styles.tileValue}>{fmtDuration(overview.avg_duration_seconds)}</div>
                <div className={styles.tileLabel}>Средняя длительность</div>
              </div>
            </div>
            <div className={styles.tile}>
              <span className={styles.tileIcon}><IconTarget size={18} /></span>
              <div>
                <div className={styles.tileValue}>{(overview.avg_score * 100).toFixed(0)}%</div>
                <div className={styles.tileLabel}>Средний балл</div>
              </div>
            </div>
            <div className={styles.tile}>
              <span className={styles.tileIcon}><IconTrend size={18} /></span>
              <div>
                <div className={styles.tileValue}>{fmtRelative(overview.last_call_at)}</div>
                <div className={styles.tileLabel}>Последний звонок</div>
              </div>
            </div>
          </div>

          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>
              Активность за последние {ACTIVITY_WINDOW_DAYS} дней
              <span className={styles.sectionHint}>
                {' '}— работал {overview.active_days} из {ACTIVITY_WINDOW_DAYS} дней, пропусков: {missedDaysCount}
              </span>
            </h2>
            <div className={styles.activityStrip}>
              {activityStrip.map(d => (
                <span
                  key={d.date}
                  className={d.active ? styles.activityDayActive : styles.activityDay}
                  title={`${new Date(d.date).toLocaleDateString('ru-RU')} — ${d.active ? 'были звонки' : 'звонков не было'}`}
                />
              ))}
            </div>
          </div>

          <div className={styles.grid}>
            {tab !== 'all' && (
              <div className={styles.section}>
                <h2 className={styles.sectionTitle}>По критериям оценки</h2>
                {metrics.length === 0 ? (
                  <div className={styles.empty}>Нет оценённых звонков за этот период</div>
                ) : (
                  <div className={styles.metricTable}>
                    {metrics.map(m => (
                      <div key={m.metric_item_id} className={styles.metricRow}>
                        <span className={styles.metricName}>{m.name}</span>
                        <div className={styles.scoreBar}>
                          <div className={styles.scoreBarFill} style={{ width: `${m.avg_score * 100}%` }} />
                        </div>
                        <span className={styles.scoreVal}>{(m.avg_score * 100).toFixed(0)}%</span>
                        <span className={styles.callCnt}>{m.call_count} зв.</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Когда чаще звонит</h2>
              {heatmap.length === 0 ? (
                <div className={styles.empty}>Нет данных за этот период</div>
              ) : (
                <Heatmap cells={heatmap} />
              )}
            </div>

            <div className={styles.section} style={{ gridColumn: '1 / -1' }}>
              <h2 className={styles.sectionTitle}>Последние звонки</h2>
              {calls.length === 0 ? (
                <div className={styles.empty}>Звонков пока нет</div>
              ) : (
                <div className={styles.callsList}>
                  {calls.map(call => (
                    <Link to={`/calls/${call.id}`} key={call.id} className={styles.callRow}>
                      <div className={styles.callName}>{call.original_filename || `Звонок #${call.id}`}</div>
                      <span className={styles.duration}>{fmtDuration(call.duration_seconds ?? 0)}</span>
                      <span
                        className={styles.badge}
                        style={{ background: STATUS_COLORS[call.status] + '22', color: STATUS_COLORS[call.status] }}
                      >
                        {STATUS_LABELS[call.status] || call.status}
                      </span>
                      <span className={styles.date}>{new Date(call.created_at).toLocaleDateString('ru-RU')}</span>
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
