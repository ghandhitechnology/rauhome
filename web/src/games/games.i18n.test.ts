/**
 * The two tables speak the reader's language.
 *
 * Both games name their pieces from plain modules rather than from a hook, so
 * nothing re-renders them when the language changes — they read the locale at
 * call time instead. That is easy to regress by hoisting a name into a
 * module-level constant, and the failure is invisible in English.
 */
import { afterAll, describe, expect, it } from 'vitest'
import { setActiveLocale } from '../i18n'
import { cardMeta, cardTitle } from './kittens/meta'
import { pieceLabel, pieceName, squareLabel } from './chess/meta'

afterAll(() => setActiveLocale('en'))

describe('game vocabulary follows the locale', () => {
  it('names cards in the active language', () => {
    setActiveLocale('en')
    expect(cardTitle('exploding_kitten')).toBe('Exploding Kitten')
    expect(cardMeta('defuse').effect).toMatch(/kitten/)

    setActiveLocale('ko')
    expect(cardTitle('exploding_kitten')).toBe('폭탄 고양이')
    expect(cardMeta('defuse').effect).toMatch(/[가-힣]/)
    // A cat card's effect is the shared "does nothing alone" line.
    expect(cardMeta('tacocat').effect).toBe(cardMeta('beard_cat').effect)
  })

  it('leaves an unknown card id alone', () => {
    setActiveLocale('ko')
    expect(cardTitle('not_a_card')).toBe('not_a_card')
  })

  it('names pieces and squares in the active language', () => {
    const knight = { square: 'e4', color: 'white', type: 'n' } as const

    setActiveLocale('en')
    expect(pieceName('n')).toBe('knight')
    expect(pieceLabel(knight)).toBe('white knight')
    expect(squareLabel('e4', undefined)).toBe('e4, empty')

    setActiveLocale('ko')
    expect(pieceName('n')).toBe('나이트')
    expect(pieceLabel(knight)).toBe('백 나이트')
    expect(squareLabel('e4', knight)).toBe('e4, 백 나이트')
    expect(squareLabel('e4', undefined)).toBe('e4, 빈 칸')
  })
})
