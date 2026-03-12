import React from 'react'

export default function Panel({title, actions, children, className = ''}) {
  return (
    <div className={`panel ${className}`}>
      <div className="panel-header">
        <div className="panel-title">{title}</div>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </div>
      <div className="panel-body">{children}</div>
    </div>
  )
}
