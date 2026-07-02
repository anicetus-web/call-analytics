import { useEffect, useState, FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { getProjects, createProject, Project } from '../api'
import Modal from '../components/Modal'
import styles from './ProjectsPage.module.css'
import formStyles from '../components/Form.module.css'

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  function reload() {
    setLoading(true)
    getProjects()
      .then(setProjects)
      .catch(() => setError('Не удалось загрузить проекты'))
      .finally(() => setLoading(false))
  }

  useEffect(reload, [])

  if (loading) return <div className={styles.state}>Загрузка...</div>
  if (error) return <div className={styles.state + ' ' + styles.error}>{error}</div>

  return (
    <div>
      <div className={styles.header}>
        <h1 className={styles.title}>Проекты</h1>
        <button className={formStyles.btnPrimary} onClick={() => setShowCreate(true)}>
          + Новый проект
        </button>
      </div>

      {projects.length === 0 ? (
        <div className={styles.empty}>Нет активных проектов</div>
      ) : (
        <div className={styles.grid}>
          {projects.map(p => (
            <Link to={`/projects/${p.id}`} key={p.id} className={styles.card}>
              <div className={styles.cardName}>{p.name}</div>
              {p.description && (
                <div className={styles.cardDesc}>{p.description}</div>
              )}
              <div className={styles.cardMeta}>
                {p.members.length} {pluralMembers(p.members.length)}
              </div>
            </Link>
          ))}
        </div>
      )}

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
