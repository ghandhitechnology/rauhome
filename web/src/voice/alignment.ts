/**
 * Where a spoken reply has got to.
 *
 * The hub sends one `say_align` per sentence: its text, where the sentence
 * starts in the reply's audio timeline, and when each of its characters starts
 * within it. Audio arrives over the socket seconds before it is heard, so a
 * body cue anchored to a phrase has to be matched against playback position,
 * not against arrival.
 */

/** One spoken sentence, placed in the reply's own audio timeline. */
export type AlignedSentence = {
  turnId: string
  text: string
  /** Where this sentence starts, milliseconds into the reply. */
  offsetMs: number
  durationMs: number
  /** When each character of `text` starts, milliseconds into the sentence. */
  charMs: number[]
}

/**
 * How much of the reply has actually been heard by `playedMs`.
 *
 * Sentences already past are whole; the one in flight is revealed character by
 * character against its own timestamps. Sentences are rejoined with a single
 * space, which is how they were split — phrase matching normalises whitespace,
 * so that is enough to match a phrase spanning a sentence boundary.
 */
export function spokenSoFar(sentences: AlignedSentence[], playedMs: number): string {
  const parts: string[] = []
  for (const sentence of sentences) {
    if (playedMs >= sentence.offsetMs + sentence.durationMs) {
      parts.push(sentence.text)
      continue
    }
    if (playedMs <= sentence.offsetMs) break
    const local = playedMs - sentence.offsetMs
    let count = 0
    while (count < sentence.charMs.length && sentence.charMs[count] <= local) count++
    if (count > 0) parts.push(sentence.text.slice(0, count))
    break
  }
  return parts.join(' ')
}

/**
 * The sentence the ear is in — last sentence whose audio has started.
 *
 * Used for Face speech bubbles so captions track playback, not synth arrival.
 */
export function spokenSentence(sentences: AlignedSentence[], playedMs: number): string {
  let current = ''
  for (const sentence of sentences) {
    // Match spokenSoFar: nothing is "current" until playback has entered
    // the sentence (strictly past its offset).
    if (playedMs <= sentence.offsetMs) break
    current = sentence.text
  }
  return current
}

/**
 * The audible prefix of the sentence currently reaching the speaker.
 *
 * Unlike `spokenSentence`, this does not expose a sentence in full at its
 * first sample. Face uses it for a genuinely streaming speech bubble while
 * Conversation continues to use the cumulative `spokenSoFar` reply.
 */
export function spokenSentenceSoFar(
  sentences: AlignedSentence[],
  playedMs: number,
): string {
  let current: AlignedSentence | null = null
  for (const sentence of sentences) {
    if (playedMs <= sentence.offsetMs) break
    current = sentence
  }
  if (!current) return ''
  if (playedMs >= current.offsetMs + current.durationMs) return current.text
  if (!current.charMs.length) return ''

  const local = playedMs - current.offsetMs
  let count = 0
  while (count < current.charMs.length && current.charMs[count] <= local) count++
  return current.text.slice(0, count)
}
