import { useEffect, useState, FormEvent } from 'react'
import {
  getProjects, createManager, addMember, Project,
} from '../api'
import { CreateGroupModal } from '../pages/ProjectDetailPage'
import Modal from './Modal'
import { IconUsers, IconGroup, IconHelp } from './icons'
import formStyles from './Form.module.css'
import styles from './QuickActions.module.css'

export default function QuickActions({ onChanged }: { onChanged: () => void }) {
  const [showAddManager, setShowAddManager] = useState(false)
  const [showCreateGroup, setShowCreateGroup] = useState(false)
  const [showHelp, setShowHelp] = useState(false)

  return (
    <div className={styles.section}>
      <h2 className={styles.title}>Быстрые действия</h2>
      <div className={styles.grid}>
        <button className={styles.tile} onClick={() => setShowAddManager(true)}>
          <span className={`${styles.iconBadge} ${styles.pink}`}><IconUsers size={20} /></span>
          Добавить менеджера
        </button>
        <button className={styles.tile} onClick={() => setShowCreateGroup(true)}>
          <span className={`${styles.iconBadge} ${styles.blue}`}><IconGroup size={20} /></span>
          Создать группу метрик
        </button>
        <button className={styles.tile} onClick={() => setShowHelp(true)}>
          <span className={`${styles.iconBadge} ${styles.purple}`}><IconHelp size={20} /></span>
          Помощь
        </button>
      </div>

      {showAddManager && (
        <AddManagerQuickModal
          onClose={() => setShowAddManager(false)}
          onDone={() => { setShowAddManager(false); onChanged() }}
        />
      )}

      {showCreateGroup && (
        <CreateGroupQuickFlow
          onClose={() => setShowCreateGroup(false)}
          onDone={() => { setShowCreateGroup(false); onChanged() }}
        />
      )}

      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}
    </div>
  )
}

function ProjectPicker({
  projects, value, onChange,
}: { projects: Project[]; value: string; onChange: (v: string) => void }) {
  return (
    <label className={formStyles.label}>
      Проект
      <select className={formStyles.select} value={value} onChange={e => onChange(e.target.value)} required>
        <option value="">Выберите проект…</option>
        {projects.map(p => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>
    </label>
  )
}

function AddManagerQuickModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [name, setName] = useState('')
  const [telegramId, setTelegramId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => { getProjects().then(setProjects).catch(() => {}) }, [])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const tgId = Number(telegramId)
    if (!Number.isInteger(tgId) || tgId <= 0) {
      setError('Telegram ID должен быть положительным числом')
      return
    }
    if (!projectId) {
      setError('Выберите проект')
      return
    }
    setSaving(true)
    let createdManagerId: number | null = null
    try {
      const manager = await createManager({ name, telegram_id: tgId })
      createdManagerId = manager.id
      // Second step can fail independently of the first — the manager already
      // exists at this point, so a generic "failed to create" message would be
      // wrong and retrying would just hit a 409 on the duplicate Telegram ID.
      await addMember(Number(projectId), manager.id)
      onDone()
    } catch {
      if (createdManagerId !== null) {
        setError(
          'Менеджер создан, но не удалось добавить его в проект. ' +
          'Откройте страницу «Менеджеры» — он там уже есть, добавьте его в проект оттуда.'
        )
      } else {
        setError('Не удалось создать менеджера. Возможно, такой Telegram ID уже используется.')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="Добавить менеджера" onClose={onClose}>
      <form className={formStyles.form} onSubmit={handleSubmit}>
        {error && <div className={formStyles.error}>{error}</div>}
        <ProjectPicker projects={projects} value={projectId} onChange={setProjectId} />
        <label className={formStyles.label}>
          Имя
          <input className={formStyles.input} value={name} onChange={e => setName(e.target.value)} required autoFocus />
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
            {saving ? 'Создание...' : 'Создать и добавить в проект'}
          </button>
          <button className={formStyles.btnSecondary} type="button" onClick={onClose}>Отмена</button>
        </div>
      </form>
    </Modal>
  )
}

function CreateGroupQuickFlow({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [confirmed, setConfirmed] = useState(false)

  useEffect(() => { getProjects().then(setProjects).catch(() => {}) }, [])

  if (confirmed && projectId) {
    return <CreateGroupModal projectId={Number(projectId)} onClose={onClose} onCreated={onDone} />
  }

  return (
    <Modal title="Создать группу метрик" onClose={onClose}>
      <form
        className={formStyles.form}
        onSubmit={e => { e.preventDefault(); if (projectId) setConfirmed(true) }}
      >
        <ProjectPicker projects={projects} value={projectId} onChange={setProjectId} />
        <div className={formStyles.actions}>
          <button className={formStyles.btnPrimary} type="submit" disabled={!projectId}>Продолжить</button>
          <button className={formStyles.btnSecondary} type="button" onClick={onClose}>Отмена</button>
        </div>
      </form>
    </Modal>
  )
}

function HelpModal({ onClose }: { onClose: () => void }) {
  return (
    <Modal title="Помощь" onClose={onClose}>
      <div className={styles.helpBody}>
        <p><strong>Проекты</strong> — рабочие пространства для команд/направлений. У каждого свои менеджеры и свои метрики оценки звонков.</p>
        <p><strong>Менеджеры</strong> добавляются по Telegram ID — попросите сотрудника написать боту <code>/start</code>, узнайте его ID и добавьте здесь.</p>
        <p><strong>Группы метрик</strong> — чек-листы, по которым LLM оценивает каждый звонок (например, «этапы скрипта продажи»).</p>
        <p><strong>Звонки</strong> — все записи, загруженные через бота, со статусом обработки и результатами.</p>
        <p style={{ color: 'var(--text-muted)' }}>Если что-то не работает — напишите разработчику.</p>
      </div>
    </Modal>
  )
}
