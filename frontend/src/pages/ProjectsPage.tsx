import { useEffect, useState, FormEvent, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { getProjects, createProject, archiveProject, Project } from '../api'
import Modal from '../components/Modal'
import Avatar from '../components/Avatar'
import QuickActions from '../components/QuickActions'
import { IconSearch, IconPlus, IconGroup } from '../components/icons'
import styles from './ProjectsPage.module.css'
import formStyles from '../components/Form.module.css'

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

  function reload() {
    setLoading(true)
    getProjects()
      .then(setProjects)
      .catch(() => setError('Не удалось загрузить проекты'))
      .finally(() => setLoading(false))
  }

  useEffect(reload, [])

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
          </div>
          <button className={formStyles.btnPrimary} onClick={() => setShowCreate(true)}>
            <IconPlus size={16} /> Новый проект
          </button>
        </div>
      </div>

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

      <QuickActions onChanged={reload} />

      <div className={styles.banner}>
        <div>
          <div className={styles.bannerTitle}>🚀 Добро пожаловать в Call Analytics!</div>
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
