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

// Logo mark: a speech bubble built from a soundwave — reads as "calls + analytics"
// at a glance, unlike a plain phone handset.
export function LogoMark({ size = 24, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 5.5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9l-4.5 3.5V17H4a1 1 0 0 1-1-1v-9.5a1 1 0 0 1 1-1Z" />
      <path d="M7 12V9.5" />
      <path d="M10 12.5V8" />
      <path d="M13 12V10" />
      <path d="M16 12.5V7.5" />
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
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.2a2.5 2.5 0 1 1 3.7 2.2c-.8.5-1.2 1-1.2 1.9" />
      <circle cx="12" cy="16.8" r="0.15" fill="currentColor" stroke="none" />
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
      <circle cx="12" cy="16.7" r="0.15" fill="currentColor" stroke="none" />
    </svg>
  )
}
