import { describe, expect, it } from 'bun:test'

describe('Chat history import enrichment', () => {
  it('counts enrichment candidates while remaining compatible with older results', async () => {
    const { countHistoryCandidates, countHistoryCatalogCandidates } =
      await import('../src/lib/chat-history-import-view')

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

    expect(
      countHistoryCatalogCandidates({
        candidates: { expressions: [], behaviors: [], jargons: [] },
        candidate_catalog: {
          total: 42,
          counts: { expressions: 31, behaviors: 4, jargons: 7, memories: 0, profiles: 0 },
          complete: true,
          incomplete_window_ids: [],
          storage: 'paged',
        },
      } as never)
    ).toEqual({ expressions: 31, behaviors: 4, jargons: 7, memories: 0, profiles: 0 })
  })

  it('keeps progress monotonic across every commit phase', async () => {
    const { chatHistoryProgressPercent } = await import('../src/lib/chat-history-import-view')

    const percentages = [
      chatHistoryProgressPercent('running', 'extracting', 1, 1),
      chatHistoryProgressPercent('running', 'consolidating', 1, 1),
      chatHistoryProgressPercent('running', 'storing_catalog', 1, 1),
      chatHistoryProgressPercent('running', 'storing', 1, 1),
      chatHistoryProgressPercent('running', 'storing_enrichment', 1, 1),
      chatHistoryProgressPercent('completed', 'completed', 1, 1),
    ]

    expect(percentages).toEqual([78, 90, 93, 96, 99, 100])
  })

  it('allows cancellation before commit but locks every commit phase', async () => {
    const { canCancelChatHistoryImport } = await import('../src/lib/chat-history-import-view')

    expect(canCancelChatHistoryImport('running', 'extracting')).toBe(true)
    expect(canCancelChatHistoryImport('running', 'consolidating')).toBe(true)
    expect(canCancelChatHistoryImport('running', 'storing_catalog')).toBe(false)
    expect(canCancelChatHistoryImport('running', 'storing')).toBe(false)
    expect(canCancelChatHistoryImport('running', 'storing_enrichment')).toBe(false)
    expect(canCancelChatHistoryImport('completed', 'completed')).toBe(false)
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
    expect(pageSource).toContain("storing_catalog: '正在保存完整候选目录'")
    expect(pageSource).toContain("storing_enrichment: '正在写入记忆与成员画像'")
    expect(resultSource).toContain("label: '运行时记忆'")
    expect(resultSource).toContain("label: '运行时画像'")
  })

  it('offers full scanning, paginated member selection, and explicit profile review', async () => {
    const settingsSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-import-settings.tsx', import.meta.url)
    ).text()
    const pickerSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-participant-picker.tsx', import.meta.url)
    ).text()
    const reviewSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-profile-review.tsx', import.meta.url)
    ).text()

    expect(settingsSource).toContain("value: 'full'")
    expect(settingsSource).toContain('每一个自然窗口')
    expect(settingsSource).toContain(
      'analysis.eligible_participant_count ?? analysis.participant_count'
    )
    expect(pickerSource).toContain('const PAGE_SIZE = 30')
    expect(pickerSource).toContain('listChatHistoryParticipants')
    expect(pickerSource).toContain('[&>.ios-dialog-close]:h-11')
    expect(reviewSource).toContain("value: 'keep_existing'")
    expect(reviewSource).toContain("value: 'apply_imported'")
  })

  it('keeps the complete candidate catalog paginated and distinct from runtime writes', async () => {
    const resultSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-import-result.tsx', import.meta.url)
    ).text()
    const catalogSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-candidate-catalog.tsx', import.meta.url)
    ).text()
    const apiSource = await Bun.file(
      new URL('../src/lib/chat-history-import-api.ts', import.meta.url)
    ).text()

    expect(resultSource).toContain('ChatHistoryCandidateCatalog')
    expect(catalogSource).toContain('完整候选目录')
    expect(catalogSource).toContain('运行时精选集合')
    expect(catalogSource).toContain("task.options.depth === 'full'")
    expect(catalogSource).toContain('当前目录只覆盖本档位选中的窗口')
    expect(catalogSource).toContain('分页只限制单次传输')
    expect(catalogSource).toContain('<RadioGroup')
    expect(catalogSource).toContain('aria-label="候选类型"')
    expect(catalogSource).not.toContain('<Tabs')
    expect(catalogSource).toContain('const PAGE_SIZE = 20')
    expect(catalogSource).toContain('min-h-11')
    expect(catalogSource).toContain('motion-reduce:animate-none')
    expect(catalogSource).toContain("if (error) catalogStatus = '目录不可用'")
    expect(catalogSource).toContain('id="chat-history-candidate-search"')
    expect(catalogSource).toContain('name="chat-history-candidate-search"')
    expect(catalogSource).toContain('type="search"')
    expect(catalogSource).toContain('aria-label="上一页"')
    expect(catalogSource).toContain('aria-label="下一页"')
    expect(apiSource).toContain('listChatHistoryCandidates')
  })

  it('keeps a cleanup action available after failure or cancellation', async () => {
    const pageSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-import.tsx', import.meta.url)
    ).text()

    expect(pageSource).toContain(
      "activeTask.status === 'failed' || activeTask.status === 'cancelled'"
    )
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
    expect(pageSource).toContain('id="chat-history-json-file"')
    expect(pageSource).toContain('name="chat-history-json-file"')
    expect(pageSource).not.toContain('<AlertTitle')
    expect(settingsSource).not.toContain('<AlertTitle')
  })

  it('constrains the import scroll content to the mobile viewport width', async () => {
    const pageSource = await Bun.file(
      new URL('../src/routes/resource/chat-history-import.tsx', import.meta.url)
    ).text()

    expect(pageSource).toContain(
      '[&>[data-radix-scroll-area-viewport]>div]:!block [&>[data-radix-scroll-area-viewport]>div]:!w-full [&>[data-radix-scroll-area-viewport]>div]:!min-w-0'
    )
  })
})
