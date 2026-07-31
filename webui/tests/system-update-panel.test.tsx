import { describe, expect, it } from 'bun:test'

describe('system update panel', () => {
  it('keeps the channel selector accessible and update execution explicit', async () => {
    const source = await Bun.file(
      new URL('../src/components/system-update-panel.tsx', import.meta.url)
    ).text()

    expect(source).toContain('role="radiogroup"')
    expect(source).toContain('role="radio"')
    expect(source).toMatch(/<h2\s+id="system-update-heading"/)
    expect(source).toContain('aria-checked={channel === item.value}')
    expect(source).toContain('aria-label="重新检查更新"')
    expect(source).toContain('status.update_available && status.can_apply && status.target')
    expect(source).toContain('await createUpdateTask(status.target.revision)')
    expect(source).toContain('verifyRestartComplete=')
    expect(source).toContain('const result = await getUpdateResult()')
    expect(source).toContain('result.last_result?.success === true')
    expect(source).not.toContain('const refreshedStatus = await getUpdateStatus(true)')
  })

  it('keeps the saved channel selected when its remote check fails', async () => {
    const source = await Bun.file(
      new URL('../src/components/system-update-panel.tsx', import.meta.url)
    ).text()

    expect(source).toContain('setSelectedChannel(channel)')
    expect(source).toContain('setStatus(null)')
  })
})
