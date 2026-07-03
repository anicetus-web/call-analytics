import { useEffect, useState, useCallback, FormEvent } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  getProject, getCalls, getMetricSummary, getManagerSummary, getTimeline,
  getManagerScoreTimeline,
  updateProject, archiveProject, addMember, removeMember, getManagers,
  getMetricGroups, createMetricGroup, updateMetricGroup, deleteMetricGroup,
  createMetricItem, updateMetricItem, deleteMetricItem,
  Project, CallListItem, MetricSummary, ManagerSummary, TimelinePoint,
  Manager, MetricGroup, MetricGroupType,
} from '../api'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import Modal from '../components/Modal'
import Avatar from '../components/Avatar'
import { IconPlus } from '../components/icons'
import styles from './ProjectDetailPage.module.css'
import formStyles from '../components/Form.module.css'

const TIME_PRESETS = [
  { key: 'week', label: 'Последняя неделя' },
  { key: 'today', label: 'Сегодня' },
  { key: 'yesterday', label: 'Вчера' },
  { key: 'month', label: 'Последний месяц' },
  { key: 'year', label: 'Последний год' },
  { key: 'all', label: 'Всё время' },
] as const
type TimePreset = typeof TIME_PRESETS[number]['key']

function presetRange(preset: TimePreset): { dateFrom?: string; dateTo?: string } {
  const iso = (d: Date) => d.toISOString().slice(0, 10)
  const today = new Date()
  switch (preset) {
    case 'today':
      return { dateFrom: iso(today) }
    case 'yesterday': {
      const d = new Date(today); d.setDate(d.getDate() - 1)
      return { dateFrom: iso(d), dateTo: iso(d) }
    }
    case 'week': {
      const d = new Date(today); d.setDate(d.getDate() - 6)
      return { dateFrom: iso(d) }
    }
    case 'month': {
      const d = new Date(today); d.setDate(d.getDate() - 29)
      return { dateFrom: iso(d) }
    }
    case 'year': {
      const d = new Date(today); d.setDate(d.getDate() - 364)
      return { dateFrom: iso(d) }
    }
    case 'all':
    default:
      return {}
  }
}

type Tab = 'calls' | 'analytics' | 'settings'

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
  converting: '#6366f1',
  transcribing: '#8b5cf6',
  analyzing: '#f59e0b',
  done: '#10b981',
  error: '#ef4444',
}

const GROUP_TYPE_LABELS: Record<MetricGroupType, string> = {
  required_keywords: 'Обязательные фразы',
  forbidden_keywords: 'Запрещённые фразы',
  script_stages: 'Этапы скрипта',
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
  const navigate = useNavigate()

  const [project, setProject] = useState<Project | null>(null)
  const [tab, setTab] = useState<Tab>('calls')
  const [calls, setCalls] = useState<CallListItem[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [offset, setOffset] = useState(0)
  const [metrics, setMetrics] = useState<MetricSummary[]>([])
  const [managers, setManagers] = useState<ManagerSummary[]>([])
  const [timeline, setTimeline] = useState<TimelinePoint[]>([])
  const [timeRange, setTimeRange] = useState<TimePreset>('week')
  const [timelineManagerId, setTimelineManagerId] = useState('')
  const [timelineLoading, setTimelineLoading] = useState(true)
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

  const loadProject = useCallback(() => getProject(projectId).then(setProject), [projectId])

  // Used to refresh project data after a mutation in the Settings tab (fire-and-forget
  // from the caller's perspective). Unlike loadProject() used in the initial-load
  // Promise.all below, failures here must not become unhandled rejections — if the
  // refetch fails after a successful save, the panel just keeps showing pre-mutation
  // data instead of a jarring page-level error.
  const refreshProject = useCallback(() => {
    loadProject().catch(() => {})
  }, [loadProject])

  useEffect(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      loadProject(),
      loadCalls(0),
      getMetricSummary(projectId).then(setMetrics),
      getManagerSummary(projectId).then(setManagers),
    ])
      .catch(() => setError('Не удалось загрузить данные проекта'))
      .finally(() => setLoading(false))
  }, [projectId, loadCalls, loadProject])

  // "Средний балл по дням" has its own filters (period + optional manager), so
  // it reloads independently of the rest of the Analytics tab.
  const loadTimeline = useCallback(() => {
    setTimelineLoading(true)
    const { dateFrom, dateTo } = presetRange(timeRange)
    const promise = timelineManagerId
      ? getManagerScoreTimeline(Number(timelineManagerId), { projectId, dateFrom, dateTo })
      : getTimeline(projectId, dateFrom, dateTo)
    promise
      .then(setTimeline)
      .catch(() => setTimeline([]))
      .finally(() => setTimelineLoading(false))
  }, [projectId, timeRange, timelineManagerId])

  useEffect(() => { loadTimeline() }, [loadTimeline])

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
        <button
          className={tab === 'settings' ? styles.activeTab : styles.tab}
          onClick={() => setTab('settings')}
        >
          Настройки
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
        <div className={styles.analyticsGrid}>
          <div className={`${styles.section} ${styles.sectionWide}`}>
            <div className={styles.timelineHeader}>
              <h2 className={styles.sectionTitle}>Средний балл по дням</h2>
              <div className={styles.timelineFilters}>
                <select
                  className={formStyles.select}
                  value={timeRange}
                  onChange={e => setTimeRange(e.target.value as TimePreset)}
                >
                  {TIME_PRESETS.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
                </select>
                <select
                  className={formStyles.select}
                  value={timelineManagerId}
                  onChange={e => setTimelineManagerId(e.target.value)}
                >
                  <option value="">Все менеджеры</option>
                  {project.members.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                </select>
              </div>
            </div>
            {timelineLoading ? (
              <div className={styles.state}>Загрузка...</div>
            ) : timeline.length === 0 ? (
              <div className={styles.empty}>Нет оценённых звонков за этот период</div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={timeline}>
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} stroke="var(--border)" />
                  <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} stroke="var(--border)" />
                  <Tooltip
                    formatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                    contentStyle={{
                      background: 'var(--bg-elevated)',
                      border: '1px solid var(--border)',
                      borderRadius: 8,
                      color: 'var(--text)',
                    }}
                    labelStyle={{ color: 'var(--text-muted)' }}
                  />
                  <Line type="monotone" dataKey="avg_score" stroke="#ec4899" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

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

          {metrics.length === 0 && managers.length === 0 && (
            <div className={styles.empty}>Нет данных по критериям и менеджерам за всё время</div>
          )}
        </div>
      )}

      {tab === 'settings' && (
        <SettingsTab
          project={project}
          onProjectChanged={refreshProject}
          onArchived={() => navigate('/projects')}
        />
      )}
    </div>
  )
}

// ── Settings tab ────────────────────────────────────────────────────────────

function SettingsTab({
  project, onProjectChanged, onArchived,
}: { project: Project; onProjectChanged: () => void; onArchived: () => void }) {
  return (
    <div className={styles.analytics}>
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Проект</h2>
        <ProjectInfoForm project={project} onSaved={onProjectChanged} onArchived={onArchived} />
      </div>

      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Менеджеры</h2>
        <MembersEditor project={project} onChanged={onProjectChanged} />
      </div>

      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Группы метрик</h2>
        <MetricGroupsEditor projectId={project.id} />
      </div>
    </div>
  )
}

function ProjectInfoForm({
  project, onSaved, onArchived,
}: { project: Project; onSaved: () => void; onArchived: () => void }) {
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      await updateProject(project.id, {
        name,
        clear_description: description.trim() === '',
        description: description.trim() === '' ? undefined : description,
      })
      onSaved()
    } catch {
      setError('Не удалось сохранить изменения')
    } finally {
      setSaving(false)
    }
  }

  async function handleArchive() {
    if (!confirm(`Архивировать проект «${project.name}»? Это возможно только если у него нет активных звонков.`)) return
    try {
      await archiveProject(project.id)
      onArchived()
    } catch {
      alert('Не удалось архивировать: в проекте есть звонки в незавершённом статусе.')
    }
  }

  return (
    <form className={formStyles.form} onSubmit={handleSubmit} style={{ maxWidth: 460 }}>
      {error && <div className={formStyles.error}>{error}</div>}
      <label className={formStyles.label}>
        Название
        <input className={formStyles.input} value={name} onChange={e => setName(e.target.value)} required />
      </label>
      <label className={formStyles.label}>
        Описание
        <textarea className={formStyles.textarea} value={description} onChange={e => setDescription(e.target.value)} />
      </label>
      <div className={formStyles.actions}>
        <button className={formStyles.btnPrimary} type="submit" disabled={saving}>
          {saving ? 'Сохранение...' : 'Сохранить'}
        </button>
        <button className={formStyles.btnDanger} type="button" onClick={handleArchive}>
          Архивировать проект
        </button>
      </div>
    </form>
  )
}

function MembersEditor({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [allManagers, setAllManagers] = useState<Manager[]>([])
  const [selected, setSelected] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getManagers()
      .then(setAllManagers)
      .catch(() => setError('Не удалось загрузить список менеджеров'))
  }, [])

  const available = allManagers.filter(m => !project.members.some(pm => pm.id === m.id))

  async function handleAdd(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!selected) return
    try {
      await addMember(project.id, Number(selected))
      setSelected('')
      onChanged()
    } catch {
      setError('Не удалось добавить менеджера')
    }
  }

  async function handleRemove(userId: number) {
    try {
      await removeMember(project.id, userId)
      onChanged()
    } catch {
      setError('Не удалось удалить менеджера из проекта')
    }
  }

  return (
    <div>
      {error && <div className={formStyles.error} style={{ marginBottom: 10 }}>{error}</div>}
      {project.members.length === 0 ? (
        <div className={styles.empty}>В проекте пока нет менеджеров</div>
      ) : (
        <div className={styles.memberList}>
          {project.members.map(m => (
            <div key={m.id} className={styles.memberRow}>
              <span className={styles.memberInfo}>
                <Avatar name={m.name} size={26} />
                {m.name}
              </span>
              <button className={formStyles.btnLink} onClick={() => handleRemove(m.id)}>Убрать</button>
            </div>
          ))}
        </div>
      )}

      {available.length > 0 && (
        <form className={styles.inlineForm} onSubmit={handleAdd}>
          <select className={formStyles.select} style={{ flex: 1 }} value={selected} onChange={e => setSelected(e.target.value)}>
            <option value="">Выбрать менеджера…</option>
            {available.map(m => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
          <button className={styles.btnAddManager} type="submit" disabled={!selected}>
            <IconPlus size={16} />
            Добавить менеджера
          </button>
        </form>
      )}
      {available.length === 0 && allManagers.length > 0 && (
        <p className={styles.empty}>Все менеджеры уже добавлены в проект</p>
      )}
      {allManagers.length === 0 && (
        <p className={styles.empty}>
          Менеджеров ещё нет — создайте их на странице «Менеджеры»
        </p>
      )}
    </div>
  )
}

function MetricGroupsEditor({ projectId }: { projectId: number }) {
  const [groups, setGroups] = useState<MetricGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  function reload() {
    setLoading(true)
    setError(null)
    getMetricGroups(projectId)
      .then(setGroups)
      .catch(() => setError('Не удалось загрузить группы метрик'))
      .finally(() => setLoading(false))
  }

  useEffect(reload, [projectId])

  async function handleDeleteGroup(g: MetricGroup) {
    if (!confirm(`Удалить группу «${g.name}»?`)) return
    try {
      await deleteMetricGroup(g.id)
      reload()
    } catch {
      alert('Не удалось удалить: по этой группе уже есть результаты анализа звонков.')
    }
  }

  if (loading) return <div className={styles.state}>Загрузка...</div>
  if (error) return <div className={`${styles.state} ${styles.error}`}>{error}</div>

  return (
    <div>
      {groups.length === 0 ? (
        <div className={styles.empty}>Групп метрик пока нет</div>
      ) : (
        groups.map(g => (
          <MetricGroupCard key={g.id} group={g} onChanged={reload} onDelete={() => handleDeleteGroup(g)} />
        ))
      )}

      <button className={formStyles.btnPrimary} style={{ marginTop: 12 }} onClick={() => setShowCreate(true)}>
        + Добавить группу метрик
      </button>

      {showCreate && (
        <CreateGroupModal
          projectId={projectId}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); reload() }}
        />
      )}
    </div>
  )
}

function MetricGroupCard({
  group, onChanged, onDelete,
}: { group: MetricGroup; onChanged: () => void; onDelete: () => void }) {
  const [newItemName, setNewItemName] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function handleAddItem(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!newItemName.trim()) return
    try {
      await createMetricItem(group.id, { name: newItemName.trim() })
      setNewItemName('')
      onChanged()
    } catch {
      setError('Не удалось добавить пункт')
    }
  }

  async function handleDeleteItem(itemId: number) {
    try {
      await deleteMetricItem(itemId)
      onChanged()
    } catch {
      setError('Не удалось удалить пункт')
    }
  }

  async function handleRenameItem(itemId: number, currentName: string) {
    const name = prompt('Новое название пункта:', currentName)
    if (!name || name === currentName) return
    try {
      await updateMetricItem(itemId, { name })
      onChanged()
    } catch {
      setError('Не удалось переименовать пункт')
    }
  }

  async function handleRenameGroup(groupId: number, currentName: string) {
    const name = prompt('Новое название группы:', currentName)
    if (!name || name === currentName) return
    try {
      await updateMetricGroup(groupId, { name })
      onChanged()
    } catch {
      setError('Не удалось переименовать группу')
    }
  }

  return (
    <div className={styles.groupCard}>
      <div className={styles.groupHeader}>
        <div>
          <div className={styles.groupName}>{group.name}</div>
          <div className={styles.groupType}>{GROUP_TYPE_LABELS[group.group_type]}</div>
        </div>
        <span className={styles.itemActions}>
          <button className={formStyles.btnLink} onClick={() => handleRenameGroup(group.id, group.name)}>Переименовать</button>
          <button className={formStyles.btnLink} onClick={onDelete}>Удалить группу</button>
        </span>
      </div>

      {error && <div className={formStyles.error} style={{ marginBottom: 8 }}>{error}</div>}

      {group.items.length === 0 ? (
        <p className={styles.empty}>Пунктов пока нет</p>
      ) : (
        <ul className={styles.itemList}>
          {group.items.filter(i => i.is_active).map(item => (
            <li key={item.id} className={styles.itemRow}>
              <span>{item.position}. {item.name}</span>
              <span className={styles.itemActions}>
                <button className={formStyles.btnLink} onClick={() => handleRenameItem(item.id, item.name)}>✎</button>
                <button className={formStyles.btnLink} onClick={() => handleDeleteItem(item.id)}>×</button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <form className={styles.inlineForm} onSubmit={handleAddItem}>
        <input
          className={formStyles.input}
          style={{ flex: 1 }}
          placeholder="Название нового пункта"
          value={newItemName}
          onChange={e => setNewItemName(e.target.value)}
        />
        <button className={formStyles.btnSecondary} type="submit" disabled={!newItemName.trim()}>
          Добавить пункт
        </button>
      </form>
    </div>
  )
}

export function CreateGroupModal({
  projectId, onClose, onCreated,
}: { projectId: number; onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [groupType, setGroupType] = useState<MetricGroupType>('script_stages')
  const [promptTemplate, setPromptTemplate] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      await createMetricGroup(projectId, { name, group_type: groupType, prompt_template: promptTemplate })
      onCreated()
    } catch {
      setError('Не удалось создать группу')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="Новая группа метрик" onClose={onClose}>
      <form className={formStyles.form} onSubmit={handleSubmit}>
        {error && <div className={formStyles.error}>{error}</div>}
        <label className={formStyles.label}>
          Название
          <input className={formStyles.input} value={name} onChange={e => setName(e.target.value)} required autoFocus />
        </label>
        <label className={formStyles.label}>
          Тип
          <select
            className={formStyles.select}
            value={groupType}
            onChange={e => setGroupType(e.target.value as MetricGroupType)}
          >
            {Object.entries(GROUP_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label className={formStyles.label}>
          Промпт для LLM
          <textarea
            className={formStyles.textarea}
            value={promptTemplate}
            onChange={e => setPromptTemplate(e.target.value)}
            placeholder="Опиши, что именно должна оценить модель по этой группе"
            required
          />
        </label>
        <div className={formStyles.actions}>
          <button className={formStyles.btnPrimary} type="submit" disabled={saving}>
            {saving ? 'Создание...' : 'Создать'}
          </button>
          <button className={formStyles.btnSecondary} type="button" onClick={onClose}>Отмена</button>
        </div>
      </form>
    </Modal>
  )
}
