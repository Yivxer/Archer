import React from 'react'

type ExpertAvatarSpec = {
  glyph: string
  art: React.ReactNode
}

const AVATARS: Record<string, ExpertAvatarSpec> = {
  default: {
    glyph: '#2bb8b0',
    art: (
      <>
        <circle cx="16" cy="16" r="5.5" fill="none" stroke="currentColor" strokeWidth="2.2" />
        <circle cx="16" cy="16" r="2" fill="currentColor" opacity="0.9" />
      </>
    ),
  },
  developer: {
    glyph: '#2f9a62',
    art: (
      <>
        <path d="M11 12.5 8.5 16 11 19.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <path d="M21 12.5 23.5 16 21 19.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <path d="M18 11.5 14 20.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
      </>
    ),
  },
  'video-coach': {
    glyph: '#f07a45',
    art: <path d="M13 11.5 20 16 13 20.5z" fill="currentColor" />,
  },
  'content-creator': {
    glyph: '#8b5cf6',
    art: (
      <>
        <path d="M12 21.5 19 11.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <path d="M19 11.5h-4.5v4.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <circle cx="11" cy="21.5" r="1.6" fill="currentColor" />
      </>
    ),
  },
  counselor: {
    glyph: '#4f8fd9',
    art: (
      <path
        d="M16 21.5c3.8 0 6.8-2.4 6.8-5.4 0-2.2-1.8-3.6-3.8-4.2-.8-1.4-2.2-2.2-3-2.2s-2.2.8-3 2.2c-2 .6-3.8 2-3.8 4.2 0 3 3 5.4 6.8 5.4z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    ),
  },
  'parent-educator': {
    glyph: '#d9921d',
    art: (
      <>
        <path d="M10.5 12h5v8.5h-5a1.2 1.2 0 0 1-1.2-1.2v-6.1A1.2 1.2 0 0 1 10.5 12z" fill="currentColor" opacity="0.28" />
        <path d="M21.5 12H16.5v8.5h5a1.2 1.2 0 0 0 1.2-1.2v-6.1A1.2 1.2 0 0 0 21.5 12z" fill="currentColor" opacity="0.28" />
        <path d="M16 12.5v7.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </>
    ),
  },
}

export function ExpertAvatar({
  expertId,
  size = 28,
  className = '',
  title,
}: {
  expertId: string | undefined
  size?: number
  className?: string
  title?: string
}) {
  const spec = AVATARS[expertId || 'default'] || AVATARS.default

  return (
    <span
      className={`expert-avatar ${className}`.trim()}
      style={{ width: size, height: size }}
      title={title}
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      aria-label={title}
    >
      <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden="true">
        <g color={spec.glyph}>
          {spec.art}
        </g>
      </svg>
    </span>
  )
}
