export type SafeStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem' | 'key' | 'length'>

export function getBrowserStorage(): SafeStorage | undefined {
  if (typeof window === 'undefined') return undefined

  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

export function safeGetItem(
  key: string,
  storage: SafeStorage | undefined = getBrowserStorage()
): string | null {
  try {
    return storage?.getItem(key) ?? null
  } catch {
    return null
  }
}

export function safeSetItem(
  key: string,
  value: string,
  storage: SafeStorage | undefined = getBrowserStorage()
): boolean {
  try {
    if (!storage) return false
    storage.setItem(key, value)
    return true
  } catch {
    return false
  }
}

export function safeRemoveItem(
  key: string,
  storage: SafeStorage | undefined = getBrowserStorage()
): boolean {
  try {
    if (!storage) return false
    storage.removeItem(key)
    return true
  } catch {
    return false
  }
}

export function safeStorageEntries(
  storage: SafeStorage | undefined = getBrowserStorage()
): Array<[string, string]> {
  if (!storage) return []

  try {
    const entries: Array<[string, string]> = []
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index)
      if (!key) continue
      const value = storage.getItem(key)
      if (value !== null) entries.push([key, value])
    }
    return entries
  } catch {
    return []
  }
}
