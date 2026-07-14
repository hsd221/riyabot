import { useEffect, useLayoutEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { AnimationContext } from '@/lib/animation-context'
import {
  readStoredBoolean,
  REDUCED_MOTION_QUERY,
  resolveMotionMode,
  writeStoredBoolean,
} from '@/lib/motion'
import { STORAGE_KEYS } from '@/lib/settings-manager'

const LEGACY_ANIMATION_STORAGE_KEY = 'enable-animations'
const LEGACY_WAVES_STORAGE_KEY = 'enable-waves-background'

function getBrowserStorage(): Storage | undefined {
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

type AnimationProviderProps = {
  children: ReactNode
  defaultEnabled?: boolean
  defaultWavesEnabled?: boolean
  storageKey?: string
  wavesStorageKey?: string
}

export function AnimationProvider({
  children,
  defaultEnabled = true,
  defaultWavesEnabled = true,
  storageKey = STORAGE_KEYS.ENABLE_ANIMATIONS,
  wavesStorageKey = STORAGE_KEYS.ENABLE_WAVES_BACKGROUND,
}: AnimationProviderProps) {
  const [enableAnimations, setEnableAnimations] = useState<boolean>(() => {
    const legacyKey =
      storageKey === STORAGE_KEYS.ENABLE_ANIMATIONS ? LEGACY_ANIMATION_STORAGE_KEY : undefined
    return readStoredBoolean(getBrowserStorage(), storageKey, legacyKey, defaultEnabled)
  })

  const [enableWavesBackground, setEnableWavesBackground] = useState<boolean>(() => {
    const legacyKey =
      wavesStorageKey === STORAGE_KEYS.ENABLE_WAVES_BACKGROUND
        ? LEGACY_WAVES_STORAGE_KEY
        : undefined
    return readStoredBoolean(getBrowserStorage(), wavesStorageKey, legacyKey, defaultWavesEnabled)
  })

  const [prefersReducedMotion, setPrefersReducedMotion] = useState(
    () => window.matchMedia?.(REDUCED_MOTION_QUERY).matches ?? false
  )

  const motionMode = resolveMotionMode(enableAnimations, prefersReducedMotion)

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

  useEffect(() => {
    const legacyKey =
      wavesStorageKey === STORAGE_KEYS.ENABLE_WAVES_BACKGROUND
        ? LEGACY_WAVES_STORAGE_KEY
        : undefined
    writeStoredBoolean(getBrowserStorage(), wavesStorageKey, enableWavesBackground, legacyKey)
  }, [enableWavesBackground, wavesStorageKey])

  const value = useMemo(
    () => ({
      enableAnimations,
      setEnableAnimations,
      enableWavesBackground,
      setEnableWavesBackground,
    }),
    [enableAnimations, enableWavesBackground]
  )

  return <AnimationContext.Provider value={value}>{children}</AnimationContext.Provider>
}
