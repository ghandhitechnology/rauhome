import { describe, expect, it } from 'vitest'

import {
  filterSlashCommands,
  matchSlash,
  mergeSkillCommands,
  readSlashDraft,
  type SlashCmd,
} from './slash'

const commands: SlashCmd[] = [
  { name: 'effort', slash: '/effort', description: 'Set effort' },
  { name: 'web_search', slash: '/search', description: 'Search the web' },
]

describe('slash command parsing', () => {
  it('only treats a leading slash as a command draft', () => {
    expect(readSlashDraft('hello /effort')).toBeNull()
    expect(readSlashDraft('/WEB_SEARCH')).toEqual({
      token: 'web-search',
      arg: '',
      hasSpace: false,
    })
  })

  it('keeps the command argument after the first whitespace', () => {
    expect(readSlashDraft('/effort high priority')).toEqual({
      token: 'effort',
      arg: 'high priority',
      hasSpace: true,
    })
  })

  it('matches either a command name or its slash alias', () => {
    expect(matchSlash('  /effort high  ', commands)).toEqual({
      cmd: commands[0],
      arg: 'high',
    })
    expect(matchSlash('/search Rauhome', commands)).toEqual({
      cmd: commands[1],
      arg: 'Rauhome',
    })
    expect(matchSlash('/missing value', commands)).toBeNull()
  })

  it('filters normalized command names and preserves built-in commands when merging', () => {
    expect(filterSlashCommands(commands, 'web-s')).toEqual([commands[1]])

    const merged = mergeSkillCommands([
      { name: 'skills', slash: '/skills', description: 'Custom skills view' },
      { name: 'web_search', slash: '/search', description: 'Search the web' },
    ])
    expect(merged.filter((command) => command.name === 'skills')).toHaveLength(1)
    expect(merged.some((command) => command.name === 'effort')).toBe(true)
  })
})
