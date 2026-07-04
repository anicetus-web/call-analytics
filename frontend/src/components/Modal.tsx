import { ReactNode } from 'react'
import styles from './Modal.module.css'

export default function Modal({
  title, onClose, children,
}: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.card} onClick={e => e.stopPropagation()}>
        <div className={styles.header}>
          <h2 className={styles.title}>{title}</h2>
          <button className={styles.closeBtn} onClick={onClose} type="button" aria-label="Закрыть">×</button>
        </div>
        {children}
      </div>
    </div>
  )
}
