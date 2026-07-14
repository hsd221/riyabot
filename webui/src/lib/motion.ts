export const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'

export type MotionMode = 'full' | 'reduced' | 'none'

type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

export function resolveStoredBoolean(
  currentValue: string | null,
  legacyValue: string | null,
  fallback: boolean
): boolean {
  const storedValue = currentValue ?? legacyValue
  if (storedValue === 'true') return true
  if (storedValue === 'false') return false
  return fallback
}

export function readStoredBoolean(
  storage: PreferenceStorage | undefined,
  currentKey: string,
  legacyKey: string | undefined,
  fallback: boolean
): boolean {
  try {
    const currentValue = storage?.getItem(currentKey) ?? null
    const legacyValue =
      currentValue === null && legacyKey ? (storage?.getItem(legacyKey) ?? null) : null
    return resolveStoredBoolean(currentValue, legacyValue, fallback)
  } catch {
    return fallback
  }
}

export function writeStoredBoolean(
  storage: PreferenceStorage | undefined,
  currentKey: string,
  value: boolean,
  legacyKey?: string
): void {
  try {
    if (!storage) return
    storage.setItem(currentKey, String(value))
    if (legacyKey) storage.removeItem(legacyKey)
  } catch {
    // Storage can be unavailable in private browsing or restricted frames.
  }
}

export function resolveMotionMode(
  animationsEnabled: boolean,
  prefersReducedMotion: boolean
): MotionMode {
  if (!animationsEnabled) return 'none'
  return prefersReducedMotion ? 'reduced' : 'full'
}
