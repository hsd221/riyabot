import { describe, expect, it } from 'bun:test'

describe('Dashboard refresh behavior', () => {
  it('subscribes to the data sync setting and rebuilds the interval', async () => {
    const source = await Bun.file(new URL('../src/routes/index.tsx', import.meta.url)).text()

    expect(source).toContain("detail?.key === 'dataSyncInterval'")
    expect(source).toContain(
      "window.addEventListener('riyabot-settings-change', handleSettingsChange)"
    )
    expect(source).toContain(
      'window.setInterval(() => void refreshAll(true), refreshInterval * 1000)'
    )
    expect(source).toContain('[autoRefresh, refreshAll, refreshInterval]')
  })

  it('keeps stale data visible when a background refresh fails', async () => {
    const source = await Bun.file(new URL('../src/routes/index.tsx', import.meta.url)).text()

    expect(source).toContain('刷新未完成，当前仍显示上次成功获取的数据。{error}')
    expect(source).toContain("title: '自动刷新失败'")
    expect(source).toContain('setError(null)')
  })
})
