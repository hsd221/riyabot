import { describe, expect, it, mock } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'

import { cn } from '../src/lib/utils'
import { buildModelTraceSearchParams } from '../src/lib/api/model-trace-api'
import type { ModelTraceDetail } from '../src/types/model-trace'

mock.module('@/lib/utils', () => ({ cn }))

const { ModelTraceDetailPanel } = await import('../src/components/model-traces/model-trace-detail')
const { ModelTraceList } = await import('../src/components/model-traces/model-trace-list')
const { TooltipProvider } = await import('../src/components/ui/tooltip')

const detail: ModelTraceDetail = {
  id: 17,
  request_type: 'reply.main',
  operation: 'response',
  model_name: 'model-a',
  model_identifier: 'provider-model-a',
  provider_name: 'provider-a',
  attempt: 1,
  status: 'success',
  started_at: '2026-07-20T12:00:00',
  completed_at: '2026-07-20T12:00:01',
  duration_ms: 1250,
  request_preview: '请具体回答这个问题',
  response_preview: '这是模型返回',
  error_type: null,
  error_message: null,
  status_code: null,
  prompt_tokens: 10,
  completion_tokens: 4,
  total_tokens: 14,
  request_payload: {
    messages: [{ role: 'user', content: [{ type: 'text', text: '请具体回答这个问题' }] }],
  },
  response_payload: {
    content: '这是模型返回',
    reasoning_content: '内部推理',
    untrusted: '<script>alert(1)</script>',
  },
  media: [
    {
      media_id: 'image-1',
      kind: 'image',
      format: 'png',
      mime_type: 'image/png',
      size_bytes: 68,
    },
    {
      media_id: 'audio-1',
      kind: 'audio',
      format: 'wav',
      mime_type: 'audio/wav',
      size_bytes: 44,
    },
  ],
}

describe('model trace view', () => {
  it('builds bounded list query parameters from active filters', () => {
    const params = buildModelTraceSearchParams({
      page: 2,
      pageSize: 30,
      status: 'error',
      requestType: 'planner.main',
      model: 'model-b',
      search: 'timeout',
    })

    expect(params.toString()).toBe(
      'page=2&page_size=30&status=error&request_type=planner.main&model=model-b&search=timeout'
    )
  })

  it('renders concrete request, response, and trace metadata without interpreting markup', () => {
    const html = renderToStaticMarkup(
      <TooltipProvider>
        <ModelTraceDetailPanel detail={detail} />
      </TooltipProvider>
    )

    expect(html).toContain('请具体回答这个问题')
    expect(html).toContain('这是模型返回')
    expect(html).toContain('内部推理')
    expect(html).toContain('provider-model-a')
    expect(html).toContain('14')
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
    expect(html).not.toContain('<script>alert(1)</script>')
  })

  it('renders request images and playable audio from authenticated trace endpoints', () => {
    const html = renderToStaticMarkup(
      <TooltipProvider>
        <ModelTraceDetailPanel detail={detail} />
      </TooltipProvider>
    )

    expect(html).toContain('<img')
    expect(html).toContain('/api/webui/model-traces/17/media/image-1')
    expect(html).toContain('alt="模型请求图片 1"')
    expect(html).toContain('<audio')
    expect(html).toContain('controls=""')
    expect(html).toContain('/api/webui/model-traces/17/media/audio-1')
  })

  it('keeps list semantics without replacing the native button role', () => {
    const html = renderToStaticMarkup(
      <ModelTraceList
        traces={[detail]}
        selectedId={detail.id}
        loading={false}
        onSelect={() => {}}
      />
    )

    expect(html).toContain('<ul role="list"')
    expect(html).toContain('<li>')
    expect(html).toContain('<button')
    expect(html).not.toContain('role="listitem"')
  })
})
