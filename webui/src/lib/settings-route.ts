export type SettingsTab = 'appearance' | 'security' | 'other' | 'about'

export function parseSettingsTab(value: unknown): SettingsTab | undefined {
  switch (value) {
    case 'appearance':
    case 'security':
    case 'other':
    case 'about':
      return value
    default:
      return undefined
  }
}
