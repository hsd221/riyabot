import { describe, expect, it } from 'bun:test'
import {
  ACCENT_PRESETS,
  applyAccentColor,
  normalizeHexColor,
  sanitizeAccentColor,
} from '../src/lib/accent-color'

class FakeStyle {
  private values = new Map<string, string>()

  setProperty(name: string, value: string) {
    this.values.set(name, value)
  }

  removeProperty(name: string) {
    this.values.delete(name)
  }

  getPropertyValue(name: string) {
    return this.values.get(name) ?? ''
  }
}

class FakeClassList {
  private values = new Set<string>()

  add(name: string) {
    this.values.add(name)
  }

  remove(name: string) {
    this.values.delete(name)
  }

  contains(name: string) {
    return this.values.has(name)
  }
}

describe('accent color', () => {
  it('normalizes only supported hexadecimal values', () => {
    expect(normalizeHexColor('#0af')).toBe('#00AAFF')
    expect(normalizeHexColor('#12Ab90')).toBe('#12AB90')
    expect(normalizeHexColor('12ab90')).toBeNull()
    expect(normalizeHexColor('#abcd')).toBeNull()
    expect(normalizeHexColor('javascript:alert(1)')).toBeNull()
  })

  it('preserves valid presets and falls back for invalid stored values', () => {
    expect(sanitizeAccentColor('gradient-ocean')).toBe('gradient-ocean')
    expect(sanitizeAccentColor('#f0a')).toBe('#FF00AA')
    expect(sanitizeAccentColor('not-a-color')).toBe('blue')
  })

  it('applies primary, ring, and gradient state from one source', () => {
    const root = {
      style: new FakeStyle(),
      classList: new FakeClassList(),
    } as unknown as HTMLElement

    applyAccentColor('gradient-sunset', root)
    expect(root.style.getPropertyValue('--primary')).toBe(ACCENT_PRESETS['gradient-sunset'].light)
    expect(root.style.getPropertyValue('--ring')).toBe(ACCENT_PRESETS['gradient-sunset'].light)
    expect(root.style.getPropertyValue('--primary-gradient')).toBe(
      ACCENT_PRESETS['gradient-sunset'].gradient
    )
    expect(root.classList.contains('has-gradient')).toBe(true)

    applyAccentColor('#336699', root)
    expect(root.style.getPropertyValue('--primary')).toBe('210 50% 40%')
    expect(root.style.getPropertyValue('--ring')).toBe('210 50% 40%')
    expect(root.style.getPropertyValue('--primary-gradient')).toBe('')
    expect(root.classList.contains('has-gradient')).toBe(false)
  })
})
