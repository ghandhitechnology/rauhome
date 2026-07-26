import { describe, expect, it } from 'vitest'

import { isPetShell } from './petBridge'

describe('petBridge outside a browser', () => {
  it('answers false instead of throwing when there is no window', () => {
    // The test host has no window at all; asking must be safe anyway, the
    // same way tauri() already guards its own read.
    expect(isPetShell()).toBe(false)
  })
})
