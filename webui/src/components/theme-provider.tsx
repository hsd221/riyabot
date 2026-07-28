import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { applyAccentColor } from '@/lib/accent-color'
import { ThemeProviderContext } from '@/lib/theme-context'
import { getSetting, setSetting, STORAGE_KEYS } from '@/lib/settings-manager'
import { safeGetItem, safeRemoveItem, safeSetItem } from '@/lib/safe-storage'

type Theme = 'dark' | 'light' | 'system'

type ThemeProviderProps = {
  children: ReactNode
  defaultTheme?: Theme
  storageKey?: string
}

const isTheme = (value: string | null): value is Theme =>
  value === 'dark' || value === 'light' || value === 'system'

const getSystemTheme = (): 'dark' | 'light' => {
  if (typeof window === 'undefined' || !window.matchMedia) return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const getStoredTheme = (storageKey: string, defaultTheme: Theme): Theme => {
  const storedTheme =
    safeGetItem(storageKey) ??
    (storageKey === STORAGE_KEYS.THEME ? safeGetItem(STORAGE_KEYS.LEGACY_THEME) : null)

  if (isTheme(storedTheme) && storageKey === STORAGE_KEYS.THEME) {
    safeSetItem(storageKey, storedTheme)
    safeRemoveItem(STORAGE_KEYS.LEGACY_THEME)
  }
  return isTheme(storedTheme) ? storedTheme : defaultTheme
}

const applyTheme = (theme: Theme, systemTheme: 'dark' | 'light') => {
  const root = window.document.documentElement
  const resolvedTheme = theme === 'system' ? systemTheme : theme

  root.classList.remove('light', 'dark')
  root.classList.add(resolvedTheme)
  root.style.colorScheme = resolvedTheme
  applyAccentColor(getSetting('accentColor'), root)
}

export function ThemeProvider({
  children,
  defaultTheme = 'system',
  storageKey = STORAGE_KEYS.THEME,
  ...props
}: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(() =>
    storageKey === STORAGE_KEYS.THEME
      ? getSetting('theme')
      : getStoredTheme(storageKey, defaultTheme)
  )
  const [systemTheme, setSystemTheme] = useState<'dark' | 'light'>(() => getSystemTheme())

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handleSystemThemeChange = () => setSystemTheme(mediaQuery.matches ? 'dark' : 'light')

    handleSystemThemeChange()
    mediaQuery.addEventListener('change', handleSystemThemeChange)
    return () => mediaQuery.removeEventListener('change', handleSystemThemeChange)
  }, [])

  useEffect(() => {
    applyTheme(theme, systemTheme)
  }, [theme, systemTheme])

  useEffect(() => {
    if (storageKey !== STORAGE_KEYS.THEME) return

    const handleSettingsChange = (event: Event) => {
      const detail = (event as CustomEvent<{ key?: string; value?: unknown }>).detail
      if (detail?.key === 'theme' && isTheme(String(detail.value))) {
        setThemeState(detail.value as Theme)
      }
      if (detail?.key === 'accentColor') {
        applyAccentColor(String(detail.value))
      }
    }
    const handleSettingsReset = () => {
      setThemeState(getSetting('theme'))
      applyAccentColor(getSetting('accentColor'))
    }

    window.addEventListener('riyabot-settings-change', handleSettingsChange)
    window.addEventListener('riyabot-settings-reset', handleSettingsReset)
    return () => {
      window.removeEventListener('riyabot-settings-change', handleSettingsChange)
      window.removeEventListener('riyabot-settings-reset', handleSettingsReset)
    }
  }, [storageKey])

  const value = {
    theme,
    resolvedTheme: theme === 'system' ? systemTheme : theme,
    setTheme: (nextTheme: Theme) => {
      if (storageKey === STORAGE_KEYS.THEME) setSetting('theme', nextTheme)
      else safeSetItem(storageKey, nextTheme)
      setThemeState(nextTheme)
    },
  }

  return (
    <ThemeProviderContext.Provider {...props} value={value}>
      {children}
    </ThemeProviderContext.Provider>
  )
}
