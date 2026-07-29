/* oxlint-disable react/only-export-components -- provider and hook are one API */
import {
  Fragment,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, type Locale } from './api'
import { EN, type TranslationKey } from './locales/en'
import { KO } from './locales/ko'

export type { Locale } from './api'
export type { TranslationKey } from './locales/en'

export const LOCALE_KEY = 'rau.locale.v1'

const TABLES: Record<Locale, Record<TranslationKey, string>> = { en: EN, ko: KO }

type Values = Record<string, string | number>

function format(text: string, values: Values): string {
  for (const [name, value] of Object.entries(values)) {
    text = text.replaceAll(`{${name}}`, String(value))
  }
  return text
}

/**
 * The same substitution, but for sentences with an element inside them — a
 * `.env` in monospace, a link to the setup wizard.
 *
 * Written as one string with a placeholder rather than as two halves joined
 * around a tag, because the halves are not translatable: Korean puts the
 * particle after the noun and the verb at the end, so the fragment that
 * follows `{file}` in English has no counterpart to be the "second half" of.
 * Handing the translator the whole sentence lets the placeholder land wherever
 * that language actually puts it.
 */
function formatNodes(text: string, nodes: Record<string, ReactNode>): ReactNode[] {
  const out: ReactNode[] = []
  const pattern = /\{(\w+)\}/g
  let cursor = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) out.push(text.slice(cursor, match.index))
    const node = nodes[match[1]]
    out.push(
      node === undefined ? (
        match[0]
      ) : (
        <Fragment key={`${match[1]}-${match.index}`}>{node}</Fragment>
      ),
    )
    cursor = match.index + match[0].length
  }
  if (cursor < text.length) out.push(text.slice(cursor))
  return out
}

/**
 * The locale outside React.
 *
 * Card names, piece names and the slash-command list are plain modules that
 * hold no hook and are read from callbacks, memos and pure helpers. They still
 * have to speak the chosen language, so the provider mirrors its state here on
 * every change and those modules read it through `tr()`. Components continue
 * to go through `useLocale()`, which is what re-renders them; this mirror is
 * only ever read during a render the context has already scheduled.
 */
let activeLocale: Locale = 'en'

export function currentLocale(): Locale {
  return activeLocale
}

/** `t()` for modules that cannot hold a hook. Prefer `useLocale()` in components. */
export function tr(key: TranslationKey, values: Values = {}): string {
  return format(TABLES[activeLocale][key], values)
}

type LocaleContextValue = {
  locale: Locale
  hasChosenLocale: boolean
  setLocale: (locale: Locale) => Promise<void>
  t: (key: TranslationKey, values?: Values) => string
  /** `t()` for a sentence with an element in it. See `formatNodes`. */
  tx: (key: TranslationKey, nodes: Record<string, ReactNode>) => ReactNode[]
}

const LocaleContext = createContext<LocaleContextValue | null>(null)

function storedLocale(): Locale | null {
  try {
    const value = localStorage.getItem(LOCALE_KEY)
    return value === 'ko' || value === 'en' ? value : null
  } catch {
    return null
  }
}

/**
 * Start the Hangul webfonts downloading the moment we know the interface is
 * Korean, rather than when the first Korean glyph is painted.
 *
 * The `@font-face` rules are unicode-range-scoped so an English session never
 * touches these files; the cost of that is a Korean session only discovering
 * them once layout has already reached a Korean character, which is late
 * enough to show one frame of the system fallback. A preload closes that gap
 * without giving up the range scoping.
 */
function preloadHangul() {
  if (document.querySelector('link[data-hangul-preload]')) return
  for (const href of ['/fonts/pretendard-variable-hangul.woff2', '/fonts/nanum-myeongjo-hangul.woff2']) {
    const link = document.createElement('link')
    link.rel = 'preload'
    link.as = 'font'
    link.type = 'font/woff2'
    link.href = href
    link.crossOrigin = 'anonymous'
    link.dataset.hangulPreload = 'true'
    document.head.append(link)
  }
}

/**
 * Point the module-level mirror at a locale, and tag the document with it.
 *
 * `LocaleProvider` calls this on every change; it is exported so the modules
 * that read `tr()` can be tested without mounting a provider. Calling it alone
 * does not re-render anything — go through `setLocale` for that.
 */
export function setActiveLocale(locale: Locale) {
  activeLocale = locale
  // Guarded because this also runs at import time, and the unit tests import
  // these modules under node — where `tr()` is still worth having and a
  // document is not.
  if (typeof document === 'undefined') return
  document.documentElement.lang = locale
  if (locale === 'ko') preloadHangul()
}

// The stored choice applies before React mounts, so the first paint is already
// in the right language and the document is already tagged `lang="ko"` — the
// hook every Korean typographic rule in hangul.css hangs off.
setActiveLocale(storedLocale() || 'en')

export function LocaleProvider({ children }: { children: ReactNode }) {
  const initial = storedLocale()
  const [locale, setLocaleState] = useState<Locale>(initial || 'en')
  const [hasChosenLocale, setHasChosenLocale] = useState(initial !== null)

  useEffect(() => {
    setActiveLocale(locale)
  }, [locale])

  useEffect(() => {
    api
      .getLanguage()
      .then((result) => {
        if (!result.configured || storedLocale()) return
        setLocaleState(result.language)
        setHasChosenLocale(true)
        try {
          localStorage.setItem(LOCALE_KEY, result.language)
        } catch {
          /* in-memory locale remains valid */
        }
      })
      .catch(() => {})
  }, [])

  const setLocale = useCallback(async (next: Locale) => {
    setLocaleState(next)
    setHasChosenLocale(true)
    setActiveLocale(next)
    try {
      localStorage.setItem(LOCALE_KEY, next)
    } catch {
      /* backend remains the durable copy */
    }
    await api.putLanguage(next)
  }, [])

  const t = useCallback(
    (key: TranslationKey, values: Values = {}) => format(TABLES[locale][key], values),
    [locale],
  )

  const tx = useCallback(
    (key: TranslationKey, nodes: Record<string, ReactNode>) =>
      formatNodes(TABLES[locale][key], nodes),
    [locale],
  )

  const value = useMemo(
    () => ({ locale, hasChosenLocale, setLocale, t, tx }),
    [hasChosenLocale, locale, setLocale, t, tx],
  )
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale() {
  const value = useContext(LocaleContext)
  if (!value) throw new Error('useLocale must be used inside LocaleProvider')
  return value
}
