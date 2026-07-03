import styles from './Avatar.module.css'

const PALETTE = [
  ['#ec4899', '#be185d'],
  ['#6366f1', '#4338ca'],
  ['#10b981', '#047857'],
  ['#f59e0b', '#b45309'],
  ['#8b5cf6', '#6d28d9'],
  ['#06b6d4', '#0e7490'],
]

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0][0].toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

function colorFor(seed: string): [string, string] {
  let hash = 0
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  }
  return PALETTE[hash % PALETTE.length] as [string, string]
}

export default function Avatar({
  name, size = 32,
}: { name: string; size?: number }) {
  const [from, to] = colorFor(name)
  return (
    <div
      className={styles.avatar}
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.4),
        background: `linear-gradient(135deg, ${from}, ${to})`,
      }}
      title={name}
    >
      {initials(name)}
    </div>
  )
}
