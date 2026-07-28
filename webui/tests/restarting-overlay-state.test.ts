import { describe, expect, it } from 'bun:test'

const routes = [
  '../src/routes/index.tsx',
  '../src/routes/config/bot.tsx',
  '../src/routes/config/model.tsx',
  '../src/routes/config/modelProvider.tsx',
]

describe('RestartingOverlay state contracts', () => {
  it('keeps the overlay visible so retry actions remain available', async () => {
    for (const route of routes) {
      const source = await Bun.file(new URL(route, import.meta.url)).text()
      const handler = source.match(/const handleRestartFailed = \(\) => \{([\s\S]*?)\n {2}\}/)?.[1]

      expect(handler).toBeDefined()
      expect(handler).not.toContain('setShowRestartOverlay(false)')
      expect(handler).toContain('setRestarting(false)')
      expect(source).toContain('onRestartFailed={handleRestartFailed}')
    }
  })

  it('does not restart polling when parent callbacks are recreated', async () => {
    const source = await Bun.file(
      new URL('../src/components/RestartingOverlay.tsx', import.meta.url)
    ).text()

    expect(source).toContain('onRestartCompleteRef.current = onRestartComplete')
    expect(source).toContain('onRestartFailedRef.current = onRestartFailed')
    expect(source).toContain('}, [cancelPolling])')
    expect(source).not.toContain('[cancelPolling, onRestartComplete, onRestartFailed]')
  })
})
