import { useEffect, useState, FormEvent, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { getProjects, createProject, archiveProject, getCallsTimeline, Project, CallsTimelinePoint } from '../api'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import Modal from '../components/Modal'
import Avatar from '../components/Avatar'
import QuickActions from '../components/QuickActions'
import { IconSearch, IconPlus, IconGroup, LogoMark } from '../components/icons'
import styles from './ProjectsPage.module.css'
import formStyles from '../components/Form.module.css'

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function fmtShortDate(iso: string): string {
  const d = new Date(iso)
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}`
}

// Recharts' default activeDot teleports instantly from point to point on
// hover — no interpolation. Wrapping it in a <g> and animating `transform`
// (not cx/cy, which don't transition reliably across browsers) gives it a
// smooth glide between days instead of the "деревянно" instant jump.
function AnimatedActiveDot({ cx, cy }: { cx?: number; cy?: number }) {
  if (cx == null || cy == null) return null
  return (
    <g style={{ transform: `translate(${cx}px, ${cy}px)`, transition: 'transform 0.35s cubic-bezier(0.34, 1.2, 0.64, 1)' }}>
      <circle r={7} fill="#ec4899" opacity={0.18} />
      <circle r={4.5} fill="#ec4899" stroke="var(--bg-card)" strokeWidth={2} />
    </g>
  )
}

// Same fix for the Tooltip's vertical cursor line — Recharts' default
// cursor also snaps instantly between days instead of gliding.
function AnimatedCursor({ points, height }: { points?: { x: number }[]; height?: number }) {
  if (!points || points.length === 0 || height == null) return null
  const { x } = points[0]
  return (
    <g style={{ transform: `translate(${x}px, 0px)`, transition: 'transform 0.35s cubic-bezier(0.34, 1.2, 0.64, 1)' }}>
      <line y1={0} y2={height} stroke="var(--border)" strokeWidth={1} strokeDasharray="3 3" />
    </g>
  )
}

const GRADIENTS = [
  'linear-gradient(135deg, rgba(236,72,153,0.35), rgba(139,92,246,0.25))',
  'linear-gradient(135deg, rgba(99,102,241,0.35), rgba(6,182,212,0.25))',
  'linear-gradient(135deg, rgba(16,185,129,0.3), rgba(99,102,241,0.2))',
  'linear-gradient(135deg, rgba(245,158,11,0.3), rgba(236,72,153,0.2))',
]

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [query, setQuery] = useState('')
  const [menuFor, setMenuFor] = useState<number | null>(null)
  const [trend, setTrend] = useState<CallsTimelinePoint[]>([])

  function reload() {
    setLoading(true)
    getProjects()
      .then(setProjects)
      .catch(() => setError('Не удалось загрузить проекты'))
      .finally(() => setLoading(false))
  }

  useEffect(reload, [])

  useEffect(() => {
    getCallsTimeline({ dateFrom: isoDaysAgo(29) })
      .then(setTrend)
      .catch(() => {})
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return projects
    return projects.filter(p =>
      p.name.toLowerCase().includes(q) || (p.description ?? '').toLowerCase().includes(q)
    )
  }, [projects, query])

  async function handleArchive(p: Project) {
    setMenuFor(null)
    if (!confirm(`Архивировать проект «${p.name}»? Это возможно только если у него нет активных звонков.`)) return
    try {
      await archiveProject(p.id)
      reload()
    } catch {
      alert('Не удалось архивировать: в проекте есть звонки в незавершённом статусе.')
    }
  }

  if (loading) return <div className={styles.state}>Загрузка...</div>
  if (error) return <div className={styles.state + ' ' + styles.error}>{error}</div>

  return (
    <div>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Проекты</h1>
          <p className={styles.subtitle}>Управляйте проектами и отслеживайте прогресс команды</p>
        </div>
        <div className={styles.headerActions}>
          <div className={styles.search}>
            <IconSearch size={16} className={styles.searchIcon} />
            <input
              placeholder="Поиск по проектам..."
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
            {query && (
              <button
                className={styles.searchClear}
                onClick={() => setQuery('')}
                type="button"
                aria-label="Очистить поиск"
              >
                ×
              </button>
            )}
          </div>
          <button className={formStyles.btnPrimary} onClick={() => setShowCreate(true)}>
            <IconPlus size={16} />
            Новый проект
          </button>
        </div>
      </div>

      {query && projects.length > 0 && (
        <div className={styles.searchResultCount}>
          Найдено: {filtered.length} из {projects.length}
        </div>
      )}

      {projects.length === 0 ? (
        <div className={styles.empty}>Нет активных проектов</div>
      ) : filtered.length === 0 ? (
        <div className={styles.empty}>Ничего не найдено по запросу «{query}»</div>
      ) : (
        <div className={styles.grid}>
          {filtered.map((p, i) => (
            <div key={p.id} className={styles.card} style={{ background: GRADIENTS[i % GRADIENTS.length] }}>
              <div className={styles.cardHeader}>
                <span className={styles.cardIcon}><IconGroup size={18} /></span>
                <button
                  className={styles.menuBtn}
                  onClick={() => setMenuFor(menuFor === p.id ? null : p.id)}
                >
                  •••
                </button>
                {menuFor === p.id && (
                  <div className={styles.menu} onMouseLeave={() => setMenuFor(null)}>
                    <button onClick={() => handleArchive(p)}>Архивировать</button>
                  </div>
                )}
              </div>
              <Link to={`/projects/${p.id}`} className={styles.cardLink}>
                <div className={styles.cardName}>{p.name}</div>
                {p.description && <div className={styles.cardDesc}>{p.description}</div>}
              </Link>
              <div className={styles.cardFooter}>
                <div className={styles.avatarStack}>
                  {p.members.slice(0, 3).map(m => (
                    <Avatar key={m.id} name={m.name} size={28} />
                  ))}
                  {p.members.length > 3 && (
                    <div className={styles.avatarMore}>+{p.members.length - 3}</div>
                  )}
                </div>
                <span className={styles.cardMeta}>
                  {p.members.length} {pluralMembers(p.members.length)}
                </span>
              </div>
            </div>
          ))}

          <button className={styles.createTile} onClick={() => setShowCreate(true)}>
            <IconPlus size={22} />
            <span>Создать новый проект</span>
          </button>
        </div>
      )}

      {trend.some(t => t.call_count > 0) && (
        <div className={styles.trendCard}>
          <div className={styles.trendHeader}>
            <span className={styles.trendTitle}>Звонки за последние 30 дней</span>
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={trend} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
              <defs>
                <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#ec4899" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={fmtShortDate}
                tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                stroke="var(--border)"
                interval="preserveStartEnd"
              />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} stroke="var(--border)" />
              <Tooltip
                labelFormatter={fmtShortDate}
                formatter={(v: number) => [`${v}`, 'Звонков']}
                contentStyle={{
                  background: 'var(--bg-elevated)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  color: 'var(--text)',
                }}
                labelStyle={{ color: 'var(--text-muted)' }}
                cursor={<AnimatedCursor />}
              />
              <Area
                type="monotone"
                dataKey="call_count"
                stroke="#ec4899"
                strokeWidth={2.5}
                fill="url(#trendFill)"
                activeDot={<AnimatedActiveDot />}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <QuickActions onChanged={reload} />

      <div className={styles.banner}>
        <span className={styles.bannerIcon}><LogoMark size={20} /></span>
        <div>
          <div className={styles.bannerTitle}>Добро пожаловать в Call Analytics</div>
          <p className={styles.bannerText}>
            Выберите проект для начала работы или создайте новый, чтобы начать отслеживать
            эффективность вашей команды.
          </p>
        </div>
      </div>

      {showCreate && (
        <CreateProjectModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); reload() }}
        />
      )}
    </div>
  )
}

function CreateProjectModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      await createProject(name, description || undefined)
      onCreated()
    } catch {
      setError('Не удалось создать проект')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="Новый проект" onClose={onClose}>
      <form className={formStyles.form} onSubmit={handleSubmit}>
        {error && <div className={formStyles.error}>{error}</div>}
        <label className={formStyles.label}>
          Название
          <input
            className={formStyles.input}
            value={name}
            onChange={e => setName(e.target.value)}
            required
            autoFocus
          />
        </label>
        <label className={formStyles.label}>
          Описание
          <textarea
            className={formStyles.textarea}
            value={description}
            onChange={e => setDescription(e.target.value)}
          />
        </label>
        <div className={formStyles.actions}>
          <button className={formStyles.btnPrimary} type="submit" disabled={saving}>
            {saving ? 'Создание...' : 'Создать'}
          </button>
          <button className={formStyles.btnSecondary} type="button" onClick={onClose}>
            Отмена
          </button>
        </div>
      </form>
    </Modal>
  )
}

function pluralMembers(n: number): string {
  if (n % 10 === 1 && n % 100 !== 11) return 'менеджер'
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return 'менеджера'
  return 'менеджеров'
}
