/**
 * That all twelve drawings actually come out.
 *
 * The set is a lot of hand-authored geometry hidden behind one component, and
 * the failure mode it invites is a shape that renders fine on the six squares
 * you happened to look at and throws on the seventh. Rendering every type in
 * both woods to a string is the cheapest possible guard against that: no DOM,
 * no canvas, just "does this function return markup".
 *
 * Two more things are pinned here because they are contracts rather than
 * drawings, and both have already been got wrong once. The finish is carried on
 * a data attribute and nowhere else — no piece file names a colour — so an
 * `<svg>` that lost the attribute would render every man in the same wood. And
 * every piece is `aria-hidden`, because the board carries the position as text
 * and thirty-two announced images would bury it.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import {
  ChessPiece,
  PieceDefs,
  PIECE_ANCHOR,
  PIECE_BASE,
  PIECE_HEIGHT,
  PIECE_TYPES,
  VIEW,
  type Finish,
} from './index'

const FINISHES: readonly Finish[] = ['maple', 'walnut']

describe('the set', () => {
  it('draws all six in both woods', () => {
    for (const type of PIECE_TYPES) {
      for (const finish of FINISHES) {
        const html = renderToStaticMarkup(<ChessPiece type={type} finish={finish} />)
        expect(html.startsWith('<svg')).toBe(true)
        // Something was actually carved, rather than an empty box returned.
        expect(html.length).toBeGreaterThan(400)
      }
    }
  })

  it('tells the stylesheet which wood each man is cut from', () => {
    for (const finish of FINISHES) {
      const html = renderToStaticMarkup(<ChessPiece type="k" finish={finish} />)
      expect(html).toContain(`data-chess-finish="${finish}"`)
    }
  })

  it('gives every man the same box, so the proportions survive', () => {
    for (const type of PIECE_TYPES) {
      const html = renderToStaticMarkup(<ChessPiece type={type} finish="maple" />)
      expect(html).toContain(`viewBox="0 0 ${VIEW.w} ${VIEW.h}"`)
    }
  })

  it('says nothing out loud', () => {
    for (const type of PIECE_TYPES) {
      const html = renderToStaticMarkup(<ChessPiece type={type} finish="walnut" />)
      expect(html).toContain('aria-hidden="true"')
    }
  })

  it('mounts the wood and the light once, for all of them', () => {
    // Without this at the board root every custom property the pieces fill
    // with is unresolved, and the whole set renders as flat black.
    const html = renderToStaticMarkup(<PieceDefs />)
    expect(html).toContain('data-chess-finish')
    expect(html.length).toBeGreaterThan(400)
  })
})

describe('the numbers the board places them by', () => {
  it('keeps the set in order of height', () => {
    const { p, r, n, b, q, k } = PIECE_HEIGHT
    expect(p).toBeLessThan(r)
    expect(r).toBeLessThan(n)
    expect(n).toBeLessThan(b)
    expect(b).toBeLessThan(q)
    expect(q).toBeLessThan(k)
  })

  it('stands every man inside the box he is drawn in', () => {
    for (const type of PIECE_TYPES) {
      // Measured from the contact line up, so a piece taller than the anchor
      // would be carved off the top of its own viewBox.
      expect(PIECE_HEIGHT[type]).toBeLessThanOrEqual(PIECE_ANCHOR.y)
      expect(PIECE_BASE[type] * 2).toBeLessThan(VIEW.w)
    }
  })

  it('puts the contact line on the floor of the box, not through it', () => {
    expect(PIECE_ANCHOR.y).toBeLessThanOrEqual(VIEW.h)
    expect(PIECE_ANCHOR.x).toBe(VIEW.w / 2)
  })
})
