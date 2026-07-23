import { describe, expect, it } from 'bun:test'

describe('Chat history import enrichment', () => {
  it('counts enrichment candidates while remaining compatible with older results', async () => {
    const { countHistoryCandidates } = await import('../src/lib/chat-history-import-view')

    expect(
      countHistoryCandidates({
        candidates: {
          expressions: [{}],
          behaviors: [{}, {}],
          jargons: [],
        },
      } as never)
    ).toEqual({ expressions: 1, behaviors: 2, jargons: 0, memories: 0, profiles: 0 })

    expect(
      countHistoryCandidates({
        candidates: {
          expressions: [],
          behaviors: [],
          jargons: [{}],
          memories: [{}, {}, {}],
          profiles: [{}, {}],
        },
      } as never)
    ).toEqual({ expressions: 0, behaviors: 0, jargons: 1, memories: 3, profiles: 2 })
  })

  it('keeps progress monotonic across both storage phases', async () => {
    const { chatHistoryProgressPercent } = await import('../src/lib/chat-history-import-view')

    const percentages = [
      chatHistoryProgressPercent('running', 'extracting', 1, 1),
      chatHistoryProgressPercent('running', 'consolidating', 1, 1),
      chatHistoryProgressPercent('running', 'storing', 1, 1),
      chatHistoryProgressPercent('running', 'storing_enrichment', 1, 1),
      chatHistoryProgressPercent('completed', 'completed', 1, 1),
    ]

    expect(percentages).toEqual([78, 90, 95, 99, 100])
  })

  it('exposes opt-in switches and submits both enrichment options', async () => {
    const pageSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-import.tsx', import.meta.url)
    ).text()
    const settingsSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-import-settings.tsx', import.meta.url)
    ).text()
    const resultSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-import-result.tsx', import.meta.url)
    ).text()

    expect(settingsSource).toContain('id="extract-history-memories"')
    expect(settingsSource).toContain('id="update-history-profiles"')
    expect(pageSource).toContain('extract_memories: extractMemories')
    expect(pageSource).toContain('update_profiles: updateProfiles')
    expect(pageSource).toContain("storing_enrichment: '正在写入记忆与未验证画像'")
    expect(resultSource).toContain("label: '聊天记忆'")
    expect(resultSource).toContain("label: '成员画像'")
  })

  it('keeps a cleanup action available after failure or cancellation', async () => {
    const pageSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-import.tsx', import.meta.url)
    ).text()

    expect(pageSource).toContain("activeTask.status === 'failed' || activeTask.status === 'cancelled'")
    expect(pageSource).toContain('删除任务记录')
    expect(pageSource).toContain('onClick={handleDelete}')
  })

  it('labels the upload control and avoids skipping heading levels in alerts', async () => {
    const pageSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-import.tsx', import.meta.url)
    ).text()
    const settingsSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-import-settings.tsx', import.meta.url)
    ).text()

    expect(pageSource).toContain('aria-label="选择 QQChatExporter JSON 聊天记录"')
    expect(pageSource).not.toContain('<AlertTitle')
    expect(settingsSource).not.toContain('<AlertTitle')
  })
})
