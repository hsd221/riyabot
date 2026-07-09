import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { ThemeProviderContext } from '@/lib/theme-context'
import { getSetting, setSetting, STORAGE_KEYS } from '@/lib/settings-manager'

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
    localStorage.getItem(storageKey) ??
    (storageKey === 'ui-theme' ? localStorage.getItem('riyabot-ui-theme') : null)
  if (isTheme(storedTheme) && storageKey === 'ui-theme') {
    localStorage.setItem(storageKey, storedTheme)
    localStorage.removeItem('riyabot-ui-theme')
  }
  return isTheme(storedTheme) ? storedTheme : defaultTheme
}

const applyTheme = (theme: Theme, systemTheme: 'dark' | 'light') => {
  const root = window.document.documentElement
  const resolvedTheme = theme === 'system' ? systemTheme : theme

  root.classList.remove('light', 'dark')
  root.classList.add(resolvedTheme)
  root.style.colorScheme = resolvedTheme
}

export function ThemeProvider({
  children,
  defaultTheme = 'system',
  storageKey = STORAGE_KEYS.THEME,
  ...props
}: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(
    () => (storageKey === STORAGE_KEYS.THEME ? getSetting('theme') : getStoredTheme(storageKey, defaultTheme))
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
    }

    const handleSettingsReset = () => setThemeState(getSetting('theme'))

    window.addEventListener('riyabot-settings-change', handleSettingsChange)
    window.addEventListener('riyabot-settings-reset', handleSettingsReset)
    return () => {
      window.removeEventListener('riyabot-settings-change', handleSettingsChange)
      window.removeEventListener('riyabot-settings-reset', handleSettingsReset)
    }
  }, [storageKey])

  // 应用保存的主题色
  useEffect(() => {
    const savedAccentColor = localStorage.getItem('accent-color')
    if (savedAccentColor) {
      const root = document.documentElement
      const colors = {
        blue: { 
          hsl: '211.29 100% 50%',
          darkHsl: '210.12 100% 51.96%',
          gradient: null
        },
        purple: { 
          hsl: '271 91% 65%', 
          darkHsl: '270 95% 75%',
          gradient: null
        },
        green: { 
          hsl: '142 71% 45%', 
          darkHsl: '142 76% 36%',
          gradient: null
        },
        orange: { 
          hsl: '25 95% 53%', 
          darkHsl: '20 90% 48%',
          gradient: null
        },
        pink: { 
          hsl: '330 81% 60%', 
          darkHsl: '330 85% 70%',
          gradient: null
        },
        red: { 
          hsl: '0 84% 60%', 
          darkHsl: '0 90% 70%',
          gradient: null
        },
        
        // 渐变色
        'gradient-sunset': { 
          hsl: '15 95% 60%', 
          darkHsl: '15 95% 65%',
          gradient: 'linear-gradient(135deg, hsl(25 95% 53%) 0%, hsl(330 81% 60%) 100%)'
        },
        'gradient-ocean': { 
          hsl: '200 90% 55%', 
          darkHsl: '200 90% 60%',
          gradient: 'linear-gradient(135deg, hsl(211.29 100% 50%) 0%, hsl(189 94% 43%) 100%)'
        },
        'gradient-forest': { 
          hsl: '150 70% 45%', 
          darkHsl: '150 75% 40%',
          gradient: 'linear-gradient(135deg, hsl(142 71% 45%) 0%, hsl(158 64% 52%) 100%)'
        },
        'gradient-aurora': { 
          hsl: '310 85% 65%', 
          darkHsl: '310 90% 70%',
          gradient: 'linear-gradient(135deg, hsl(271 91% 65%) 0%, hsl(330 81% 60%) 100%)'
        },
        'gradient-fire': { 
          hsl: '15 95% 55%', 
          darkHsl: '15 95% 60%',
          gradient: 'linear-gradient(135deg, hsl(0 84% 60%) 0%, hsl(25 95% 53%) 100%)'
        },
        'gradient-twilight': { 
          hsl: '250 90% 60%', 
          darkHsl: '250 95% 65%',
          gradient: 'linear-gradient(135deg, hsl(239 84% 67%) 0%, hsl(271 91% 65%) 100%)'
        },
      }

      const selectedColor = colors[savedAccentColor as keyof typeof colors]
      if (selectedColor) {
        const isDark = root.classList.contains('dark')
        root.style.setProperty('--primary', isDark ? selectedColor.darkHsl : selectedColor.hsl)
        
        // 设置渐变（如果有）
        if (selectedColor.gradient) {
          root.style.setProperty('--primary-gradient', selectedColor.gradient)
          root.classList.add('has-gradient')
        } else {
          root.style.removeProperty('--primary-gradient')
          root.classList.remove('has-gradient')
        }
      }
    }
  }, [theme, systemTheme])

  const value = {
    theme,
    resolvedTheme: theme === 'system' ? systemTheme : theme,
    setTheme: (theme: Theme) => {
      if (storageKey === STORAGE_KEYS.THEME) {
        setSetting('theme', theme)
      } else {
        localStorage.setItem(storageKey, theme)
      }
      setThemeState(theme)
    },
  }

  return (
    <ThemeProviderContext.Provider {...props} value={value}>
      {children}
    </ThemeProviderContext.Provider>
  )
}
