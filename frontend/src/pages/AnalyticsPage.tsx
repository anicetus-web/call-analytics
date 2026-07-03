import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import {
  getAnalyticsOverview, getCallsTimeline, getDurationBuckets, getHeatmap, getGlobalManagerSummary,
  getProjects, AnalyticsOverview, CallsTimelinePoint, DurationBucket, HeatmapCell, ManagerSummary, Project,
} from '../api'
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { IconPhoneWave, IconClock, IconTarget, IconTrend } from '../components/icons'
import styles from './AnalyticsPage.module.css'

const WEEKDAY_LABELS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

function fmtDuration(sec: number): string {
  if (!sec) return '0:00'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

const chartTooltipStyle = {
  contentStyle: {
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    color: 'var(--text)',
  },
  labelStyle: { color: 'var(--text-muted)' },
}

export default function AnalyticsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const [overview, setOverview] = useState<AnalyticsOverview | null>(null)
  const [timeline, setTimeline] = useState<CallsTimelinePoint[]>([])
  const [buckets, setBuckets] = useState<DurationBucket[]>([])
  const [heatmap, setHeatmapData] = useState<HeatmapCell[]>([])
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
    const params = {
      projectId: projectId ? Number(projectId) : undefined,
      dateFrom: dateFrom || undefined,
      dateTo: dateTo || undefined,
    }
    Promise.all([
      getAnalyticsOverview(params),
      getCallsTimeline(params),
      getDurationBuckets(params),
      getHeatmap(params),
      getGlobalManagerSummary(params),
    ])
      .then(([ov, tl, durationBuckets, hm, mg]) => {
        if (requestId !== requestIdRef.current) return
        setOverview(ov)
        setTimeline(tl)
        setBuckets(durationBuckets)
        setHeatmapData(hm)
        setManagers(mg)
      })
      .catch(() => {
        if (requestId !== requestIdRef.current) return
        setError('Не удалось загрузить аналитику')
      })
      .finally(() => {
        if (requestId === requestIdRef.current) setLoading(false)
      })
  }, [projectId, dateFrom, dateTo])

  useEffect(() => { load() }, [load])

  const heatmapMap = useMemo(() => {
    const map = new Map<string, number>()
    for (const cell of heatmap) map.set(`${cell.weekday}-${cell.hour}`, cell.call_count)
    return map
  }, [heatmap])

  const heatmapMax = useMemo(
    () => heatmap.reduce((max, c) => Math.max(max, c.call_count), 0),
    [heatmap]
  )

  return (
    <div>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Аналитика</h1>
          <p className={styles.subtitle}>Сводка по звонкам и работе менеджеров</p>
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
        <div className={styles.state}>Загрузка...</div>
      ) : error ? (
        <div className={`${styles.state} ${styles.error}`}>{error}</div>
      ) : !overview ? null : (
        <>
          <div className={styles.tiles}>
            <div className={styles.tile}>
              <span className={styles.tileIcon}><IconPhoneWave size={18} /></span>
              <div>
                <div className={styles.tileValue}>{overview.total_calls}</div>
                <div className={styles.tileLabel}>Всего звонков</div>
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
                <div className={styles.tileValue}>{overview.calls_last_7_days}</div>
                <div className={styles.tileLabel}>Звонков за 7 дней</div>
              </div>
            </div>
          </div>

          <div className={styles.grid}>
            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Звонки по дням</h2>
              {timeline.length === 0 ? (
                <div className={styles.empty}>Нет данных за выбранный период</div>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={timeline}>
                    <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} stroke="var(--border)" />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} stroke="var(--border)" />
                    <Tooltip {...chartTooltipStyle} />
                    <Line type="monotone" dataKey="call_count" name="Звонков" stroke="#ec4899" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Распределение по длительности</h2>
              {buckets.every(b => b.call_count === 0) ? (
                <div className={styles.empty}>Нет данных за выбранный период</div>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={buckets}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} stroke="var(--border)" />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} stroke="var(--border)" />
                    <Tooltip {...chartTooltipStyle} />
                    <Bar dataKey="call_count" name="Звонков" fill="#6366f1" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Загрузка по времени</h2>
              {heatmap.length === 0 ? (
                <div className={styles.empty}>Нет данных за выбранный период</div>
              ) : (
                <div className={styles.heatmap}>
                  <div className={styles.heatmapRow}>
                    <span className={styles.heatmapCorner} />
                    {Array.from({ length: 24 }, (_, h) => (
                      <span key={h} className={styles.heatmapHourLabel}>{h % 3 === 0 ? h : ''}</span>
                    ))}
                  </div>
                  {WEEKDAY_LABELS.map((label, weekday) => (
                    <div key={weekday} className={styles.heatmapRow}>
                      <span className={styles.heatmapDayLabel}>{label}</span>
                      {Array.from({ length: 24 }, (_, hour) => {
                        const count = heatmapMap.get(`${weekday}-${hour}`) ?? 0
                        const intensity = heatmapMax > 0 ? count / heatmapMax : 0
                        return (
                          <span
                            key={hour}
                            className={styles.heatmapCell}
                            style={{ background: intensity > 0 ? `rgba(236,72,153,${0.12 + intensity * 0.75})` : undefined }}
                            title={`${label}, ${hour}:00 — ${count} зв.`}
                          />
                        )
                      })}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>По менеджерам</h2>
              {managers.length === 0 ? (
                <div className={styles.empty}>Нет данных за выбранный период</div>
              ) : (
                <div className={styles.metricTable}>
                  {managers.map(m => (
                    <div key={m.user_id} className={styles.metricRow}>
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
          </div>
        </>
      )}
    </div>
  )
}
