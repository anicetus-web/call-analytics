import { useEffect, useState, useMemo, FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { getManagers, createManager, updateManager, deleteManager, Manager } from '../api'
import Modal from '../components/Modal'
import Avatar from '../components/Avatar'
import { IconSearch } from '../components/icons'
import styles from './ManagersPage.module.css'
import formStyles from '../components/Form.module.css'

export default function ManagersPage() {
  const [managers, setManagers] = useState<Manager[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [editing, setEditing] = useState<Manager | null>(null)
  const [query, setQuery] = useState('')

  function reload() {
    setLoading(true)
    getManagers()
      .then(setManagers)
      .catch(() => setError('Не удалось загрузить менеджеров'))
      .finally(() => setLoading(false))
  }

  useEffect(reload, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return managers
    return managers.filter(m =>
      m.name.toLowerCase().includes(q) || String(m.telegram_id ?? '').includes(q)
    )
  }, [managers, query])

  async function handleDelete(m: Manager) {
    if (!confirm(`Удалить менеджера «${m.name}»? Это возможно только если у него нет звонков.`)) return
    try {
      await deleteManager(m.id)
      reload()
    } catch {
      alert('Не удалось удалить: у менеджера, вероятно, есть звонки в системе.')
    }
  }

  if (loading) return <div className={styles.state}>Загрузка...</div>
  if (error) return <div className={styles.state + ' ' + styles.error}>{error}</div>

  return (
    <div>
      <div className={styles.header}>
        <h1 className={styles.title}>Менеджеры</h1>
        <div className={styles.headerActions}>
          <div className={styles.search}>
            <IconSearch size={16} className={styles.searchIcon} />
            <input
              placeholder="Поиск по имени или Telegram ID..."
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
          </div>
          <button className={formStyles.btnPrimary} onClick={() => setShowCreate(true)}>
            + Новый менеджер
          </button>
        </div>
      </div>

      {managers.length === 0 ? (
        <div className={styles.empty}>Менеджеров пока нет</div>
      ) : filtered.length === 0 ? (
        <div className={styles.empty}>Ничего не найдено по запросу «{query}»</div>
      ) : (
        <div className={styles.list}>
          {filtered.map(m => (
            <Link to={`/managers/${m.id}`} key={m.id} className={styles.row}>
              <div className={styles.rowLeft}>
                <Avatar name={m.name} size={36} />
                <div>
                  <div className={styles.name}>{m.name}</div>
                  <div className={styles.meta}>
                    Telegram ID: {m.telegram_id ?? '—'}
                    {m.login && <> · логин: {m.login}</>}
                  </div>
                </div>
              </div>
              <div className={styles.rowActions}>
                <button
                  className={formStyles.btnLink}
                  onClick={e => { e.preventDefault(); e.stopPropagation(); setEditing(m) }}
                >
                  Изменить
                </button>
                <button
                  className={formStyles.btnLink}
                  onClick={e => { e.preventDefault(); e.stopPropagation(); handleDelete(m) }}
                >
                  Удалить
                </button>
              </div>
            </Link>
          ))}
        </div>
      )}

      {showCreate && (
        <ManagerModal
          title="Новый менеджер"
          onClose={() => setShowCreate(false)}
          onSaved={() => { setShowCreate(false); reload() }}
          save={data => createManager(data)}
        />
      )}

      {editing && (
        <ManagerModal
          title="Изменить менеджера"
          initial={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload() }}
          save={data => updateManager(editing.id, data)}
        />
      )}
    </div>
  )
}

function ManagerModal({
  title, initial, onClose, onSaved, save,
}: {
  title: string
  initial?: Manager
  onClose: () => void
  onSaved: () => void
  save: (data: { name: string; telegram_id: number }) => Promise<unknown>
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [telegramId, setTelegramId] = useState(initial?.telegram_id?.toString() ?? '')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const tgId = Number(telegramId)
    if (!Number.isInteger(tgId) || tgId <= 0) {
      setError('Telegram ID должен быть положительным числом')
      return
    }
    setSaving(true)
    try {
      await save({ name, telegram_id: tgId })
      onSaved()
    } catch {
      setError('Не удалось сохранить. Возможно, такой Telegram ID уже используется.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={title} onClose={onClose}>
      <form className={formStyles.form} onSubmit={handleSubmit}>
        {error && <div className={formStyles.error}>{error}</div>}
        <label className={formStyles.label}>
          Имя
          <input
            className={formStyles.input}
            value={name}
            onChange={e => setName(e.target.value)}
            required
            autoFocus
          />
        </label>
        <label className={formStyles.label}>
          Telegram ID
          <input
            className={formStyles.input}
            type="number"
            value={telegramId}
            onChange={e => setTelegramId(e.target.value)}
            required
          />
        </label>
        <div className={formStyles.actions}>
          <button className={formStyles.btnPrimary} type="submit" disabled={saving}>
            {saving ? 'Сохранение...' : 'Сохранить'}
          </button>
          <button className={formStyles.btnSecondary} type="button" onClick={onClose}>
            Отмена
          </button>
        </div>
      </form>
    </Modal>
  )
}
