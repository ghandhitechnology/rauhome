/**
 * The pending echo's hand-off to the hub log.
 *
 * The echo is a stand-in until the hub logs the message; recognising that
 * moment is anchored to the log entry that was last at send time, never to
 * an index — the hub trims the log at its cap, and an index captured at
 * send time slides past the slot the echo actually lands in.
 */
import { describe, expect, it } from 'vitest'

import { pendingEchoed, type PendingEcho } from './Conversation'

const user = (text: string, time: string) => ({ role: 'user', text, time })
const rau = (text: string, time: string) => ({ role: 'assistant', text, time })

function pending(text: string, anchor: PendingEcho['anchor']): PendingEcho {
  return { role: 'user', text, time: '12:00:02', anchor }
}

describe('the pending echo', () => {
  it('clears once the hub logs the sent message', () => {
    const log = [user('hi', '11:59:50'), rau('hello', '11:59:55'), user('yes', '12:00:02')]
    expect(pendingEchoed(log, pending('yes', rau('hello', '11:59:55')))).toBe(true)
  })

  it('keeps showing while the log has not caught up', () => {
    const log = [user('hi', '11:59:50'), rau('hello', '11:59:55')]
    expect(pendingEchoed(log, pending('yes', rau('hello', '11:59:55')))).toBe(false)
  })

  it('is not cleared by an older identical line — the twin “yes”', () => {
    // The first "yes" is still the log's tail when the second is sent, so it
    // is the anchor — and must not swallow the second one's echo.
    const log = [rau('draw?', '11:58:50'), user('yes', '11:59:00')]
    const anchor = user('yes', '11:59:00')
    expect(pendingEchoed(log, pending('yes', anchor))).toBe(false)

    log.push(user('yes', '12:00:02'))
    expect(pendingEchoed(log, pending('yes', anchor))).toBe(true)
  })

  it('still clears at the log cap, where the echo lands left of the send-time length', () => {
    // A full log: every send is appended and the head trimmed, so the anchor
    // slides left instead of sitting at length - 1. An index anchor of 100
    // would never match the echo at index 99; the entry anchor does.
    const log = Array.from({ length: 100 }, (_, i) =>
      rau(`line ${i}`, `10:${String(i).padStart(2, '0')}:00`),
    )
    const tail = log[log.length - 1]
    const anchor = { role: tail.role, text: tail.text, time: tail.time }

    log.shift()
    log.push(user('again', '12:00:02'))
    expect(pendingEchoed(log, pending('again', anchor))).toBe(true)
  })

  it('accepts any match once the anchor has aged out of the trimmed log', () => {
    // Everything still in the log arrived after the send, so a matching user
    // line can only be this echo.
    const log = [rau('busy room', '12:00:01'), user('yes', '12:00:02')]
    expect(pendingEchoed(log, pending('yes', rau('long gone', '09:00:00')))).toBe(true)
  })

  it('matches from the start when the log was empty at send time', () => {
    expect(pendingEchoed([user('hi', '12:00:02')], pending('hi', null))).toBe(true)
    expect(pendingEchoed([], pending('hi', null))).toBe(false)
  })

  it('is not cleared by Rau saying the same words', () => {
    const log = [rau('yes', '12:00:02')]
    expect(pendingEchoed(log, pending('yes', null))).toBe(false)
  })
})
