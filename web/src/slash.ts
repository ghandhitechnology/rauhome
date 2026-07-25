/** Shared slash-command parsing for Talk composer + chat bubbles. */

export type SlashCmd = {
  name: string
  slash: string
  description: string
}

export const META_COMMANDS: SlashCmd[] = [
  { name: 'skills', slash: '/skills', description: 'List always-on skills' },
  { name: 'effort', slash: '/effort', description: 'Set effort: low · medium · high · max' },
]

export type SlashDraft = {
  token: string
  arg: string
  hasSpace: boolean
}

export function readSlashDraft(text: string): SlashDraft | null {
  const raw = text || ''
  if (!raw.startsWith('/')) return null
  const body = raw.slice(1)
  const sp = body.search(/\s/)
  if (sp === -1) {
    return {
      token: body.toLowerCase().replace(/_/g, '-'),
      arg: '',
      hasSpace: false,
    }
  }
  return {
    token: body.slice(0, sp).toLowerCase().replace(/_/g, '-'),
    arg: body.slice(sp + 1),
    hasSpace: true,
  }
}

export function normalizeCmdName(name: string): string {
  return name.toLowerCase().replace(/_/g, '-')
}

/** Resolve a finished/known slash from a sent message. */
export function matchSlash(
  text: string,
  commands: SlashCmd[],
): { cmd: SlashCmd; arg: string } | null {
  const draft = readSlashDraft((text || '').trim())
  if (!draft?.token) return null
  const hit = commands.find(
    (c) =>
      normalizeCmdName(c.name) === draft.token ||
      normalizeCmdName(c.slash.replace(/^\//, '')) === draft.token,
  )
  if (!hit) return null
  return { cmd: hit, arg: draft.arg.trim() }
}

export function filterSlashCommands(commands: SlashCmd[], token: string): SlashCmd[] {
  const t = normalizeCmdName(token)
  if (!t) return commands
  return commands.filter((c) => {
    const name = normalizeCmdName(c.name)
    const slash = normalizeCmdName(c.slash.replace(/^\//, ''))
    return name.startsWith(t) || slash.startsWith(t) || name.includes(t)
  })
}

export function mergeSkillCommands(skills: { name?: string; slash?: string; description?: string }[]): SlashCmd[] {
  const fromSkills: SlashCmd[] = (skills || []).map((s) => ({
    name: s.name || 'skill',
    slash: s.slash || `/${s.name}`,
    description: s.description || '',
  }))
  const seen = new Set(fromSkills.map((c) => normalizeCmdName(c.name)))
  const metas = META_COMMANDS.filter((m) => !seen.has(normalizeCmdName(m.name)))
  return [...metas, ...fromSkills].sort((a, b) => a.slash.localeCompare(b.slash))
}
