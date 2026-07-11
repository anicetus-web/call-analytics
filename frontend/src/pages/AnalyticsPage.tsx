import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { Link } from 'react-router-dom'
import {
  getKpi, getTopErrorCalls, getManagersTrend,
  getMetricSummary, getProjects, getManagers,
  Kpi, TopErrorCallItem, ManagerTrendItem, MetricSummary, Project, Manager,
} from '../api'
import { IconTarget, IconTrend, IconAlert, IconPhoneWave } from '../components/icons'
import Avatar from '../components/Avatar'
import { TopErrorsTab, ManagerErrorsTab } from './ErrorsPage'
import styles from './AnalyticsPage.module.css'

const QUALITY_COLORS = { high: '#34d399', medium: '#eab308', low: '#fb7185' }

function scoreTierColor(avgScore: number): string {
  if (avgScore >= 0.8) return QUALITY_COLORS.high
  if (avgScore >= 0.5) return QUALITY_COLORS.medium
  return QUALITY_COLORS.low
}

interface SkillGroup {
  id: number
  name: string
  groupType: MetricSummary['metric_group_type']
  items: MetricSummary[]
}

// Split the flat metric list into one block per metric group (already sorted
// group-then-position by the backend), so each group reads separately.
function groupMetrics(metrics: MetricSummary[]): SkillGroup[] {
  const blocks: SkillGroup[] = []
  const byId = new Map<number, SkillGroup>()
  for (const m of metrics) {
    let block = byId.get(m.metric_group_id)
    if (!block) {
      block = { id: m.metric_group_id, name: m.metric_group_name, groupType: m.metric_group_type, items: [] }
      byId.set(m.metric_group_id, block)
      blocks.push(block)
    }
    block.items.push(m)
  }
  return blocks
}

function fmtPct(v: number): string {
  return `${Math.round(v * 100)}%`
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function fmtCallDuration(sec: number | null): string {
  if (!sec) return '—'
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

// Scores are one of {0, 0.5} in this drill-down (the endpoint only ever
// returns calls that failed, i.e. score < 1.0) — a plain 0/50 percentage
// on its own doesn't say whether that's "missed entirely" or "partial
// credit", so spell it out.
function scoreBadge(score: number): { text: string; className: string } {
  return score === 0
    ? { text: 'Не выполнено', className: styles.badgeFail }
    : { text: 'Частично · 50%', className: styles.badgePartial }
}

function DrillDownCallRow({ call }: { call: TopErrorCallItem }) {
  const badge = scoreBadge(call.score)
  return (
    <Link to={`/calls/${call.call_id}`} className={styles.errorCallRow}>
      <Avatar name={call.manager_name} size={26} />
      <div className={styles.errorCallMain}>
        <span className={styles.errorCallManager}>{call.manager_name}</span>
        <span className={styles.errorCallMeta}>
          {fmtDate(call.created_at)} · {fmtCallDuration(call.duration_seconds)}
        </span>
      </div>
      <span className={`${styles.errorCallBadge} ${badge.className}`}>{badge.text}</span>
      <span className={styles.errorCallArrow}>→</span>
    </Link>
  )
}

function DrillDownSkeleton() {
  return (
    <>
      {[0, 1].map(i => (
        <div key={i} className={styles.errorCallSkeleton}>
          <span className={styles.skeletonAvatar} />
          <div className={styles.errorCallMain}>
            <span className={styles.skeletonLine} style={{ width: '55%' }} />
            <span className={styles.skeletonLine} style={{ width: '35%' }} />
          </div>
          <span className={styles.skeletonBadge} />
        </div>
      ))}
    </>
  )
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
  const [managersTrend, setManagersTrend] = useState<ManagerTrendItem[]>([])
  const [skills, setSkills] = useState<MetricSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [expandedSkill, setExpandedSkill] = useState<number | null>(null)
  const [skillCalls, setSkillCalls] = useState<Record<number, TopErrorCallItem[] | 'loading' | 'error'>>({})

  const requestIdRef = useRef(0)
  const qualityRef = useRef<HTMLDivElement>(null)
  const errorsRef = useRef<HTMLDivElement>(null)
  const managersRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    Promise.all([getProjects(true), getManagers()])
      .then(([p, m]) => {
        setProjects(p)
        setManagers(m)
        // Analytics is scoped per project (criteria/metric groups differ between
        // projects, so a blended "all projects" view doesn't mean much) — default
        // to the first project instead of an all-projects option. Future projects
        // just show up as additional options here automatically.
        setProjectId(prev => prev || (p[0] ? String(p[0].id) : ''))
      })
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

    const skillsPromise = numericProjectId
      ? getMetricSummary(numericProjectId, dateFrom || undefined, dateTo || undefined)
      : Promise.resolve([])

    Promise.all([
      getKpi(numericProjectId, numericManagerId),
      getManagersTrend(numericProjectId),
      skillsPromise,
    ])
      .then(([kp, mt, sk]) => {
        if (requestId !== requestIdRef.current) return
        setKpi(kp)
        setManagersTrend(mt)
        setSkills(sk)
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
  // previously expanded skill's call list would otherwise silently show
  // stale results scoped to the old filter combination.
  useEffect(() => {
    setExpandedSkill(null)
    setSkillCalls({})
  }, [projectId, managerId, dateFrom, dateTo])

  function scrollToManagers() {
    managersRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function handleMainProblemClick() {
    if (!kpi?.main_problem) return
    qualityRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
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
        <select className={styles.filterSelect} aria-label="Проект" value={projectId} onChange={e => handleProjectChange(e.target.value)}>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select className={styles.filterSelect} aria-label="Менеджер" value={managerId} onChange={e => setManagerId(e.target.value)}>
          <option value="">Все менеджеры</option>
          {managerOptions.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        <input type="date" className={styles.filterDate} aria-label="Дата от" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
        <span className={styles.dash}>—</span>
        <input type="date" className={styles.filterDate} aria-label="Дата до" value={dateTo} onChange={e => setDateTo(e.target.value)} />
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
        <div className={styles.state}>Загрузка…</div>
      ) : error ? (
        <div className={`${styles.state} ${styles.error}`}>{error}</div>
      ) : !kpi ? null : (
        <>
          <div className={styles.tiles}>
            <button type="button" className={`${styles.tile} ${styles.tileClickable}`} onClick={scrollToManagers}>
              <span className={styles.tileIcon}><IconTarget size={18} /></span>
              <div>
                <div className={styles.tileValue}>
                  {fmtPct(kpi.avg_score)}
                  {scoreDelta && <span className={scoreDelta.className}> {scoreDelta.text}</span>}
                </div>
                <div className={styles.tileLabel}>Средняя оценка AI за неделю</div>
                <div className={styles.tileHint}>Смотреть по менеджерам →</div>
              </div>
            </button>
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
            <button
              type="button"
              className={`${styles.tile} ${styles.tileClickable}`}
              onClick={handleMainProblemClick}
              disabled={!kpi.main_problem}
            >
              <span className={styles.tileIcon}><IconAlert size={18} /></span>
              <div>
                <div className={styles.tileValue}>
                  {kpi.main_problem ? `${kpi.main_problem.fail_count} случаев` : '—'}
                </div>
                <div className={styles.tileLabel}>
                  {kpi.main_problem ? `${kpi.main_problem.metric_name} · за 7 дней` : 'Основная проблема за неделю'}
                </div>
                {kpi.main_problem && <div className={styles.tileHint}>Показать эти звонки →</div>}
              </div>
            </button>
            <Link to="/calls" className={`${styles.tile} ${styles.tileClickable}`}>
              <span className={styles.tileIcon}><IconPhoneWave size={18} /></span>
              <div>
                <div className={styles.tileValue}>{kpi.calls_analyzed}</div>
                <div className={styles.tileLabel}>Звонков оценено AI за неделю</div>
                <div className={styles.tileHint}>Открыть все звонки →</div>
              </div>
            </Link>
          </div>

          <div className={styles.grid}>
            <div className={`${styles.section} ${styles.sectionAccentPink}`} ref={qualityRef}>
              <h2 className={styles.sectionTitle}>Топ ошибок</h2>
              <TopErrorsTab dateFrom={dateFrom || undefined} dateTo={dateTo || undefined} projectId={projectId ? Number(projectId) : undefined} userId={managerId ? Number(managerId) : undefined} showAllButton={false} />
              <Link to="/analytics/errors?tab=top" className={styles.jumpToManagersBtn}>Перейти к топ ошибкам →</Link>
            </div>

            <div className={`${styles.section} ${styles.sectionAccentBlue}`} ref={errorsRef}>
              <h2 className={styles.sectionTitle}>Ошибки менеджеров</h2>
              <ManagerErrorsTab dateFrom={dateFrom || undefined} dateTo={dateTo || undefined} projectId={projectId ? Number(projectId) : undefined} compact />
              <Link to="/analytics/errors?tab=managers" className={styles.jumpToManagersBtnBlue}>Перейти к ошибкам менеджеров →</Link>
            </div>

            {!selectedManager && (
              <div className={`${styles.section} ${styles.sectionAccentPink}`} ref={managersRef}>
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
          </div>

          <div className={styles.section} style={{ marginTop: 16 }}>
            <h2 className={styles.sectionTitle}>Навыки и соблюдение скрипта</h2>
            <p className={styles.sectionDesc}>Где менеджеры стабильно теряют баллы AI</p>
            {!projectId ? (
              <div className={styles.empty}>Выберите проект в фильтре, чтобы увидеть разбивку — у каждого свои критерии</div>
            ) : skills.length === 0 ? (
              <div className={styles.empty}>Нет оценённых звонков за этот период</div>
            ) : (() => {
              const allGroups = groupMetrics(skills)
              const rightGroups = allGroups.filter(g => g.groupType === 'forbidden_keywords')
              const leftGroups = allGroups.filter(g => g.groupType !== 'forbidden_keywords')

              const renderGroup = (group: SkillGroup) => {
                const groupAvg = group.items.reduce((s, i) => s + i.avg_score, 0) / group.items.length
                return (
                  <div key={group.id} className={styles.skillGroup}>
                    <div className={styles.skillGroupHead}>
                      <span className={styles.skillGroupName}>{group.name}</span>
                      <span className={styles.skillGroupScore} style={{ color: scoreTierColor(groupAvg) }}>
                        {Math.round(groupAvg * 100)}%
                      </span>
                    </div>
                    <div className={styles.skillCardGrid}>
                      {group.items.map(m => {
                        const isOpen = expandedSkill === m.metric_item_id
                        const pct = Math.round(m.avg_score * 100)
                        return (
                          <button
                            key={m.metric_item_id}
                            type="button"
                            className={`${styles.skillCard} ${isOpen ? styles.skillCardOpen : ''}`}
                            onClick={() => toggleSkill(m.metric_item_id)}
                            aria-expanded={isOpen}
                          >
                            <div className={styles.scoreRingWrapLg}>
                              <div
                                className={styles.scoreRing}
                                style={{ background: `conic-gradient(${scoreTierColor(m.avg_score)} ${pct * 3.6}deg, var(--bg-hover) 0deg)` }}
                              />
                              <span className={styles.scoreRingValue}>{pct}%</span>
                            </div>
                            <span className={styles.skillCardName}>{m.name}</span>
                            <span className={styles.skillCardCnt}>{m.call_count} зв.</span>
                          </button>
                        )
                      })}
                    </div>
                    {group.items.map(m => {
                      const isOpen = expandedSkill === m.metric_item_id
                      if (!isOpen) return null
                      const calls = skillCalls[m.metric_item_id]
                      return (
                        <div key={m.metric_item_id} className={styles.errorCalls}>
                          <div className={styles.skillCallsLabel}>{m.name}</div>
                          {calls === 'loading' || calls === undefined ? (
                            <DrillDownSkeleton />
                          ) : calls === 'error' ? (
                            <div className={styles.errorCallsState}>Не удалось загрузить звонки</div>
                          ) : calls.length === 0 ? (
                            <div className={styles.errorCallsState}>Провалов по этому критерию не найдено</div>
                          ) : (
                            <>
                              {calls.map(c => <DrillDownCallRow key={c.call_id} call={c} />)}
                              {calls.length >= 4 && (
                                <div className={styles.errorCallsState}>Показаны последние {calls.length}</div>
                              )}
                            </>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )
              }

              return (
                <div className={rightGroups.length > 0 ? styles.skillsSplit : styles.skillsRow}>
                  <div className={styles.skillsRow}>{leftGroups.map(renderGroup)}</div>
                  {rightGroups.length > 0 && (
                    <div className={styles.skillsRowRight}>{rightGroups.map(renderGroup)}</div>
                  )}
                </div>
              )
            })()}
          </div>
        </>
      )}
    </div>
  )
}
