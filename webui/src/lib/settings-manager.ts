/**
 * 前端设置管理器
 * 统一管理所有前端 localStorage 设置，并在受限存储环境中安全降级。
 */

import { safeGetItem, safeRemoveItem, safeSetItem, safeStorageEntries } from '@/lib/safe-storage'
import { sanitizeAccentColor } from '@/lib/accent-color'

export const STORAGE_KEYS = {
  THEME: 'ui-theme',
  LEGACY_THEME: 'riyabot-ui-theme',
  ACCENT_COLOR: 'accent-color',
  ENABLE_ANIMATIONS: 'riyabot-animations',

  LOG_CACHE_SIZE: 'riyabot-log-cache-size',
  LOG_AUTO_SCROLL: 'riyabot-log-auto-scroll',
  LOG_FONT_SIZE: 'riyabot-log-font-size',
  LOG_LINE_SPACING: 'riyabot-log-line-spacing',
  DATA_SYNC_INTERVAL: 'riyabot-data-sync-interval',
  WS_RECONNECT_INTERVAL: 'riyabot-ws-reconnect-interval',
  WS_MAX_RECONNECT_ATTEMPTS: 'riyabot-ws-max-reconnect-attempts',

  // ACCESS_TOKEN 已弃用，仅用于清理旧版本遗留数据。
  ACCESS_TOKEN: 'access-token',
  COMPLETED_TOURS: 'riyabot-completed-tours',
  CHAT_USER_ID: 'riyabot_console_user_id',
  CHAT_USER_NAME: 'riyabot_console_user_name',
} as const

const LEGACY_WAVES_STORAGE_KEYS = ['riyabot-waves-background', 'enable-waves-background']

export const DEFAULT_SETTINGS = {
  theme: 'system' as 'light' | 'dark' | 'system',
  accentColor: 'blue',
  enableAnimations: true,
  logCacheSize: 1000,
  logAutoScroll: true,
  logFontSize: 'xs' as 'xs' | 'sm' | 'base',
  logLineSpacing: 4,
  dataSyncInterval: 30,
  wsReconnectInterval: 3000,
  wsMaxReconnectAttempts: 10,
}

export type Settings = typeof DEFAULT_SETTINGS
export type ExportableSettings = Settings & {
  completedTours?: string[]
}

const isThemeValue = (value: string): value is Settings['theme'] =>
  value === 'light' || value === 'dark' || value === 'system'

const isLogFontSizeValue = (value: string): value is Settings['logFontSize'] =>
  value === 'xs' || value === 'sm' || value === 'base'

function cleanupLegacyWavesSetting(): void {
  LEGACY_WAVES_STORAGE_KEYS.forEach((key) => safeRemoveItem(key))
}

export function getSetting<K extends keyof Settings>(key: K): Settings[K] {
  const storageKey = getStorageKey(key)
  const currentValue = safeGetItem(storageKey)
  const legacyTheme = key === 'theme' ? safeGetItem(STORAGE_KEYS.LEGACY_THEME) : null
  const stored = currentValue ?? legacyTheme

  if (stored === null) return DEFAULT_SETTINGS[key]

  const defaultValue = DEFAULT_SETTINGS[key]

  if (key === 'theme') {
    if (!isThemeValue(stored)) return defaultValue
    if (currentValue === null) safeSetItem(STORAGE_KEYS.THEME, stored)
    if (legacyTheme !== null) safeRemoveItem(STORAGE_KEYS.LEGACY_THEME)
    return stored as Settings[K]
  }

  if (key === 'accentColor') {
    return sanitizeAccentColor(stored) as Settings[K]
  }

  if (key === 'logFontSize') {
    return (isLogFontSizeValue(stored) ? stored : DEFAULT_SETTINGS.logFontSize) as Settings[K]
  }

  if (typeof defaultValue === 'boolean') return (stored === 'true') as Settings[K]

  if (typeof defaultValue === 'number') {
    const parsed = Number.parseFloat(stored)
    return (Number.isNaN(parsed) ? defaultValue : parsed) as Settings[K]
  }

  return stored as Settings[K]
}

export function setSetting<K extends keyof Settings>(key: K, value: Settings[K]): void {
  const normalizedValue = key === 'accentColor' ? sanitizeAccentColor(String(value)) : value
  safeSetItem(getStorageKey(key), String(normalizedValue))
  if (key === 'theme') safeRemoveItem(STORAGE_KEYS.LEGACY_THEME)

  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('riyabot-settings-change', {
        detail: { key, value: normalizedValue },
      })
    )
  }
}

export function getAllSettings(): Settings {
  cleanupLegacyWavesSetting()
  return {
    theme: getSetting('theme'),
    accentColor: getSetting('accentColor'),
    enableAnimations: getSetting('enableAnimations'),
    logCacheSize: getSetting('logCacheSize'),
    logAutoScroll: getSetting('logAutoScroll'),
    logFontSize: getSetting('logFontSize'),
    logLineSpacing: getSetting('logLineSpacing'),
    dataSyncInterval: getSetting('dataSyncInterval'),
    wsReconnectInterval: getSetting('wsReconnectInterval'),
    wsMaxReconnectAttempts: getSetting('wsMaxReconnectAttempts'),
  }
}

export function exportSettings(): ExportableSettings {
  const completedToursValue = safeGetItem(STORAGE_KEYS.COMPLETED_TOURS)
  let completedTours: string[] = []

  if (completedToursValue) {
    try {
      const parsed = JSON.parse(completedToursValue)
      if (Array.isArray(parsed) && parsed.every((value) => typeof value === 'string')) {
        completedTours = parsed
      }
    } catch {
      // 损坏的引导记录不应阻止导出其他设置。
    }
  }

  return { ...getAllSettings(), completedTours }
}

export function importSettings(settings: Partial<ExportableSettings>): {
  success: boolean
  imported: string[]
  skipped: string[]
} {
  const imported: string[] = []
  const skipped: string[] = []

  for (const [key, value] of Object.entries(settings)) {
    if (key === 'completedTours') {
      if (Array.isArray(value) && value.every((item) => typeof item === 'string')) {
        safeSetItem(STORAGE_KEYS.COMPLETED_TOURS, JSON.stringify(value))
        imported.push(key)
      } else {
        skipped.push(key)
      }
      continue
    }

    if (!(key in DEFAULT_SETTINGS)) {
      skipped.push(key)
      continue
    }

    const settingKey = key as keyof Settings
    const defaultValue = DEFAULT_SETTINGS[settingKey]
    if (typeof value !== typeof defaultValue) {
      skipped.push(key)
      continue
    }
    if (settingKey === 'theme' && !isThemeValue(value as string)) {
      skipped.push(key)
      continue
    }
    if (settingKey === 'accentColor' && sanitizeAccentColor(value as string) !== value) {
      skipped.push(key)
      continue
    }
    if (settingKey === 'logFontSize' && !isLogFontSizeValue(value as string)) {
      skipped.push(key)
      continue
    }

    setSetting(settingKey, value as Settings[typeof settingKey])
    imported.push(key)
  }

  cleanupLegacyWavesSetting()
  return { success: imported.length > 0, imported, skipped }
}

export function resetAllSettings(): void {
  for (const key of Object.keys(DEFAULT_SETTINGS) as (keyof Settings)[]) {
    setSetting(key, DEFAULT_SETTINGS[key])
  }
  safeRemoveItem(STORAGE_KEYS.COMPLETED_TOURS)
  cleanupLegacyWavesSetting()
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('riyabot-settings-reset'))
}

export function clearLocalCache(): { clearedKeys: string[]; preservedKeys: string[] } {
  const clearedKeys: string[] = []

  for (const [key] of safeStorageEntries()) {
    if (
      key.startsWith('riyabot') ||
      key.startsWith('accent-color') ||
      key === STORAGE_KEYS.THEME ||
      key === STORAGE_KEYS.ACCESS_TOKEN ||
      key === 'enable-waves-background'
    ) {
      if (safeRemoveItem(key)) clearedKeys.push(key)
    }
  }

  return { clearedKeys, preservedKeys: [] }
}

export function getStorageUsage(): {
  used: number
  items: number
  details: { key: string; size: number }[]
} {
  const details = safeStorageEntries().map(([key, value]) => ({
    key,
    size: (key.length + value.length) * 2,
  }))
  details.sort((first, second) => second.size - first.size)

  return {
    used: details.reduce((total, item) => total + item.size, 0),
    items: details.length,
    details,
  }
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const base = 1024
  const sizes = ['B', 'KB', 'MB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(base)), sizes.length - 1)
  return `${Number.parseFloat((bytes / base ** index).toFixed(2))} ${sizes[index]}`
}

function getStorageKey(settingKey: keyof Settings): string {
  const keyMap: Record<keyof Settings, string> = {
    theme: STORAGE_KEYS.THEME,
    accentColor: STORAGE_KEYS.ACCENT_COLOR,
    enableAnimations: STORAGE_KEYS.ENABLE_ANIMATIONS,
    logCacheSize: STORAGE_KEYS.LOG_CACHE_SIZE,
    logAutoScroll: STORAGE_KEYS.LOG_AUTO_SCROLL,
    logFontSize: STORAGE_KEYS.LOG_FONT_SIZE,
    logLineSpacing: STORAGE_KEYS.LOG_LINE_SPACING,
    dataSyncInterval: STORAGE_KEYS.DATA_SYNC_INTERVAL,
    wsReconnectInterval: STORAGE_KEYS.WS_RECONNECT_INTERVAL,
    wsMaxReconnectAttempts: STORAGE_KEYS.WS_MAX_RECONNECT_ATTEMPTS,
  }
  return keyMap[settingKey]
}
