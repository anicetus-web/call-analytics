import { useId } from 'react'
import styles from './SessionStatus.module.css'

function fmtSince(iso: string): string {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'только что'
  if (mins < 60) return `${mins} мин назад`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} ч назад`
  return new Date(iso).toLocaleDateString('ru-RU')
}

export default function SessionStatus({
  active, since, size = 12,
}: { active: boolean; since?: string | null; size?: number }) {
  const gradId = useId()
  const label = active
    ? `Сессия активна${since ? ` — начата ${fmtSince(since)}` : ''}`
    : 'Нет активной сессии'

  return (
    <span className={styles.wrap} title={label}>
      <svg
        width={size} height={size} viewBox="0 0 24 24"
        className={`${styles.dot} ${active ? styles.dotActive : styles.dotInactive}`}
      >
        <defs>
          <radialGradient id={gradId} cx="35%" cy="30%" r="70%">
            {active ? (
              <>
                <stop offset="0%" stopColor="#86efac" />
                <stop offset="100%" stopColor="#059669" />
              </>
            ) : (
              <>
                <stop offset="0%" stopColor="#fca5a5" />
                <stop offset="100%" stopColor="#b91c1c" />
              </>
            )}
          </radialGradient>
        </defs>
        <circle cx="12" cy="12" r="10" fill={`url(#${gradId})`} />
      </svg>
      <span className={active ? styles.labelActive : styles.labelInactive}>
        {active ? 'сессия активна' : 'нет сессии'}
      </span>
    </span>
  )
}
