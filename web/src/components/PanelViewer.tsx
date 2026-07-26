import { useEffect, useState } from 'react'
import { panelStore, panelUrl, type PanelSummary } from '../panels'
import './PanelViewer.css'

/**
 * Full-screen view of a panel Rau made.
 *
 * The document is model-written, so it is mounted the way hostile-but-useful
 * input should be: `sandbox="allow-scripts"` and deliberately *without*
 * `allow-same-origin`, which puts it in an opaque origin. Scripts run — a
 * dashboard has to be able to respond to a click — but the document cannot
 * read this app's storage or DOM, and cannot call the hub as the user. The
 * server additionally serves it under a Content-Security-Policy that forbids
 * reaching the network at all, so there is nowhere for anything to go.
 *
 * The frame is created only while a panel is open. Keeping one mounted per
 * panel on the wall would cost a document, a script context and a paint each,
 * for something the size of a postage stamp.
 */
export default function PanelViewer() {
  const [open, setOpen] = useState<string | null>(panelStore.openPanel)
  const [panels, setPanels] = useState<PanelSummary[]>(panelStore.list())

  useEffect(
    () =>
      panelStore.subscribe(() => {
        setOpen(panelStore.openPanel)
        setPanels(panelStore.list())
      }),
    [],
  )

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') panelStore.show(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  if (!open) return null
  const panel = panels.find((p) => p.panel_id === open)

  return (
    <div className="panel-viewer" role="dialog" aria-modal="true" aria-label={panel?.title || 'Panel'}>
      <div className="panel-viewer-backdrop" onClick={() => panelStore.show(null)} />
      <div className="panel-viewer-frame">
        <header className="panel-viewer-head">
          <span className="panel-viewer-kind">{panel?.kind || 'report'}</span>
          <h2>{panel?.title || 'Panel'}</h2>
          <button
            className="panel-viewer-close"
            onClick={() => panelStore.show(null)}
            aria-label="Close panel"
          >
            ✕
          </button>
        </header>
        <iframe
          key={open}
          className="panel-viewer-doc"
          title={panel?.title || 'Panel'}
          src={panelUrl(open)}
          // No allow-same-origin: scripts run, but in an opaque origin that
          // cannot reach this app or the hub. Do not add it.
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
        />
      </div>
    </div>
  )
}
