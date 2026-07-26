/**
 * When a pause means "your turn" and when it means "hang on, I'm thinking".
 *
 * A fixed silence timeout cannot tell those apart, and picking one number
 * makes both cases worse: short enough to feel responsive after "what time is
 * it?" is short enough to cut someone off mid-sentence, and long enough to let
 * them think is long enough to feel like Rau is asleep.
 *
 * Energy alone cannot distinguish them either — the two pauses sound
 * identical. What differs is the *words* on either side of them, and the STT
 * partial gives us those for free, a beat before the silence has run out. So
 * the endpointer reads the transcript so far and shortens or lengthens the
 * wait accordingly.
 *
 * This is deliberately a set of shallow textual rules rather than a model.
 * Being wrong is cheap in one direction (a slightly long pause) and expensive
 * in the other (talking over someone), so every rule here defaults to waiting.
 */

/** How finished the thing the user just said sounds. */
export type Endpoint = 'complete' | 'neutral' | 'continuing'

/**
 * Words that almost never end a sentence.
 *
 * Trailing conjunctions and prepositions are the strongest signal available
 * that someone is mid-thought: "I was going to ask about—" then a pause is a
 * person searching for a word, not a person waiting for an answer.
 */
const DANGLING = new Set([
  'and',
  'but',
  'or',
  'so',
  'because',
  'if',
  'when',
  'while',
  'that',
  'which',
  'the',
  'a',
  'an',
  'to',
  'of',
  'for',
  'with',
  'about',
  'from',
  'in',
  'on',
  'at',
  'is',
  'are',
  'was',
  'were',
  'my',
  'your',
  'like',
  'just',
])

/** Sounds people make *instead* of finishing — the clearest "still going". */
const FILLERS = new Set(['um', 'uh', 'er', 'erm', 'hmm', 'hm', 'mm', 'eh', 'ah'])

/**
 * Openers that promise a longer sentence.
 *
 * "Can you" is never the whole request, so the pause after it is someone
 * composing the rest of it.
 */
const OPENERS = [
  'can you',
  'could you',
  'would you',
  'i want',
  'i need',
  'i was',
  'i wanted',
  'what if',
  'how do i',
  'tell me about',
  'do you know',
]

/** Strip trailing punctuation and whitespace without touching the words. */
function words(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s'?.!,]/gu, ' ')
    .split(/\s+/)
    .filter(Boolean)
}

/**
 * Read a partial transcript and say how finished it sounds.
 *
 * `neutral` is the honest answer far more often than either extreme, and it
 * maps to the old fixed behaviour — so a transcript this cannot read leaves
 * endpointing exactly as it was.
 */
export function classifyEndpoint(partial: string): Endpoint {
  const text = (partial ?? '').trim()
  if (!text) return 'neutral'

  const list = words(text)
  if (!list.length) return 'neutral'
  const last = list[list.length - 1].replace(/[?.!,]+$/u, '')

  // Someone audibly still looking for the word.
  if (FILLERS.has(last)) return 'continuing'
  if (DANGLING.has(last)) return 'continuing'
  // A trailing comma is a held breath, not an ending.
  if (/,$/.test(text)) return 'continuing'

  // Two words in is almost never a whole thought, unless it is a question or
  // one of the short replies a conversation actually runs on.
  const SHORT_COMPLETE = new Set(['yes', 'no', 'yeah', 'nope', 'sure', 'okay', 'ok', 'thanks', 'stop'])
  if (list.length <= 2 && !/[?.!]$/.test(text) && !SHORT_COMPLETE.has(list[0])) {
    return 'continuing'
  }

  const lowered = list.join(' ')
  if (list.length <= 4 && OPENERS.some((o) => lowered.startsWith(o))) return 'continuing'

  // Explicit terminal punctuation from the STT backend is the one signal that
  // is worth more than any of the above.
  if (/[?.!]$/.test(text)) return 'complete'
  // A question that the backend did not punctuate.
  if (list.length >= 3 && /^(what|when|where|who|why|how|is|are|do|does|did|can|should)$/.test(list[0])) {
    return 'neutral'
  }
  return 'neutral'
}

/** Silence multipliers, applied to the VAD's base hangover. */
export const ENDPOINT_SCALE: Record<Endpoint, number> = {
  // A finished question does not need most of half a second of proof.
  complete: 0.5,
  neutral: 1,
  // Long enough to find a word, short enough not to feel abandoned.
  continuing: 1.9,
}
