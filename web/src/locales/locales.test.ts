import { describe, expect, it } from 'vitest'
import { EN, type TranslationKey } from './en'
import { KO } from './ko'

const KEYS = Object.keys(EN) as TranslationKey[]

/** `{name}` slots, which have to survive translation or `t()` interpolates nothing. */
function slots(text: string): string[] {
  return [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()
}

/** Strings that are the same in both languages on purpose. */
const SHARED = new Set<TranslationKey>([
  'setup.welcomeTitle', // the name
  'talk.rau',
  'ek.rau',
  'face.back', // "← Rau"
  // Both languages happen to name a piece in the same order: 백 나이트.
  'chess.pieceLabel',
  'chess.squareLabel',
  'language.english', // the Settings switcher names each language in its own script
  'language.korean',
  'language.greeting',
  'stat.mcp',
  'ops.cron',
  'mood.idle',
])

describe('translation tables', () => {
  it('covers every key', () => {
    expect(Object.keys(KO).sort()).toEqual(KEYS.slice().sort())
  })

  it('keeps every interpolation slot', () => {
    for (const key of KEYS) {
      expect(slots(KO[key]), `slots differ for ${key}`).toEqual(slots(EN[key]))
    }
  })

  it('actually translates', () => {
    const untranslated = KEYS.filter((key) => !SHARED.has(key) && KO[key] === EN[key])
    expect(untranslated).toEqual([])
  })

  /*
    The em dash is a Latin mark. Dropped into a Hangul line it reads as
    punctuation borrowed from another alphabet, and it is the tell that a
    string was transposed from English rather than written in Korean. The
    middle dot does that job here.
  */
  it('uses no em dashes in Korean', () => {
    const withDash = KEYS.filter((key) => KO[key].includes('—'))
    expect(withDash).toEqual([])
  })

  it('leaves no Latin sentence in a Korean string', () => {
    // Product nouns are fine (Rau, ElevenLabs, soul.md); a clause is not.
    const englishClause = /\b(the|and|with|your|this|that|from)\b/i
    const leftovers = KEYS.filter(
      (key) => !SHARED.has(key) && /[가-힣]/.test(KO[key]) && englishClause.test(KO[key]),
    )
    expect(leftovers).toEqual([])
  })
})
