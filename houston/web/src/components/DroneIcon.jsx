import React from 'react'

export default function DroneIcon({ alive = false, size = 18 }) {
  const color = alive ? '#17ffd8' : '#e35b5b'
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" role="img" aria-label={alive ? 'alive' : 'lost'}>
      <g fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="5" cy="5" r="3" />
        <circle cx="19" cy="5" r="3" />
        <circle cx="5" cy="19" r="3" />
        <circle cx="19" cy="19" r="3" />
        <path d="M8 8l8 8M16 8l-8 8" />
      </g>
    </svg>
  )
}
