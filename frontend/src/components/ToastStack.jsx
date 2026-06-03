import React from 'react'

export default function ToastStack({toasts}) {
  // Only show the first toast if any
  const toast = toasts && toasts.length > 0 ? toasts[0] : null
  return (
    <div className="toast-stack">
      {toast && (
        <div key={toast.id} className="toast">
          <div className="toast-title">{toast.title}</div>
          <div className="toast-body">{toast.body}</div>
        </div>
      )}
    </div>
  )
}
