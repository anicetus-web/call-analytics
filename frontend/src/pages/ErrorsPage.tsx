import { useEffect, useState, useMemo, useRef } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  getTopErrors, getTopErrorManagers, getTopErrorCalls, getManagers, getManagerErrorSummary,
  TopErrorItem, ErrorManagerItem, TopErrorCallItem, Manager, ManagerErrorSummary,
} from '../api'
import Avatar from '../components/Avatar'
import { IconSearch } from '../components/icons'
import styles from './ErrorsPage.module.css'

export type Period = 'today' | 'yesterday' | '7d' | '30d' | 'custom'
const PERIOD_KEYS: Period[] = ['today', 'yesterday', '7d', '30d', 'custom']

function periodRange(period: Period, customFrom: string, customTo: string): { dateFrom?: string; dateTo?: string } {
  const fmt = (d: Date) => d.toISOString().slice(0, 10)
  const today = new Date()
  switch (period) {
    case 'today':
      return { dateFrom: fmt(today), dateTo: fmt(today) }
    case 'yesterday': {
      const y = new Date(today); y.setDate(y.getDate() - 1)
      return { dateFrom: fmt(y), dateTo: fmt(y) }
    }
    case '7d': {
      const from = new Date(today); from.setDate(from.getDate() - 6)
      return { dateFrom: fmt(from), dateTo: fmt(today) }
    }
    case '30d': {
      const from = new Date(today); from.setDate(from.getDate() - 29)
      return { dateFrom: fmt(from), dateTo: fmt(today) }
    }
    case 'custom':
      return { dateFrom: customFrom || undefined, dateTo: customTo || undefined }
  }
}

function DrillDownSkeleton() {
  return (
    <>
      {[0, 1].map(i => (
        <div key={i} className={styles.callSkeleton}>
          <span className={styles.skeletonAvatar} />
          <span className={styles.skeletonLine} style={{ width: '60%' }} />
        </div>
      ))}
    </>
  )
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function CallDrillDown({ calls }: { calls: TopErrorCallItem[] | 'loading' | 'error' | undefined }) {
  if (calls === 'loading' || calls === undefined) return <DrillDownSkeleton />
  if (calls === 'error') return <div className={styles.emptySmall}>Не удалось загрузить звонки</div>
  if (calls.length === 0) return <div className={styles.emptySmall}>Звонки не найдены</div>
  return (
    <>
      {calls.map(c => (
        <Link to={`/calls/${c.call_id}`} key={c.call_id} className={styles.callRow}>
          <Avatar name={c.manager_name} size={24} />
          <span className={styles.callManager}>{c.manager_name}</span>
          <span className={styles.callMeta}>{fmtDate(c.created_at)}</span>
          <span className={styles.callArrow}>→</span>
        </Link>
      ))}
    </>
  )
}

// ── Tab 1: Топ ошибок ──────────────────────────────────────────────────────

export function TopErrorsTab({ dateFrom, dateTo, projectId, userId, limit = 5, showAllButton = true }: {
  dateFrom?: string; dateTo?: string; projectId?: number; userId?: number; limit?: number; showAllButton?: boolean
}) {
  const [errors, setErrors] = useState<TopErrorItem[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [managersByError, setManagersByError] = useState<Record<number, ErrorManagerItem[] | 'loading' | 'error'>>({})
  const [callsByError, setCallsByError] = useState<Record<number, TopErrorCallItem[] | 'loading' | 'error'>>({})
  const [search, setSearch] = useState('')
  const [showAll, setShowAll] = useState<Record<number, boolean>>({})
  const [errorsExpanded, setErrorsExpanded] = useState(false)
  const requestIdRef = useRef(0)

  useEffect(() => {
    setLoading(true)
    const requestId = ++requestIdRef.current
    setExpanded(null)
    setManagersByError({})
    setCallsByError({})
    setShowAll({})
    setErrorsExpanded(false)
    getTopErrors({ dateFrom, dateTo, projectId, userId }, limit)
      .then(data => { if (requestId === requestIdRef.current) setErrors(data) })
      .finally(() => { if (requestId === requestIdRef.current) setLoading(false) })
  }, [dateFrom, dateTo, projectId, userId, limit])

  function showAllErrors() {
    setErrorsExpanded(true)
    setLoading(true)
    const requestId = ++requestIdRef.current
    getTopErrors({ dateFrom, dateTo, projectId, userId }, 100)
      .then(data => { if (requestId === requestIdRef.current) setErrors(data) })
      .finally(() => { if (requestId === requestIdRef.current) setLoading(false) })
  }

  function toggle(e: TopErrorItem) {
    const id = e.metric_item_id
    const next = expanded === id ? null : id
    setExpanded(next)
    setSearch('')
    if (next !== null) {
      if (!managersByError[id]) {
        setManagersByError(prev => ({ ...prev, [id]: 'loading' }))
        getTopErrorManagers(id, { dateFrom, dateTo, projectId })
          .then(data => setManagersByError(prev => ({ ...prev, [id]: data })))
          .catch(() => setManagersByError(prev => ({ ...prev, [id]: 'error' })))
      }
      if (!callsByError[id]) {
        setCallsByError(prev => ({ ...prev, [id]: 'loading' }))
        getTopErrorCalls(id, { userId, dateFrom, dateTo }, 4)
          .then(data => setCallsByError(prev => ({ ...prev, [id]: data })))
          .catch(() => setCallsByError(prev => ({ ...prev, [id]: 'error' })))
      }
    }
  }

  if (loading) return <div className={styles.state}>Загрузка…</div>
  if (errors.length === 0) return <div className={styles.empty}>Нет ошибок за выбранный период</div>

  return (
    <div className={styles.errorList}>
      {errors.map(e => {
        const id = e.metric_item_id
        const isOpen = expanded === id
        const managers = managersByError[id]
        const calls = callsByError[id]
        const filteredManagers = Array.isArray(managers)
          ? managers.filter(m => m.name.toLowerCase().includes(search.toLowerCase()))
          : []
        const visibleManagers = showAll[id] ? filteredManagers : filteredManagers.slice(0, 5)
        return (
          <div key={id} className={styles.errorCard}>
            <button type="button" className={styles.errorCardHead} onClick={() => toggle(e)} aria-expanded={isOpen}>
              <span className={`${styles.chevron} ${isOpen ? styles.chevronOpen : ''}`}>▸</span>
              <span className={styles.errorName}>{e.metric_name}</span>
              <span className={styles.errorProject}>{e.project_name}</span>
              <span className={styles.errorCount}>{e.fail_count} случаев</span>
            </button>
            {isOpen && (
              <div className={styles.errorDetail}>
                <div className={styles.detailCalls}>
                  <span className={styles.detailLabel}>Примеры звонков</span>
                  <CallDrillDown calls={calls} />
                </div>
                <div className={styles.detailManagers}>
                  <span className={styles.detailLabel}>Кто чаще всего допускает эту ошибку</span>
                  <div className={styles.searchWrap}>
                    <IconSearch size={15} className={styles.searchIcon} />
                    <input
                      type="text"
                      className={styles.searchInput}
                      placeholder="Поиск менеджера…"
                      value={search}
                      onChange={ev => setSearch(ev.target.value)}
                    />
                  </div>
                  {managers === 'loading' || managers === undefined ? (
                    <div className={styles.emptySmall}>Загрузка…</div>
                  ) : managers === 'error' ? (
                    <div className={styles.emptySmall}>Не удалось загрузить</div>
                  ) : filteredManagers.length === 0 ? (
                    <div className={styles.emptySmall}>Менеджеры не найдены</div>
                  ) : (
                    <>
                      <div className={styles.managerRankList}>
                        {visibleManagers.map((m, i) => (
                          <Link to={`/managers/${m.user_id}`} key={m.user_id} className={styles.managerRankRow}>
                            <span className={styles.managerRankNum}>{i + 1}</span>
                            <Avatar name={m.name} size={22} />
                            <span className={styles.managerRankName}>{m.name}</span>
                            <span className={styles.managerRankCount}>{m.fail_count}</span>
                          </Link>
                        ))}
                      </div>
                      {!showAll[id] && filteredManagers.length > 5 && (
                        <button type="button" className={styles.showAllBtn} onClick={() => setShowAll(prev => ({ ...prev, [id]: true }))}>
                          Показать всех менеджеров ({filteredManagers.length})
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        )
      })}
      {showAllButton && !errorsExpanded && errors.length === limit && (
        <button type="button" className={styles.showAllBtn} onClick={showAllErrors}>
          Показать все ошибки
        </button>
      )}
    </div>
  )
}

// ── Tab 2: Ошибки менеджеров ────────────────────────────────────────────────

export function ManagerErrorsTab({ dateFrom, dateTo, projectId, compact = false, initialManagerId }: {
  dateFrom?: string; dateTo?: string; projectId?: number; compact?: boolean; initialManagerId?: number
}) {
  const [managers, setManagers] = useState<Manager[]>([])
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(initialManagerId ?? null)
  const [summary, setSummary] = useState<ManagerErrorSummary | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [errorsExpanded, setErrorsExpanded] = useState(false)
  const [expandedErr, setExpandedErr] = useState<number | null>(null)
  const [callsByError, setCallsByError] = useState<Record<number, TopErrorCallItem[] | 'loading' | 'error'>>({})
  const requestIdRef = useRef(0)

  useEffect(() => { getManagers().then(setManagers).catch(() => {}) }, [])

  const filtered = useMemo(
    () => managers.filter(m => m.name.toLowerCase().includes(search.toLowerCase())),
    [managers, search],
  )

  useEffect(() => {
    if (selectedId === null) { setSummary(null); return }
    setSummaryLoading(true)
    const requestId = ++requestIdRef.current
    setExpandedErr(null)
    setCallsByError({})
    setErrorsExpanded(false)
    getManagerErrorSummary(selectedId, { dateFrom, dateTo, projectId }, 5)
      .then(data => { if (requestId === requestIdRef.current) setSummary(data) })
      .finally(() => { if (requestId === requestIdRef.current) setSummaryLoading(false) })
  }, [selectedId, dateFrom, dateTo, projectId])

  function showAllErrors() {
    if (selectedId === null) return
    setErrorsExpanded(true)
    setSummaryLoading(true)
    const requestId = ++requestIdRef.current
    getManagerErrorSummary(selectedId, { dateFrom, dateTo, projectId }, 100)
      .then(data => { if (requestId === requestIdRef.current) setSummary(data) })
      .finally(() => { if (requestId === requestIdRef.current) setSummaryLoading(false) })
  }

  function toggleErr(metricItemId: number) {
    const next = expandedErr === metricItemId ? null : metricItemId
    setExpandedErr(next)
    if (next !== null && !callsByError[next]) {
      setCallsByError(prev => ({ ...prev, [next]: 'loading' }))
      getTopErrorCalls(next, { userId: selectedId ?? undefined, dateFrom, dateTo }, 4)
        .then(data => setCallsByError(prev => ({ ...prev, [next]: data })))
        .catch(() => setCallsByError(prev => ({ ...prev, [next]: 'error' })))
    }
  }

  return (
    <div className={compact ? styles.managersTabStack : styles.managersTabGrid}>
      <div className={styles.managerPicker}>
        <div className={styles.searchWrap}>
          <IconSearch size={14} className={styles.searchIcon} />
          <input
            type="text"
            className={styles.searchInput}
            placeholder="Поиск менеджера…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <div className={compact ? styles.managerPickerListCompact : styles.managerPickerList}>
          {filtered.map(m => (
            <button
              key={m.id}
              type="button"
              className={`${styles.managerPickerRow} ${selectedId === m.id ? styles.managerPickerRowActive : ''}`}
              onClick={() => setSelectedId(prev => prev === m.id ? null : m.id)}
            >
              <Avatar name={m.name} size={26} />
              <span>{m.name}</span>
            </button>
          ))}
          {filtered.length === 0 && <div className={styles.emptySmall}>Менеджеры не найдены</div>}
        </div>
      </div>

      <div className={styles.managerCard}>
        {selectedId === null ? (
          <div className={styles.empty}>Выберите менеджера слева, чтобы увидеть его ошибки</div>
        ) : summaryLoading || !summary ? (
          <div className={styles.state}>Загрузка…</div>
        ) : (
          <>
            <div className={styles.managerCardHead}>
              <Avatar name={summary.name} size={40} />
              <div>
                <div className={styles.managerCardName}>{summary.name}</div>
                <div className={styles.managerCardMeta}>
                  Диалогов: {summary.call_count} · Всего ошибок: {summary.total_errors}{compact ? ' · топ-5' : ''}
                </div>
              </div>
            </div>
            {summary.top_errors.length === 0 ? (
              <div className={styles.empty}>Ошибок не найдено за выбранный период</div>
            ) : (
              <div className={styles.errorList}>
                {summary.top_errors.map(e => {
                  const isOpen = expandedErr === e.metric_item_id
                  const calls = callsByError[e.metric_item_id]
                  return (
                    <div key={e.metric_item_id} className={styles.errorCard}>
                      <button type="button" className={styles.errorCardHead} onClick={() => toggleErr(e.metric_item_id)} aria-expanded={isOpen}>
                        <span className={`${styles.chevron} ${isOpen ? styles.chevronOpen : ''}`}>▸</span>
                        <span className={styles.errorName}>{e.metric_name}</span>
                        <span className={styles.errorCount}>{e.fail_count}</span>
                      </button>
                      {isOpen && (
                        <div className={styles.detailCalls}>
                          <CallDrillDown calls={calls} />
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
            {!compact && !errorsExpanded && summary.top_errors.length === 5 && (
              <button type="button" className={styles.showAllBtn} onClick={showAllErrors}>
                Показать все ошибки
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────

const PERIODS: { key: Period; label: string }[] = [
  { key: 'today', label: 'Сегодня' },
  { key: 'yesterday', label: 'Вчера' },
  { key: '7d', label: 'Последние 7 дней' },
  { key: '30d', label: 'Последние 30 дней' },
  { key: 'custom', label: 'Диапазон' },
]

export default function ErrorsPage() {
  const [searchParams] = useSearchParams()
  const initialTab = searchParams.get('tab') === 'managers' ? 'managers' : 'top'
  const [tab, setTab] = useState<'top' | 'managers'>(initialTab)
  const periodParam = searchParams.get('period')
  const initialPeriod: Period = periodParam && (PERIOD_KEYS as string[]).includes(periodParam) ? periodParam as Period : '7d'
  const [period, setPeriod] = useState<Period>(initialPeriod)
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const managerIdParam = searchParams.get('manager_id')
  const initialManagerId = managerIdParam ? Number(managerIdParam) : undefined

  const { dateFrom, dateTo } = periodRange(period, customFrom, customTo)

  return (
    <div>
      <Link to="/analytics" className={styles.breadcrumb}>← Аналитика</Link>

      <div className={styles.header}>
        <h1 className={styles.title}>Ошибки</h1>
        <p className={styles.subtitle}>Какие ошибки чаще всего допускают менеджеры — по компании и по каждому лично</p>
      </div>

      <div className={styles.periodRow}>
        {PERIODS.map(p => (
          <button
            key={p.key}
            type="button"
            className={period === p.key ? styles.periodBtnActive : styles.periodBtn}
            onClick={() => setPeriod(p.key)}
          >
            {p.label}
          </button>
        ))}
        {period === 'custom' && (
          <>
            <input type="date" className={styles.filterDate} value={customFrom} onChange={e => setCustomFrom(e.target.value)} />
            <span className={styles.dash}>—</span>
            <input type="date" className={styles.filterDate} value={customTo} onChange={e => setCustomTo(e.target.value)} />
          </>
        )}
      </div>

      <div className={styles.tabsRow}>
        <button type="button" className={tab === 'top' ? styles.tabActive : styles.tab} onClick={() => setTab('top')}>
          Топ ошибок
        </button>
        <button type="button" className={tab === 'managers' ? styles.tabActive : styles.tab} onClick={() => setTab('managers')}>
          Ошибки менеджеров
        </button>
      </div>

      {tab === 'top' ? <TopErrorsTab dateFrom={dateFrom} dateTo={dateTo} /> : <ManagerErrorsTab dateFrom={dateFrom} dateTo={dateTo} initialManagerId={initialManagerId} />}
    </div>
  )
}
