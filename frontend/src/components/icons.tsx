type IconProps = { size?: number; className?: string }

const base = (size = 20) => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
})

// Logo mark: a simple audio waveform — four bars of varying height, symmetric
// around the vertical center. Deliberately minimal so it stays crisp at the
// small sizes it's actually rendered at (20-26px), unlike the earlier
// speech-bubble-plus-bars combination which turned into a muddy blob that
// small.
export function LogoMark({ size = 24, className }: IconProps) {
  return (
    <svg {...base(size)} className={className} strokeWidth={2.2}>
      <path d="M4 9v6" />
      <path d="M9 5v14" />
      <path d="M14 7v10" />
      <path d="M19 9v6" />
    </svg>
  )
}

export function IconFolder({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M3 6.5a1 1 0 0 1 1-1h4.5l1.8 2H20a1 1 0 0 1 1 1V17a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6.5Z" />
    </svg>
  )
}

export function IconUsers({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="9" cy="8" r="3" />
      <path d="M3.5 19c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
      <path d="M15.5 4.3c1.4.3 2.5 1.6 2.5 3.2 0 1.6-1.1 2.9-2.5 3.2" />
      <path d="M17 14.2c2 .4 3.5 2.1 3.5 4.3" />
    </svg>
  )
}

export function IconPhoneWave({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4.5 4a1 1 0 0 1 1-1h2.2a1 1 0 0 1 1 .8l.7 3a1 1 0 0 1-.3 1L7.6 9.4a13 13 0 0 0 7 7l1.6-1.5a1 1 0 0 1 1-.3l3 .7a1 1 0 0 1 .8 1V18.5a1 1 0 0 1-1 1C11.5 19.5 4.5 12.5 4.5 4Z" />
    </svg>
  )
}

export function IconHelp({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v3.4M12 17.1v3.4M3.5 12h3.4M17.1 12h3.4" />
    </svg>
  )
}

export function IconSearch({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M20 20l-4.5-4.5" />
    </svg>
  )
}

export function IconPlus({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

export function IconLogout({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M9 4H6a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h3" />
      <path d="M14 8l4 4-4 4" />
      <path d="M18 12H9" />
    </svg>
  )
}

export function IconGroup({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <rect x="3" y="4" width="7" height="7" rx="1.5" />
      <rect x="14" y="4" width="7" height="7" rx="1.5" />
      <rect x="8.5" y="14" width="7" height="7" rx="1.5" />
    </svg>
  )
}

export function IconAlert({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 3.5 21 19.5H3L12 3.5Z" />
      <path d="M12 10v4" />
      <path d="M12 16.7h.01" strokeWidth={3} />
    </svg>
  )
}

export function IconClock({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </svg>
  )
}

export function IconTarget({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="4.5" />
      <path d="M12 11.9h.01" strokeWidth={3} />
    </svg>
  )
}

export function IconTrend({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 16l5.5-5.5 4 4L20 8" />
      <path d="M14.5 8H20v5.5" />
    </svg>
  )
}

export function IconChart({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className} strokeWidth={2.4} strokeLinecap="round">
      <path d="M6 19v-5" />
      <path d="M12 19V9" />
      <path d="M18 19V6" />
    </svg>
  )
}

export function IconMenu({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className} strokeWidth={2.2}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  )
}

export function IconClose({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className} strokeWidth={2.2}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  )
}
