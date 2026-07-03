import { useState } from 'react'
import styles from './Heatmap.module.css'

const WEEKDAY_LABELS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

export interface HeatmapCellData {
  weekday: number
  hour: number
  call_count: number
}

function pluralCalls(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'звонок'
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return 'звонка'
  return 'звонков'
}

export default function Heatmap({ cells }: { cells: HeatmapCellData[] }) {
  const [active, setActive] = useState<{ weekday: number; hour: number; count: number } | null>(null)

  const countMap = new Map<string, number>()
  for (const c of cells) countMap.set(`${c.weekday}-${c.hour}`, c.call_count)
  const max = cells.reduce((m, c) => Math.max(m, c.call_count), 0)

  return (
    <div>
      <div className={styles.infoBar}>
        {active ? (
          <span className={styles.infoChip}>
            {WEEKDAY_LABELS[active.weekday]}, {active.hour}:00 — {active.count} {pluralCalls(active.count)}
          </span>
        ) : (
          <span className={styles.infoHint}>Наведите или нажмите на ячейку</span>
        )}
      </div>
      <div className={styles.heatmap}>
        <div className={styles.heatmapRow}>
          <span className={styles.heatmapCorner} />
          {Array.from({ length: 24 }, (_, h) => (
            <span key={h} className={styles.heatmapHourLabel}>{h % 3 === 0 ? h : ''}</span>
          ))}
        </div>
        {WEEKDAY_LABELS.map((label, weekday) => (
          <div key={weekday} className={styles.heatmapRow}>
            <span className={styles.heatmapDayLabel}>{label}</span>
            {Array.from({ length: 24 }, (_, hour) => {
              const count = countMap.get(`${weekday}-${hour}`) ?? 0
              const intensity = max > 0 ? count / max : 0
              const isActive = active?.weekday === weekday && active?.hour === hour
              return (
                <span
                  key={hour}
                  className={isActive ? styles.heatmapCellActive : styles.heatmapCell}
                  style={{ background: intensity > 0 ? `rgba(236,72,153,${0.12 + intensity * 0.75})` : undefined }}
                  onMouseEnter={() => setActive({ weekday, hour, count })}
                  onMouseLeave={() => setActive(null)}
                  onClick={() => setActive({ weekday, hour, count })}
                />
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
