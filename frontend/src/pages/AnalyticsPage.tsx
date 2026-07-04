import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { Link } from 'react-router-dom'
import {
  getKpi, getTopErrors, getTopErrorCalls, getQualityDistribution, getManagersTrend, getKeywords,
  getDurationBuckets, getMetricSummary, getProjects, getManagers,
  Kpi, TopErrorItem, TopErrorCallItem, QualityDistribution, ManagerTrendItem, KeywordItem, DurationBucket, MetricSummary, Project, Manager,
} from '../api'
import { PieChart, Pie, Cell, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { IconTarget, IconTrend, IconAlert, IconPhoneWave } from '../components/icons'
import Avatar from '../components/Avatar'
import styles from './AnalyticsPage.module.css'

const QUALITY_COLORS = { high: '#34d399', medium: '#eab308', low: '#fb7185' }

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

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
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
  const [managers, setManagers] = useState<Manager[]>([])
  const [projectId, setProjectId] = useState('')
  const [managerId, setManagerId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const [kpi, setKpi] = useState<Kpi | null>(null)
  const [quality, setQuality] = useState<QualityDistribution | null>(null)
  const [topErrors, setTopErrors] = useState<TopErrorItem[]>([])
  const [managersTrend, setManagersTrend] = useState<ManagerTrendItem[]>([])
  const [keywords, setKeywords] = useState<KeywordItem[]>([])
  const [skills, setSkills] = useState<MetricSummary[]>([])
  const [buckets, setBuckets] = useState<DurationBucket[]>([])
  const [activeBucket, setActiveBucket] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [expandedError, setExpandedError] = useState<number | null>(null)
  const [errorCalls, setErrorCalls] = useState<Record<number, TopErrorCallItem[] | 'loading' | 'error'>>({})
  const [expandedSkill, setExpandedSkill] = useState<number | null>(null)
  const [skillCalls, setSkillCalls] = useState<Record<number, TopErrorCallItem[] | 'loading' | 'error'>>({})

  const requestIdRef = useRef(0)

  useEffect(() => {
    Promise.all([getProjects(true), getManagers()])
      .then(([p, m]) => { setProjects(p); setManagers(m) })
      .catch(() => {})
  }, [])

  // Cascade: once a project is picked, only offer managers who belong to it —
  // matches the pattern already used on the "Звонки" page.
  const managerOptions = useMemo(() => {
    if (!projectId) return managers
    const project = projects.find(p => String(p.id) === projectId)
    if (!project) return managers
    const memberIds = new Set(project.members.map(m => m.id))
    return managers.filter(m => memberIds.has(m.id))
  }, [managers, projects, projectId])

  function handleProjectChange(value: string) {
    setProjectId(value)
    if (value && managerId) {
      const project = projects.find(p => String(p.id) === value)
      if (project && !project.members.some(m => String(m.id) === managerId)) {
        setManagerId('')
      }
    }
  }

  const selectedManager = managerId ? managers.find(m => String(m.id) === managerId) ?? null : null

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    const requestId = ++requestIdRef.current
    const numericProjectId = projectId ? Number(projectId) : undefined
    const numericManagerId = managerId ? Number(managerId) : undefined
    const params = {
      projectId: numericProjectId, userId: numericManagerId,
      dateFrom: dateFrom || undefined, dateTo: dateTo || undefined,
    }

    const skillsPromise = numericProjectId
      ? getMetricSummary(numericProjectId, dateFrom || undefined, dateTo || undefined)
      : Promise.resolve([])

    Promise.all([
      getKpi(numericProjectId, numericManagerId),
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
  }, [projectId, managerId, dateFrom, dateTo])

  useEffect(() => { load() }, [load])

  // Reset drill-down state whenever the underlying filters change — a
  // previously expanded error's call list would otherwise silently show
  // stale results scoped to the old filter combination.
  useEffect(() => {
    setExpandedError(null)
    setErrorCalls({})
    setExpandedSkill(null)
    setSkillCalls({})
  }, [projectId, managerId, dateFrom, dateTo])

  function toggleError(metricItemId: number) {
    const next = expandedError === metricItemId ? null : metricItemId
    setExpandedError(next)
    if (next !== null && !errorCalls[next]) {
      setErrorCalls(prev => ({ ...prev, [next]: 'loading' }))
      getTopErrorCalls(next, {
        userId: managerId ? Number(managerId) : undefined,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
      }, 4)
        .then(calls => setErrorCalls(prev => ({ ...prev, [next]: calls })))
        .catch(() => setErrorCalls(prev => ({ ...prev, [next]: 'error' })))
    }
  }

  function toggleSkill(metricItemId: number) {
    const next = expandedSkill === metricItemId ? null : metricItemId
    setExpandedSkill(next)
    if (next !== null && !skillCalls[next]) {
      setSkillCalls(prev => ({ ...prev, [next]: 'loading' }))
      getTopErrorCalls(next, {
        userId: managerId ? Number(managerId) : undefined,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
      }, 4)
        .then(calls => setSkillCalls(prev => ({ ...prev, [next]: calls })))
        .catch(() => setSkillCalls(prev => ({ ...prev, [next]: 'error' })))
    }
  }

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
        <select className={styles.filterSelect} value={projectId} onChange={e => handleProjectChange(e.target.value)}>
          <option value="">Все проекты</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select className={styles.filterSelect} value={managerId} onChange={e => setManagerId(e.target.value)}>
          <option value="">Все менеджеры</option>
          {managerOptions.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        <input type="date" className={styles.filterDate} value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
        <span className={styles.dash}>—</span>
        <input type="date" className={styles.filterDate} value={dateTo} onChange={e => setDateTo(e.target.value)} />
        <span className={styles.filterNote}>Диапазон дат влияет на всё, кроме KPI и рейтинга менеджеров — те всегда за последние 7 дней</span>
      </div>

      {selectedManager && (
        <Link to={`/managers/${selectedManager.id}`} className={styles.managerBanner}>
          <Avatar name={selectedManager.name} size={32} />
          <span>Открыть полный профиль менеджера «{selectedManager.name}» — активность, пропуски, вся история звонков</span>
          <span className={styles.managerBannerArrow}>→</span>
        </Link>
      )}

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
            {!selectedManager && (
              <div className={styles.tile}>
                <span className={styles.tileIcon}><IconTrend size={18} /></span>
                <div>
                  <div className={styles.tileValue}>
                    {kpi.best_manager ? (
                      <Link to={`/managers/${kpi.best_manager.user_id}`} className={styles.tileLink}>
                        {kpi.best_manager.name}
                      </Link>
                    ) : '—'}
                  </div>
                  <div className={styles.tileLabel}>
                    Лучший менеджер недели{kpi.best_manager && ` — ${fmtPct(kpi.best_manager.avg_score)}`}
                  </div>
                </div>
              </div>
            )}
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
                  <div className={styles.donutWrap}>
                    <ResponsiveContainer width={220} height={220}>
                      <PieChart>
                        <Pie data={qualityData} dataKey="value" innerRadius={78} outerRadius={104} paddingAngle={3} cornerRadius={5} startAngle={90} endAngle={-270}>
                          {qualityData.map(d => (
                            <Cell key={d.key} fill={QUALITY_COLORS[d.key as keyof typeof QUALITY_COLORS]} stroke="none" />
                          ))}
                        </Pie>
                        <Tooltip {...chartTooltipStyle} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className={styles.donutCenter}>
                      <div className={styles.donutCenterValue}>{quality?.total}</div>
                      <div className={styles.donutCenterLabel}>звонков</div>
                    </div>
                  </div>
                  <div className={styles.donutLegend}>
                    {qualityData.map(d => (
                      <div key={d.key} className={styles.donutLegendRow}>
                        <span className={styles.donutDot} style={{ background: QUALITY_COLORS[d.key as keyof typeof QUALITY_COLORS] }} />
                        <span className={styles.donutLegendName}>{d.name}</span>
                        <span className={styles.donutCount}>{d.value}</span>
                        <span className={styles.donutPct}>
                          {quality?.total ? Math.round((d.value / quality.total) * 100) : 0}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>
                Частые ошибки{selectedManager ? ` — ${selectedManager.name}` : ' менеджеров'}
              </h2>
              {topErrors.length === 0 ? (
                <div className={styles.empty}>Нет данных за выбранный период</div>
              ) : (
                <div className={styles.errorList}>
                  {topErrors.map(e => {
                    const isOpen = expandedError === e.metric_item_id
                    const calls = errorCalls[e.metric_item_id]
                    return (
                      <div key={e.metric_item_id} className={styles.errorItem}>
                        <button
                          type="button"
                          className={styles.errorRow}
                          onClick={() => toggleError(e.metric_item_id)}
                          aria-expanded={isOpen}
                        >
                          <div className={styles.errorTop}>
                            <span className={styles.errorName}>
                              <span className={`${styles.errorChevron} ${isOpen ? styles.errorChevronOpen : ''}`}>▸</span>
                              {e.metric_name}
                              {!projectId && (
                                <Link to={`/projects/${e.project_id}`} className={styles.errorProject} onClick={ev => ev.stopPropagation()}>
                                  {' '}· {e.project_name}
                                </Link>
                              )}
                            </span>
                            <span className={styles.errorCount}>{e.fail_count} случаев</span>
                          </div>
                          <div className={styles.errorBarTrack}>
                            <div className={styles.errorBarFill} style={{ width: `${e.fail_rate * 100}%` }} />
                          </div>
                        </button>
                        {isOpen && (
                          <div className={styles.errorCalls}>
                            {calls === 'loading' || calls === undefined ? (
                              <div className={styles.errorCallsState}>Загрузка...</div>
                            ) : calls === 'error' ? (
                              <div className={styles.errorCallsState}>Не удалось загрузить звонки</div>
                            ) : calls.length === 0 ? (
                              <div className={styles.errorCallsState}>Звонки не найдены</div>
                            ) : (
                              <>
                                {calls.map(c => (
                                  <Link key={c.call_id} to={`/calls/${c.call_id}`} className={styles.errorCallRow}>
                                    <Avatar name={c.manager_name} size={22} />
                                    <span className={styles.errorCallManager}>{c.manager_name}</span>
                                    <span className={styles.errorCallDate}>{fmtDate(c.created_at)}</span>
                                    <span className={styles.errorCallArrow}>→</span>
                                  </Link>
                                ))}
                                {e.fail_count > calls.length && (
                                  <div className={styles.errorCallsState}>Показаны последние {calls.length} из {e.fail_count}</div>
                                )}
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {!selectedManager && (
              <div className={styles.section}>
                <h2 className={styles.sectionTitle}>
                  Топ менеджеров <span className={styles.sectionHint}>за последние 7 дней</span>
                </h2>
                {topManagers.length === 0 ? (
                  <div className={styles.empty}>Нет оценённых звонков за неделю</div>
                ) : (
                  <>
                    <div className={styles.rankList}>
                      {topManagers.map((m, i) => {
                        const delta = fmtDelta(m.delta)
                        return (
                          <Link to={`/managers/${m.user_id}`} key={m.user_id} className={styles.rankRow}>
                            <span className={styles.rankNum}>{i + 1}</span>
                            <span className={styles.rankName}>{m.name}</span>
                            <span className={styles.rankScore}>{fmtPct(m.avg_score)}</span>
                            {delta && <span className={delta.className}>{delta.text}</span>}
                          </Link>
                        )
                      })}
                    </div>
                    <Link to="/analytics/ranking" className={styles.showAllLink}>Показать всех менеджеров →</Link>
                  </>
                )}
              </div>
            )}

            {!selectedManager && worstManagers.length > 0 && (
              <div className={styles.section}>
                <h2 className={styles.sectionTitle}>
                  Требуют внимания <span className={styles.sectionHint}>за последние 7 дней</span>
                </h2>
                <div className={styles.rankList}>
                  {worstManagers.map(m => {
                    const delta = fmtDelta(m.delta)
                    return (
                      <Link to={`/managers/${m.user_id}`} key={m.user_id} className={styles.rankRow}>
                        <span className={styles.rankNum}><IconAlert size={14} /></span>
                        <span className={styles.rankName}>{m.name}</span>
                        <span className={styles.rankScore}>{fmtPct(m.avg_score)}</span>
                        {delta && <span className={delta.className}>{delta.text}</span>}
                      </Link>
                    )
                  })}
                </div>
              </div>
            )}

            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Навыки и соблюдение скрипта</h2>
              <p className={styles.sectionDesc}>Где менеджеры стабильно теряют баллы AI</p>
              {!projectId ? (
                <div className={styles.empty}>Выберите проект в фильтре, чтобы увидеть разбивку — у каждого свои критерии</div>
              ) : skills.length === 0 ? (
                <div className={styles.empty}>Нет оценённых звонков за этот период</div>
              ) : (
                <div className={styles.skillsRow}>
                  <ResponsiveContainer width="100%" height={170}>
                    <RadarChart data={skills.map(s => ({ name: s.name, value: Math.round(s.avg_score * 100) }))}>
                      <PolarGrid stroke="var(--border)" />
                      <PolarAngleAxis dataKey="name" tick={{ fontSize: 9, fill: 'var(--text-muted)' }} />
                      <PolarRadiusAxis domain={[0, 100]} tick={{ fontSize: 8, fill: 'var(--text-faint)' }} />
                      <Radar dataKey="value" stroke="#ec4899" fill="#ec4899" fillOpacity={0.35} />
                      <Tooltip {...chartTooltipStyle} formatter={(v: number) => `${v}%`} />
                    </RadarChart>
                  </ResponsiveContainer>
                  <div className={styles.metricTable}>
                    {skills.map(m => {
                      const isOpen = expandedSkill === m.metric_item_id
                      const calls = skillCalls[m.metric_item_id]
                      return (
                        <div key={m.metric_item_id} className={styles.errorItem}>
                          <button
                            type="button"
                            className={styles.metricRow}
                            onClick={() => toggleSkill(m.metric_item_id)}
                            aria-expanded={isOpen}
                          >
                            <span className={styles.metricName}>
                              <span className={`${styles.errorChevron} ${isOpen ? styles.errorChevronOpen : ''}`}>▸</span>
                              {m.name}
                            </span>
                            <div className={styles.scoreBar}>
                              <div className={styles.scoreBarFill} style={{ width: `${m.avg_score * 100}%` }} />
                            </div>
                            <span className={styles.scoreVal}>{fmtPct(m.avg_score)}</span>
                            <span className={styles.callCnt}>{m.call_count} зв.</span>
                          </button>
                          {isOpen && (
                            <div className={styles.errorCalls}>
                              {calls === 'loading' || calls === undefined ? (
                                <div className={styles.errorCallsState}>Загрузка...</div>
                              ) : calls === 'error' ? (
                                <div className={styles.errorCallsState}>Не удалось загрузить звонки</div>
                              ) : calls.length === 0 ? (
                                <div className={styles.errorCallsState}>Провалов по этому критерию не найдено</div>
                              ) : (
                                <>
                                  {calls.map(c => (
                                    <Link key={c.call_id} to={`/calls/${c.call_id}`} className={styles.errorCallRow}>
                                      <Avatar name={c.manager_name} size={22} />
                                      <span className={styles.errorCallManager}>{c.manager_name}</span>
                                      <span className={styles.errorCallDate}>{fmtDate(c.created_at)}</span>
                                      <span className={styles.errorCallArrow}>→</span>
                                    </Link>
                                  ))}
                                  {calls.length >= 4 && (
                                    <div className={styles.errorCallsState}>Показаны последние {calls.length}</div>
                                  )}
                                </>
                              )}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>

            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Часто встречающиеся слова</h2>
              <p className={styles.sectionDesc}>Что чаще всего звучит в разговорах с клиентами, по транскрибации</p>
              {keywords.length === 0 ? (
                <div className={styles.empty}>Нет транскрибаций за выбранный период</div>
              ) : (
                <div className={styles.keywordList}>
                  {keywords.slice(0, 8).map(k => (
                    <div key={k.word} className={styles.keywordRow}>
                      <span className={styles.keywordWord}>{k.word}</span>
                      <div className={styles.keywordBarTrack}>
                        <div
                          className={styles.keywordBarFill}
                          style={{ width: `${(k.count / keywords[0].count) * 100}%` }}
                        />
                      </div>
                      <span className={styles.keywordCount}>{k.count}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Распределение по длительности</h2>
              {buckets.every(b => b.call_count === 0) ? (
                <div className={styles.empty}>Нет данных за выбранный период</div>
              ) : (
                <div className={styles.durationChartWrap}>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={buckets} barCategoryGap="45%">
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                      <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} stroke="var(--border)" />
                      <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} stroke="var(--border)" width={28} />
                      <Tooltip {...chartTooltipStyle} cursor={false} />
                      <Bar
                        dataKey="call_count"
                        name="Звонков"
                        radius={[3, 3, 0, 0]}
                        maxBarSize={22}
                        onMouseEnter={(_, idx) => setActiveBucket(idx)}
                        onMouseLeave={() => setActiveBucket(null)}
                      >
                        {buckets.map((b, i) => (
                          <Cell
                            key={b.label}
                            fill="#6366f1"
                            style={{
                              filter: activeBucket === i
                                ? 'brightness(1.4) drop-shadow(0 0 6px rgba(99,102,241,0.7))'
                                : 'none',
                              transform: activeBucket === i ? 'scaleY(1.04)' : 'scaleY(1)',
                              transformOrigin: 'bottom center',
                              transformBox: 'fill-box',
                              transition: 'transform 0.15s ease, filter 0.15s ease',
                              cursor: 'pointer',
                            }}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
