import { describe, expect, it } from 'bun:test'

import {
  readStoredBoolean,
  resolveMotionMode,
  resolveStoredBoolean,
  writeStoredBoolean,
} from '../src/lib/motion'

describe('resolveMotionMode', () => {
  it('disables decorative motion when the user turns animations off', () => {
    expect(resolveMotionMode(false, false)).toBe('none')
    expect(resolveMotionMode(false, true)).toBe('none')
  })

  it('uses reduced motion when the operating system requests it', () => {
    expect(resolveMotionMode(true, true)).toBe('reduced')
  })

  it('uses full motion when animations are enabled without a system restriction', () => {
    expect(resolveMotionMode(true, false)).toBe('full')
  })
})

describe('resolveStoredBoolean', () => {
  it('prefers the current setting over a legacy value', () => {
    expect(resolveStoredBoolean('false', 'true', true)).toBe(false)
  })

  it('uses the legacy value when the current setting is missing', () => {
    expect(resolveStoredBoolean(null, 'false', true)).toBe(false)
  })

  it('falls back when neither stored value is valid', () => {
    expect(resolveStoredBoolean(null, null, true)).toBe(true)
    expect(resolveStoredBoolean('unexpected', null, false)).toBe(false)
  })
})

describe('motion preference storage', () => {
  it('falls back instead of crashing when browser storage is unavailable', () => {
    const unavailableStorage = {
      getItem: () => {
        throw new DOMException('Storage is disabled', 'SecurityError')
      },
      setItem: () => undefined,
      removeItem: () => undefined,
    }

    expect(readStoredBoolean(unavailableStorage, 'current', 'legacy', false)).toBe(false)
  })

  it('keeps the legacy preference when writing the migrated value fails', () => {
    let removedLegacyValue = false
    const fullStorage = {
      getItem: () => null,
      setItem: () => {
        throw new DOMException('Quota exceeded', 'QuotaExceededError')
      },
      removeItem: () => {
        removedLegacyValue = true
      },
    }

    expect(() => writeStoredBoolean(fullStorage, 'current', true, 'legacy')).not.toThrow()
    expect(removedLegacyValue).toBe(false)
  })
})
