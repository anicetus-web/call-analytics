import { useEffect, useState, useCallback, useRef } from 'react'
import {
  getKpi, getTopErrors, getQualityDistribution, getManagersTrend, getKeywords,
  getDurationBuckets, getMetricSummary, getProjects,
  Kpi, TopErrorItem, QualityDistribution, ManagerTrendItem, KeywordItem, DurationBucket, MetricSummary, Project,
} from '../api'
import { PieChart, Pie, Cell, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { IconTarget, IconTrend, IconAlert, IconPhoneWave } from '../components/icons'
import styles from './AnalyticsPage.module.css'

const QUALITY_COLORS = { high: '#10b981', medium: '#f59e0b', low: '#ef4444' }

const chartTooltipStyle = {
  contentStyle: {
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    color: 'var(--text)',
  },
  labelStyle: { color: 'var(--text-muted)' },
}

function fmtPct(v: number): string {
  return `${Math.round(v * 100)}%`
}

// v is a fraction-of-1 delta (e.g. 0.04 = "+4 percentage points"), matching how avg_score itself is stored.
function fmtDelta(v: number | null): { text: string; className: string } | null {
  if (v === null) return null
  const points = Math.round(v * 100)
  if (points === 0) return { text: '→ 0%', className: styles.deltaFlat }
  const sign = points > 0 ? '↑' : '↓'
  const cls = points > 0 ? styles.deltaUp : styles.deltaDown
  return { text: `${sign} ${Math.abs(points)}%`, className: cls }
}

export default function AnalyticsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const [kpi, setKpi] = useState<Kpi | null>(null)
  const [quality, setQuality] = useState<QualityDistribution | null>(null)
  const [topErrors, setTopErrors] = useState<TopErrorItem[]>([])
  const [managersTrend, setManagersTrend] = useState<ManagerTrendItem[]>([])
  const [keywords, setKeywords] = useState<KeywordItem[]>([])
  const [skills, setSkills] = useState<MetricSummary[]>([])
  const [buckets, setBuckets] = useState<DurationBucket[]>([])
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
    const numericProjectId = projectId ? Number(projectId) : undefined
    const params = { projectId: numericProjectId, dateFrom: dateFrom || undefined, dateTo: dateTo || undefined }

    const skillsPromise = numericProjectId
      ? getMetricSummary(numericProjectId, dateFrom || undefined, dateTo || undefined)
      : Promise.resolve([])

    Promise.all([
      getKpi(numericProjectId),
      getQualityDistribution(params),
      getTopErrors(params, 5),
      getManagersTrend(numericProjectId),
      getKeywords(params, 16),
      skillsPromise,
      getDurationBuckets(params),
    ])
      .then(([kp, ql, te, mt, kw, sk, db]) => {
        if (requestId !== requestIdRef.current) return
        setKpi(kp)
        setQuality(ql)
        setTopErrors(te)
        setManagersTrend(mt)
        setKeywords(kw)
        setSkills(sk)
        setBuckets(db)
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

  const topManagers = managersTrend.slice(0, 3)
  const worstManagers = [...managersTrend].slice(3).reverse()

  const qualityData = quality
    ? [
        { name: 'Высокое', key: 'high', value: quality.high },
        { name: 'Среднее', key: 'medium', value: quality.medium },
        { name: 'Низкое', key: 'low', value: quality.low },
      ].filter(d => d.value > 0)
    : []

  const scoreDelta = kpi ? fmtDelta(kpi.avg_score_delta) : null

  return (
    <div>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Аналитика</h1>
          <p className={styles.subtitle}>Оценка качества работы менеджеров по данным AI-анализа звонков</p>
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
        <span className={styles.filterNote}>Диапазон дат влияет на всё, кроме KPI и рейтинга менеджеров — те всегда за последние 7 дней</span>
      </div>

      {loading ? (
        <div className={styles.state}>Загрузка...</div>
      ) : error ? (
        <div className={`${styles.state} ${styles.error}`}>{error}</div>
      ) : !kpi ? null : (
        <>
          <div className={styles.tiles}>
            <div className={styles.tile}>
              <span className={styles.tileIcon}><IconTarget size={18} /></span>
              <div>
                <div className={styles.tileValue}>
                  {fmtPct(kpi.avg_score)}
                  {scoreDelta && <span className={scoreDelta.className}> {scoreDelta.text}</span>}
                </div>
                <div className={styles.tileLabel}>Средняя оценка AI за неделю</div>
              </div>
            </div>
            <div className={styles.tile}>
              <span className={styles.tileIcon}><IconTrend size={18} /></span>
              <div>
                <div className={styles.tileValue}>{kpi.best_manager ? kpi.best_manager.name : '—'}</div>
                <div className={styles.tileLabel}>
                  Лучший менеджер недели{kpi.best_manager && ` — ${fmtPct(kpi.best_manager.avg_score)}`}
                </div>
              </div>
            </div>
            <div className={styles.tile}>
              <span className={styles.tileIcon}><IconAlert size={18} /></span>
              <div>
                <div className={styles.tileValue}>
                  {kpi.main_problem ? `${kpi.main_problem.fail_count} случаев` : '—'}
                </div>
                <div className={styles.tileLabel}>
                  {kpi.main_problem ? kpi.main_problem.metric_name : 'Основная проблема за неделю'}
                </div>
              </div>
            </div>
            <div className={styles.tile}>
              <span className={styles.tileIcon}><IconPhoneWave size={18} /></span>
              <div>
                <div className={styles.tileValue}>{kpi.calls_analyzed}</div>
                <div className={styles.tileLabel}>Звонков оценено AI за неделю</div>
              </div>
            </div>
          </div>

          <div className={styles.grid}>
            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Распределение качества звонков</h2>
              {qualityData.length === 0 ? (
                <div className={styles.empty}>Нет оценённых звонков за выбранный период</div>
              ) : (
                <div className={styles.donutRow}>
                  <ResponsiveContainer width={180} height={180}>
                    <PieChart>
                      <Pie data={qualityData} dataKey="value" innerRadius={55} outerRadius={80} paddingAngle={2}>
                        {qualityData.map(d => (
                          <Cell key={d.key} fill={QUALITY_COLORS[d.key as keyof typeof QUALITY_COLORS]} />
                        ))}
                      </Pie>
                      <Tooltip {...chartTooltipStyle} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className={styles.donutLegend}>
                    {qualityData.map(d => (
                      <div key={d.key} className={styles.donutLegendRow}>
                        <span className={styles.donutDot} style={{ background: QUALITY_COLORS[d.key as keyof typeof QUALITY_COLORS] }} />
                        {d.name}
                        <span className={styles.donutCount}>{d.value}</span>
                      </div>
                    ))}
                    <div className={styles.donutTotal}>Всего оценено: {quality?.total}</div>
                  </div>
                </div>
              )}
            </div>

            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Частые ошибки менеджеров</h2>
              {topErrors.length === 0 ? (
                <div className={styles.empty}>Нет данных за выбранный период</div>
              ) : (
                <div className={styles.errorList}>
                  {topErrors.map(e => (
                    <div key={e.metric_item_id} className={styles.errorRow}>
                      <span className={styles.errorName}>
                        {e.metric_name}
                        {!projectId && <span className={styles.errorProject}> · {e.project_name}</span>}
                      </span>
                      <span className={styles.errorCount}>{e.fail_count} случаев</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>
                Топ менеджеров <span className={styles.sectionHint}>за последние 7 дней</span>
              </h2>
              {topManagers.length === 0 ? (
                <div className={styles.empty}>Нет оценённых звонков за неделю</div>
              ) : (
                <div className={styles.rankList}>
                  {topManagers.map((m, i) => {
                    const delta = fmtDelta(m.delta)
                    return (
                      <div key={m.user_id} className={styles.rankRow}>
                        <span className={styles.rankMedal}>{['🥇', '🥈', '🥉'][i]}</span>
                        <span className={styles.rankName}>{m.name}</span>
                        <span className={styles.rankScore}>{fmtPct(m.avg_score)}</span>
                        {delta && <span className={delta.className}>{delta.text}</span>}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {worstManagers.length > 0 && (
              <div className={styles.section}>
                <h2 className={styles.sectionTitle}>
                  Требуют внимания <span className={styles.sectionHint}>за последние 7 дней</span>
                </h2>
                <div className={styles.rankList}>
                  {worstManagers.map(m => {
                    const delta = fmtDelta(m.delta)
                    return (
                      <div key={m.user_id} className={styles.rankRow}>
                        <span className={styles.rankMedal}><IconAlert size={16} /></span>
                        <span className={styles.rankName}>{m.name}</span>
                        <span className={styles.rankScore}>{fmtPct(m.avg_score)}</span>
                        {delta && <span className={delta.className}>{delta.text}</span>}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            <div className={styles.section} style={{ gridColumn: '1 / -1' }}>
              <h2 className={styles.sectionTitle}>Навыки и соблюдение скрипта</h2>
              {!projectId ? (
                <div className={styles.empty}>Выберите проект в фильтре выше, чтобы увидеть разбивку по критериям — у разных проектов свои критерии оценки</div>
              ) : skills.length === 0 ? (
                <div className={styles.empty}>Нет оценённых звонков за этот период</div>
              ) : (
                <div className={styles.skillsRow}>
                  <ResponsiveContainer width="100%" height={260}>
                    <RadarChart data={skills.map(s => ({ name: s.name, value: Math.round(s.avg_score * 100) }))}>
                      <PolarGrid stroke="var(--border)" />
                      <PolarAngleAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                      <PolarRadiusAxis domain={[0, 100]} tick={{ fontSize: 9, fill: 'var(--text-faint)' }} />
                      <Radar dataKey="value" stroke="#ec4899" fill="#ec4899" fillOpacity={0.35} />
                      <Tooltip {...chartTooltipStyle} formatter={(v: number) => `${v}%`} />
                    </RadarChart>
                  </ResponsiveContainer>
                  <div className={styles.metricTable}>
                    {skills.map(m => (
                      <div key={m.metric_item_id} className={styles.metricRow}>
                        <span className={styles.metricName}>{m.name}</span>
                        <div className={styles.scoreBar}>
                          <div className={styles.scoreBarFill} style={{ width: `${m.avg_score * 100}%` }} />
                        </div>
                        <span className={styles.scoreVal}>{fmtPct(m.avg_score)}</span>
                        <span className={styles.callCnt}>{m.call_count} зв.</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Часто встречающиеся слова</h2>
              {keywords.length === 0 ? (
                <div className={styles.empty}>Нет транскрибаций за выбранный период</div>
              ) : (
                <div className={styles.keywordCloud}>
                  {keywords.map(k => (
                    <span
                      key={k.word}
                      className={styles.keywordChip}
                      style={{ fontSize: 11 + Math.min(k.count, 10) }}
                    >
                      {k.word} <span className={styles.keywordCount}>{k.count}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Распределение по длительности</h2>
              {buckets.every(b => b.call_count === 0) ? (
                <div className={styles.empty}>Нет данных за выбранный период</div>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
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
          </div>
        </>
      )}
    </div>
  )
}
