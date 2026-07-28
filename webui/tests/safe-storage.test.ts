import { describe, expect, it } from 'bun:test'
import {
  getBrowserStorage,
  safeGetItem,
  safeRemoveItem,
  safeSetItem,
  safeStorageEntries,
  type SafeStorage,
} from '../src/lib/safe-storage'

function createThrowingStorage(): SafeStorage {
  return {
    get length() {
      throw new Error('storage blocked')
    },
    getItem() {
      throw new Error('storage blocked')
    },
    key() {
      throw new Error('storage blocked')
    },
    removeItem() {
      throw new Error('storage blocked')
    },
    setItem() {
      throw new Error('storage blocked')
    },
  }
}

describe('safe storage', () => {
  it('returns a no-crash fallback when browser storage is unavailable', () => {
    expect(getBrowserStorage()).toBeUndefined()
    expect(safeGetItem('missing')).toBeNull()
    expect(safeSetItem('key', 'value')).toBe(false)
    expect(safeRemoveItem('key')).toBe(false)
    expect(safeStorageEntries()).toEqual([])
  })

  it('catches security and quota exceptions from storage implementations', () => {
    const storage = createThrowingStorage()
    expect(safeGetItem('key', storage)).toBeNull()
    expect(safeSetItem('key', 'value', storage)).toBe(false)
    expect(safeRemoveItem('key', storage)).toBe(false)
    expect(safeStorageEntries(storage)).toEqual([])
  })

  it('reads entries from a working storage implementation', () => {
    const values = new Map([
      ['theme', 'dark'],
      ['accent', 'blue'],
    ])
    const storage: SafeStorage = {
      get length() {
        return values.size
      },
      getItem(key) {
        return values.get(key) ?? null
      },
      key(index) {
        return Array.from(values.keys())[index] ?? null
      },
      removeItem(key) {
        values.delete(key)
      },
      setItem(key, value) {
        values.set(key, value)
      },
    }

    expect(safeStorageEntries(storage)).toEqual([
      ['theme', 'dark'],
      ['accent', 'blue'],
    ])
    expect(safeSetItem('density', 'comfortable', storage)).toBe(true)
    expect(safeGetItem('density', storage)).toBe('comfortable')
    expect(safeRemoveItem('density', storage)).toBe(true)
    expect(safeGetItem('density', storage)).toBeNull()
  })
})
