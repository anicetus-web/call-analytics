import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  getManagers, getProjects, getCalls,
  getManagerOverview, getManagerMetrics, getManagerTimeline,
  Manager, Project, CallListItem, ManagerOverview, MetricSummary, CallsTimelinePoint,
} from '../api'
import { IconPhoneWave, IconClock, IconTarget, IconTrend } from '../components/icons'
import Avatar from '../components/Avatar'
import SessionStatus from '../components/SessionStatus'
import styles from './ManagerDetailPage.module.css'

const PERIODS = [
  { key: 'day', label: 'День', days: 1 },
  { key: 'week', label: 'Неделя', days: 7 },
  { key: 'month', label: 'Месяц', days: 30 },
] as const
type PeriodKey = typeof PERIODS[number]['key']

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

// Matches the high/medium/low palette already used for quality distribution
// elsewhere in the app, so a score reads the same way everywhere.
function scoreTierColor(avgScore: number): string {
  if (avgScore >= 0.8) return '#34d399'
  if (avgScore >= 0.5) return '#eab308'
  return '#fb7185'
}

interface MetricGroupBlock {
  id: number
  name: string
  items: MetricSummary[]
}

// One block per metric group (backend already sorts group-then-position), so a
// manager's criteria read as separate groups instead of one mixed list.
function groupMetrics(metrics: MetricSummary[]): MetricGroupBlock[] {
  const blocks: MetricGroupBlock[] = []
  const byId = new Map<number, MetricGroupBlock>()
  for (const m of metrics) {
    let block = byId.get(m.metric_group_id)
    if (!block) {
      block = { id: m.metric_group_id, name: m.metric_group_name, items: [] }
      byId.set(m.metric_group_id, block)
      blocks.push(block)
    }
    block.items.push(m)
  }
  return blocks
}

function fmtRelative(iso: string | null): string {
  if (!iso) return 'ещё не было'
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)
  if (days <= 0) return 'сегодня'
  if (days === 1) return 'вчера'
  if (days < 7) return `${days} дн. назад`
  return new Date(iso).toLocaleDateString('ru-RU')
}

function pluralDays(n: number): string {
  if (n % 10 === 1 && n % 100 !== 11) return 'день'
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return 'дня'
  return 'дней'
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
  const [period, setPeriod] = useState<PeriodKey>('month')

  const [activeDay, setActiveDay] = useState<{ date: string; active: boolean } | null>(null)

  const [overview, setOverview] = useState<ManagerOverview | null>(null)
  const [metrics, setMetrics] = useState<MetricSummary[]>([])
  const [timeline, setTimeline] = useState<CallsTimelinePoint[]>([])
  const [calls, setCalls] = useState<CallListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [managerError, setManagerError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const requestIdRef = useRef(0)
  const windowDays = PERIODS.find(p => p.key === period)!.days
  // windowDays - 1: "День" (1) must resolve to today only, not today+yesterday —
  // matches the activityStrip loop below, which also starts at isoDaysAgo(windowDays - 1).
  const dateFrom = useMemo(() => isoDaysAgo(windowDays - 1), [windowDays])

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
      getCalls({ user_id: userId, project_id: projectId, limit: 20 }),
    ])
      .then(([ov, mt, tl, cl]) => {
        if (requestId !== requestIdRef.current) return
        setOverview(ov)
        setMetrics(mt)
        setTimeline(tl)
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
    for (let i = windowDays - 1; i >= 0; i--) {
      const date = isoDaysAgo(i)
      days.push({ date, active: activeDatesSet.has(date) })
    }
    return days
  }, [activeDatesSet, windowDays])

  const missedDaysCount = activityStrip.filter(d => !d.active).length

  if (!managerLoaded) return <div className={styles.state}>Загрузка…</div>
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
          <SessionStatus active={!!manager.session_started_at} since={manager.session_started_at} size={13} />
        </div>
      </div>

      <div className={styles.tabsRow}>
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
        <div className={styles.periodToggle}>
          {PERIODS.map(p => (
            <button
              key={p.key}
              className={period === p.key ? styles.periodBtnActive : styles.periodBtn}
              onClick={() => setPeriod(p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <div className={`${styles.state} ${styles.error}`}>{error}</div>
      ) : loading || !overview ? (
        <div className={styles.state}>Загрузка…</div>
      ) : (
        <>
          <div className={styles.tiles}>
            <div className={styles.tile}>
              <span className={styles.tileIcon}><IconPhoneWave size={18} /></span>
              <div>
                <div className={styles.tileValue}>{overview.total_calls}</div>
                <div className={styles.tileLabel}>Звонков за {windowDays} {pluralDays(windowDays)}</div>
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
              Активность за последние {windowDays} {pluralDays(windowDays)}
              <span className={styles.sectionHint}>
                {' '}— работал {overview.active_days} из {windowDays} {pluralDays(windowDays)}, пропусков: {missedDaysCount}
              </span>
            </h2>
            <div className={styles.infoBar}>
              {activeDay ? (
                <span className={styles.infoChip}>
                  {new Date(activeDay.date).toLocaleDateString('ru-RU')} — {activeDay.active ? 'были звонки' : 'звонков не было'}
                </span>
              ) : (
                <span className={styles.infoHint}>Наведите или нажмите на день</span>
              )}
            </div>
            <div className={styles.activityStrip}>
              {activityStrip.map(d => (
                <span
                  key={d.date}
                  className={activeDay?.date === d.date
                    ? (d.active ? styles.activityDayActiveSelected : styles.activityDaySelected)
                    : (d.active ? styles.activityDayActive : styles.activityDay)}
                  onMouseEnter={() => setActiveDay(d)}
                  onMouseLeave={() => setActiveDay(null)}
                  onClick={() => setActiveDay(d)}
                />
              ))}
            </div>
          </div>

          <div className={styles.grid}>
            {tab !== 'all' && (
              <div className={styles.section} style={{ gridColumn: '1 / -1' }}>
                <h2 className={styles.sectionTitle}>По критериям оценки</h2>
                {metrics.length === 0 ? (
                  <div className={styles.empty}>Нет оценённых звонков за этот период</div>
                ) : (
                  groupMetrics(metrics).map(group => {
                    const groupAvg = group.items.reduce((s, i) => s + i.avg_score, 0) / group.items.length
                    return (
                      <div key={group.id} className={styles.metricGroupBlock}>
                        <div className={styles.metricGroupHead}>
                          <span className={styles.metricGroupName}>{group.name}</span>
                          <span className={styles.metricGroupScore} style={{ color: scoreTierColor(groupAvg) }}>
                            {Math.round(groupAvg * 100)}%
                          </span>
                        </div>
                        <div className={styles.metricGrid}>
                          {group.items.map(m => {
                            const pct = Math.round(m.avg_score * 100)
                            const color = scoreTierColor(m.avg_score)
                            return (
                              <div key={m.metric_item_id} className={styles.metricCard}>
                                <div
                                  className={styles.metricRing}
                                  style={{ background: `conic-gradient(${color} ${pct * 3.6}deg, var(--bg-elevated) 0deg)` }}
                                >
                                  <span className={styles.metricRingValue}>{pct}%</span>
                                </div>
                                <span className={styles.metricCardName}>{m.name}</span>
                                <span className={styles.metricCardCnt}>{m.call_count} зв.</span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            )}

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
