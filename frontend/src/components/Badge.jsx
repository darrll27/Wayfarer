import React from 'react'

export default function Badge({label, tone = 'neutral'}) {
  return <span className={`badge badge-${tone}`}>{label}</span>
}
