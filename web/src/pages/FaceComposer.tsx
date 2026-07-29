/**
 * Face bottom composer.
 *
 * Owns its own draft so keystrokes do not re-render the room, the card table,
 * or the rest of Face. While a hand is on it collapses to a chip after send
 * (and on Escape / the hide control) so the fan is free again.
 */
import { useEffect, useRef, useState } from 'react'
import PermissionMenu from '../components/PermissionMenu'
import { useLocale } from '../i18n'

type Props = {
  inGame: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Deliver the trimmed message. Throw (or reject) to put the draft back. */
  onSend: (text: string) => void | Promise<void>
}

export default function FaceComposer({
  inGame,
  open,
  onOpenChange,
  onSend,
}: Props) {
  const { t } = useLocale()
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (open || !inGame) inputRef.current?.focus()
  }, [open, inGame])

  async function send() {
    const text = draft.trim()
    if (!text || sending) return
    setSending(true)
    setDraft('')
    setError('')
    // Collapse first so the hand is usable while the request is in flight.
    if (inGame) onOpenChange(false)
    try {
      await onSend(text)
    } catch {
      setDraft((d) => d || text)
      setError('Could not reach Rau — that message was not sent.')
      if (inGame) onOpenChange(true)
    } finally {
      setSending(false)
    }
  }

  /*
    Collapsing belongs to the table and nowhere else. Off the table the
    composer is the only way to say anything at all, so it is never a chip,
    never hidden behind a click, and the hide control is not drawn — a room
    with nothing over it has nothing for the composer to get out of the way
    of. A stale `open: false` left over from a finished hand is ignored here
    rather than repaired upstream, so there is one place that decides this.
  */
  const showChip = inGame && !open

  return (
    <footer
      className={`face-compose ${showChip ? 'is-chip' : ''}`}
      data-tour="room-composer"
    >
      {showChip ? (
        <button
          type="button"
          className="face-chip"
          onClick={() => onOpenChange(true)}
          title="Say something to Rau"
        >
          <span className="face-chip-dot" aria-hidden />
          talk to Rau
        </button>
      ) : (
        <>
          {error && (
            <p className="voice-note bad" role="alert">
              {error}
            </p>
          )}
          <div className="face-box">
            <input
              ref={inputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  void send()
                }
                if (e.key === 'Escape' && inGame) {
                  e.preventDefault()
                  e.stopPropagation()
                  onOpenChange(false)
                }
              }}
              placeholder={t('face.say')}
              aria-label="Message Rau"
              autoComplete="off"
              enterKeyHint="send"
            />
            <PermissionMenu />
            {inGame && (
              <button
                type="button"
                className="face-collapse"
                onClick={() => onOpenChange(false)}
                aria-label={t('face.hideChat')}
                title={t('face.hideChat')}
              >
                ⌄
              </button>
            )}
            <button
              type="button"
              className="face-send"
              disabled={!draft.trim() || sending}
              onClick={() => void send()}
              aria-label={t('talk.send')}
            >
              {sending ? <i className="spinner" /> : '→'}
            </button>
          </div>
        </>
      )}
    </footer>
  )
}
