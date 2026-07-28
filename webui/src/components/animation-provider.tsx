import { useEffect, useLayoutEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { AnimationContext } from '@/lib/animation-context'
import {
  readStoredBoolean,
  REDUCED_MOTION_QUERY,
  resolveMotionMode,
  writeStoredBoolean,
} from '@/lib/motion'
import { getBrowserStorage, safeRemoveItem } from '@/lib/safe-storage'
import { STORAGE_KEYS } from '@/lib/settings-manager'

const LEGACY_ANIMATION_STORAGE_KEY = 'enable-animations'
const LEGACY_WAVES_STORAGE_KEYS = ['enable-waves-background', 'riyabot-waves-background']

type AnimationProviderProps = {
  children: ReactNode
  defaultEnabled?: boolean
  storageKey?: string
}

export function AnimationProvider({
  children,
  defaultEnabled = true,
  storageKey = STORAGE_KEYS.ENABLE_ANIMATIONS,
}: AnimationProviderProps) {
  const [enableAnimations, setEnableAnimations] = useState<boolean>(() => {
    const legacyKey =
      storageKey === STORAGE_KEYS.ENABLE_ANIMATIONS ? LEGACY_ANIMATION_STORAGE_KEY : undefined
    return readStoredBoolean(getBrowserStorage(), storageKey, legacyKey, defaultEnabled)
  })
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(
    () => window.matchMedia?.(REDUCED_MOTION_QUERY).matches ?? false
  )
  const motionMode = resolveMotionMode(enableAnimations, prefersReducedMotion)

  useEffect(() => {
    LEGACY_WAVES_STORAGE_KEYS.forEach((key) => safeRemoveItem(key))
  }, [])

  useEffect(() => {
    const mediaQuery = window.matchMedia(REDUCED_MOTION_QUERY)
    const handleChange = (event: MediaQueryListEvent) => setPrefersReducedMotion(event.matches)

    setPrefersReducedMotion(mediaQuery.matches)
    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [])

  useLayoutEffect(() => {
    const root = document.documentElement
    root.dataset.motion = motionMode
    root.classList.toggle('no-animations', motionMode === 'none')
  }, [motionMode])

  useEffect(() => {
    const legacyKey =
      storageKey === STORAGE_KEYS.ENABLE_ANIMATIONS ? LEGACY_ANIMATION_STORAGE_KEY : undefined
    writeStoredBoolean(getBrowserStorage(), storageKey, enableAnimations, legacyKey)
  }, [enableAnimations, storageKey])

  const value = useMemo(() => ({ enableAnimations, setEnableAnimations }), [enableAnimations])

  return <AnimationContext.Provider value={value}>{children}</AnimationContext.Provider>
}
