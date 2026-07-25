import { useEffect, useRef } from 'react'
import type { SlashCmd } from '../slash'
import './SlashMenu.css'

type Props = {
  open: boolean
  commands: SlashCmd[]
  activeIndex: number
  onHover: (index: number) => void
  onPick: (cmd: SlashCmd) => void
}

export default function SlashMenu({ open, commands, activeIndex, onHover, onPick }: Props) {
  const listRef = useRef<HTMLUListElement>(null)
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([])

  useEffect(() => {
    if (!open) return
    const el = itemRefs.current[activeIndex]
    const list = listRef.current
    if (!el || !list) return
    el.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [activeIndex, open, commands.length])

  if (!open || commands.length === 0) return null

  return (
    <div className="slash-menu" role="listbox" aria-label="Slash commands">
      <div className="slash-menu-head">Commands</div>
      <ul ref={listRef} className="slash-menu-list">
        {commands.map((cmd, i) => (
          <li key={cmd.slash}>
            <button
              ref={(node) => {
                itemRefs.current[i] = node
              }}
              type="button"
              role="option"
              aria-selected={i === activeIndex}
              className={`slash-menu-item ${i === activeIndex ? 'active' : ''}`}
              onMouseEnter={() => onHover(i)}
              onMouseDown={(e) => {
                e.preventDefault()
                onPick(cmd)
              }}
            >
              <code className="slash-menu-cmd">{cmd.slash}</code>
              <span className="slash-menu-desc">{cmd.description || cmd.name}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
