import { describe, expect, it } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'

import { DreamRunMessageList } from '../src/components/memory/dream-run-message-details'
import type { DreamRunMessageData } from '../src/types/memory'

const messages: DreamRunMessageData[] = [
  {
    archive_id: 1,
    message_id: 'message-1',
    stream_id: 'group-1',
    user_id: 'user-a',
    platform: 'qq',
    sender_name: '钢琴学员',
    conversation_name: '练琴群',
    content: '我决定从今天开始每天练琴',
    message_timestamp: 1_768_000_000,
    chat_type: 'group',
    route: 'high',
    significance: 0.85,
    outcome: 'retained_as_candidate',
    processed_at: '2026-01-02T08:02:00',
  },
  {
    archive_id: 2,
    message_id: 'message-2',
    stream_id: 'private-1',
    user_id: 'user-b',
    platform: 'qq',
    sender_name: '小红',
    conversation_name: '私聊',
    content: '哈哈哈',
    message_timestamp: 1_768_000_060,
    chat_type: 'private',
    route: 'skipped',
    significance: 0.05,
    outcome: 'skipped',
    processed_at: '2026-01-02T08:03:00',
  },
]

describe('dream run message details', () => {
  it('shows each source message and the concrete processing decision', () => {
    const html = renderToStaticMarkup(
      <DreamRunMessageList messages={messages} total={messages.length} runType="daily" />
    )

    expect(html).toContain('我决定从今天开始每天练琴')
    expect(html).toContain('钢琴学员')
    expect(html).toContain('练琴群')
    expect(html).toContain('高优先级')
    expect(html).toContain('保留到候选池')
    expect(html).toContain('85%')
    expect(html).toContain('跳过')
    expect(html).toContain('未进入候选池')
  })

  it('explains when a cycle only performed memory-level maintenance', () => {
    const html = renderToStaticMarkup(
      <DreamRunMessageList messages={[]} total={0} runType="weekly" />
    )

    expect(html).toContain('没有直接处理原始消息')
    expect(html).toContain('记忆级维护')
  })
})
