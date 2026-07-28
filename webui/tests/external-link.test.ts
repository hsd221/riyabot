import { afterEach, describe, expect, it, mock } from 'bun:test'
import { getSafeExternalUrl, openExternalLink } from '../src/lib/external-link'

const originalWindow = globalThis.window

afterEach(() => {
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: originalWindow,
  })
})

describe('safe external links', () => {
  it('allows absolute HTTPS URLs and rejects unsafe protocols', () => {
    expect(getSafeExternalUrl('https://example.com/docs')?.href).toBe('https://example.com/docs')
    expect(getSafeExternalUrl('http://example.com')).toBeNull()
    expect(getSafeExternalUrl('http://localhost:8001', { allowHttp: true })?.href).toBe(
      'http://localhost:8001/'
    )
    expect(getSafeExternalUrl('javascript:alert(1)')).toBeNull()
    expect(getSafeExternalUrl('/relative/path')).toBeNull()
  })

  it('opens valid links with opener isolation', () => {
    const openedWindow = { opener: 'source' }
    const open = mock(() => openedWindow)
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: { open },
    })

    expect(openExternalLink('https://example.com/docs')).toBe(true)
    expect(open).toHaveBeenCalledWith('https://example.com/docs', '_blank', 'noopener,noreferrer')
    expect(openedWindow.opener).toBeNull()
  })

  it('does not call window.open for rejected URLs', () => {
    const open = mock(() => null)
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: { open },
    })

    expect(openExternalLink('data:text/html,bad')).toBe(false)
    expect(open).not.toHaveBeenCalled()
  })
})
