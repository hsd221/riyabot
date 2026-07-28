export const ACCENT_PRESETS = {
  blue: {
    label: '蓝色',
    light: '211.29 100% 50%',
    dark: '210.12 100% 51.96%',
    swatch: '#007AFF',
    gradient: null,
  },
  purple: {
    label: '紫色',
    light: '240.94 60.95% 58.82%',
    dark: '240.87 73.4% 63.14%',
    swatch: 'linear-gradient(180deg, #706EF0 0%, #5856D6 100%)',
    gradient: null,
  },
  green: {
    label: '绿色',
    light: '135.1 58.57% 49.22%',
    dark: '134.91 63.64% 50.39%',
    swatch: 'linear-gradient(180deg, #4ADE6C 0%, #34C759 100%)',
    gradient: null,
  },
  orange: {
    label: '橙色',
    light: '35.06 100% 50%',
    dark: '36.49 100% 51.96%',
    swatch: 'linear-gradient(180deg, #FFAD32 0%, #FF9500 100%)',
    gradient: null,
  },
  pink: {
    label: '粉色',
    light: '348.57 100% 58.82%',
    dark: '348 100% 60.78%',
    swatch: 'linear-gradient(180deg, #FF5D86 0%, #FF2D55 100%)',
    gradient: null,
  },
  red: {
    label: '红色',
    light: '3.19 100% 59.41%',
    dark: '3.35 100% 61.37%',
    swatch: 'linear-gradient(180deg, #FF5A4F 0%, #FF3B30 100%)',
    gradient: null,
  },
  'gradient-sunset': {
    label: '日落',
    light: '35.06 100% 50%',
    dark: '36.49 100% 51.96%',
    swatch: 'linear-gradient(135deg, #FF9500 0%, #FF2D55 100%)',
    gradient: 'linear-gradient(135deg, #FF9500 0%, #FF2D55 100%)',
  },
  'gradient-ocean': {
    label: '海洋',
    light: '211.29 100% 50%',
    dark: '210.12 100% 51.96%',
    swatch: 'linear-gradient(135deg, #007AFF 0%, #5AC8FA 100%)',
    gradient: 'linear-gradient(135deg, #007AFF 0%, #5AC8FA 100%)',
  },
  'gradient-forest': {
    label: '森林',
    light: '135.1 58.57% 49.22%',
    dark: '134.91 63.64% 50.39%',
    swatch: 'linear-gradient(135deg, #34C759 0%, #00C7BE 100%)',
    gradient: 'linear-gradient(135deg, #34C759 0%, #00C7BE 100%)',
  },
  'gradient-aurora': {
    label: '极光',
    light: '240.94 60.95% 58.82%',
    dark: '240.87 73.4% 63.14%',
    swatch: 'linear-gradient(135deg, #5856D6 0%, #FF2D55 100%)',
    gradient: 'linear-gradient(135deg, #5856D6 0%, #FF2D55 100%)',
  },
  'gradient-fire': {
    label: '烈焰',
    light: '3.19 100% 59.41%',
    dark: '3.35 100% 61.37%',
    swatch: 'linear-gradient(135deg, #FF3B30 0%, #FF9500 100%)',
    gradient: 'linear-gradient(135deg, #FF3B30 0%, #FF9500 100%)',
  },
  'gradient-twilight': {
    label: '暮光',
    light: '240.94 60.95% 58.82%',
    dark: '240.87 73.4% 63.14%',
    swatch: 'linear-gradient(135deg, #5856D6 0%, #AF52DE 100%)',
    gradient: 'linear-gradient(135deg, #5856D6 0%, #AF52DE 100%)',
  },
} as const

export type AccentPresetKey = keyof typeof ACCENT_PRESETS
export const DEFAULT_ACCENT_COLOR: AccentPresetKey = 'blue'
export const SOLID_ACCENT_KEYS: AccentPresetKey[] = [
  'blue',
  'purple',
  'green',
  'orange',
  'pink',
  'red',
]
export const GRADIENT_ACCENT_KEYS: AccentPresetKey[] = [
  'gradient-sunset',
  'gradient-ocean',
  'gradient-forest',
  'gradient-aurora',
  'gradient-fire',
  'gradient-twilight',
]

const HEX_COLOR_PATTERN = /^#(?:[\da-f]{3}|[\da-f]{6})$/i

export function isAccentPreset(value: string): value is AccentPresetKey {
  return Object.prototype.hasOwnProperty.call(ACCENT_PRESETS, value)
}

export function normalizeHexColor(value: string): string | null {
  const trimmed = value.trim()
  if (!HEX_COLOR_PATTERN.test(trimmed)) return null

  const digits = trimmed.slice(1)
  const expanded =
    digits.length === 3
      ? digits
          .split('')
          .map((digit) => `${digit}${digit}`)
          .join('')
      : digits
  return `#${expanded.toUpperCase()}`
}

export function normalizeAccentColor(value: string): string | null {
  if (isAccentPreset(value)) return value
  return normalizeHexColor(value)
}

export function sanitizeAccentColor(value: string | null | undefined): string {
  return value ? (normalizeAccentColor(value) ?? DEFAULT_ACCENT_COLOR) : DEFAULT_ACCENT_COLOR
}

export function hexToHsl(value: string): string | null {
  const normalized = normalizeHexColor(value)
  if (!normalized) return null

  const red = Number.parseInt(normalized.slice(1, 3), 16) / 255
  const green = Number.parseInt(normalized.slice(3, 5), 16) / 255
  const blue = Number.parseInt(normalized.slice(5, 7), 16) / 255
  const maximum = Math.max(red, green, blue)
  const minimum = Math.min(red, green, blue)
  const lightness = (maximum + minimum) / 2
  let hue = 0
  let saturation = 0

  if (maximum !== minimum) {
    const delta = maximum - minimum
    saturation = lightness > 0.5 ? delta / (2 - maximum - minimum) : delta / (maximum + minimum)

    if (maximum === red) hue = (green - blue) / delta + (green < blue ? 6 : 0)
    if (maximum === green) hue = (blue - red) / delta + 2
    if (maximum === blue) hue = (red - green) / delta + 4
    hue /= 6
  }

  return `${Math.round(hue * 360)} ${Math.round(saturation * 100)}% ${Math.round(lightness * 100)}%`
}

export function getAccentSwatch(value: string): string {
  const normalized = normalizeAccentColor(value)
  if (!normalized) return ACCENT_PRESETS[DEFAULT_ACCENT_COLOR].swatch
  return isAccentPreset(normalized) ? ACCENT_PRESETS[normalized].swatch : normalized
}

export function applyAccentColor(
  value: string,
  root: HTMLElement = document.documentElement
): string {
  const normalized = sanitizeAccentColor(value)
  const preset = isAccentPreset(normalized) ? ACCENT_PRESETS[normalized] : null
  const primary = preset
    ? root.classList.contains('dark')
      ? preset.dark
      : preset.light
    : (hexToHsl(normalized) ?? ACCENT_PRESETS[DEFAULT_ACCENT_COLOR].light)

  root.style.setProperty('--primary', primary)
  root.style.setProperty('--ring', primary)

  if (preset?.gradient) {
    root.style.setProperty('--primary-gradient', preset.gradient)
    root.classList.add('has-gradient')
  } else {
    root.style.removeProperty('--primary-gradient')
    root.classList.remove('has-gradient')
  }

  return normalized
}
