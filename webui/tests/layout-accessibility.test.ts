import { describe, expect, it } from 'bun:test'

describe('Layout accessibility contracts', () => {
  it('keeps the skip link off-screen until it receives focus', async () => {
    const source = await Bun.file(new URL('../src/components/layout.tsx', import.meta.url)).text()

    expect(source).toContain('href="#main-content"')
    expect(source).toContain('-translate-y-[calc(100%+1rem)]')
    expect(source).toContain('focus:translate-y-0')
  })
})
