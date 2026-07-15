const THEME_SELECTORS = { light: '', dark: '.dark' } as const

export type ChartTheme = keyof typeof THEME_SELECTORS

type ChartStyleItem = {
  color?: unknown
  theme?: Partial<Record<ChartTheme, unknown>>
}

type ChartStyleConfig = Readonly<Record<string, ChartStyleItem>>

// Keep every mapped token short enough that the `chart-` prefix remains idempotent
// when the style builder validates an already generated data attribute.
const MAX_SAFE_IDENTIFIER_LENGTH = 80
const MAX_ENCODED_CODE_POINTS = 10
const MAX_COLOR_LENGTH = 160

const SAFE_IDENTIFIER_RE = /^[a-z0-9_-]+$/i
const HEX_COLOR_RE = /^#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i
const CSS_UNSAFE_CHARACTER_RE = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u
const CSS_VARIABLE_NAME = '--[a-z0-9_-]{1,128}'
const CSS_NUMBER = '[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?%?'
const CSS_VARIABLE_RE = new RegExp(`^var\\(\\s*${CSS_VARIABLE_NAME}\\s*\\)$`, 'i')
const CSS_VARIABLE_ARGUMENTS_RE = new RegExp(
  `^var\\(\\s*${CSS_VARIABLE_NAME}\\s*\\)(?:\\s*\\/\\s*${CSS_NUMBER})?$`,
  'i'
)
const CSS_COLOR_FUNCTION_RE = /^(rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch)\((.*)\)$/i
const CSS_NUMERIC_ARGUMENTS_RE = /^[\d\s.,%+eE/-]+$/
const SAFE_NAMED_COLORS = new Set([
  'aqua',
  'black',
  'blue',
  'currentcolor',
  'fuchsia',
  'gray',
  'green',
  'grey',
  'lime',
  'maroon',
  'navy',
  'olive',
  'orange',
  'purple',
  'red',
  'silver',
  'teal',
  'transparent',
  'white',
  'yellow',
])

function hashIdentifier(value: string): string {
  let first = 0x811c9dc5
  let second = 0x9e3779b9

  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index)
    first = Math.imul(first ^ codeUnit, 0x01000193)
    second = Math.imul(second ^ codeUnit, 0x85ebca6b)
  }

  const firstHex = (first >>> 0).toString(16).padStart(8, '0')
  const secondHex = (second >>> 0).toString(16).padStart(8, '0')
  return `${value.length.toString(36)}-${firstHex}${secondHex}`
}

function toSafeIdentifier(value: string): string {
  if (value.length <= MAX_SAFE_IDENTIFIER_LENGTH && SAFE_IDENTIFIER_RE.test(value)) {
    return value
  }

  const codePoints = Array.from(value)
  if (codePoints.length === 0) {
    return 'encoded-empty'
  }
  if (codePoints.length > MAX_ENCODED_CODE_POINTS) {
    return `encoded-long-${hashIdentifier(value)}`
  }

  const encoded = codePoints
    .map((character) => character.codePointAt(0)?.toString(16).padStart(6, '0'))
    .join('')
  return `encoded-${encoded}`
}

export function getChartId(value: string): string {
  return `chart-${toSafeIdentifier(value)}`
}

export function getChartColorVariable(key: string): string {
  return `var(--color-${toSafeIdentifier(key)})`
}

export function sanitizeChartColor(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }

  const color = value.trim()
  if (!color || color.length > MAX_COLOR_LENGTH || CSS_UNSAFE_CHARACTER_RE.test(color)) {
    return null
  }
  if (HEX_COLOR_RE.test(color) || SAFE_NAMED_COLORS.has(color.toLowerCase())) {
    return color
  }
  if (CSS_VARIABLE_RE.test(color)) {
    return color
  }

  const functionMatch = CSS_COLOR_FUNCTION_RE.exec(color)
  if (!functionMatch) {
    return null
  }

  const argumentsText = functionMatch[2].trim()
  if (CSS_VARIABLE_ARGUMENTS_RE.test(argumentsText)) {
    return color
  }
  if (
    !argumentsText ||
    !/\d/.test(argumentsText) ||
    !CSS_NUMERIC_ARGUMENTS_RE.test(argumentsText)
  ) {
    return null
  }

  return color
}

export function buildChartStyle(id: string, config: ChartStyleConfig): string {
  const selectorId = toSafeIdentifier(id)

  return Object.entries(THEME_SELECTORS)
    .map(([theme, prefix]) => {
      const declarations = Object.entries(config).flatMap(([key, itemConfig]) => {
        if (!itemConfig || typeof itemConfig !== 'object') {
          return []
        }

        const themeColor = itemConfig.theme?.[theme as ChartTheme]
        const color = sanitizeChartColor(themeColor || itemConfig.color)
        if (!color) {
          return []
        }

        const property = getChartColorVariable(key).slice(4, -1)
        return [`  ${property}: ${color};`]
      })

      if (declarations.length === 0) {
        return ''
      }

      const selectorPrefix = prefix ? `${prefix} ` : ''
      return `${selectorPrefix}[data-chart="${selectorId}"] {\n${declarations.join('\n')}\n}`
    })
    .filter(Boolean)
    .join('\n')
}
