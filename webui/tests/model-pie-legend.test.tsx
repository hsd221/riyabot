import { describe, expect, it } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'

import { ModelPieLegend } from '../src/components/statistics/model-pie-legend'

describe('ModelPieLegend', () => {
  it('shows complete model names and percentages in the mobile layout', () => {
    const longModelName = 'provider/very-long-model-name-without-natural-wrap-points-20260720'
    const html = renderToStaticMarkup(
      <ModelPieLegend
        data={[
          { name: longModelName, value: 2, fill: '#007AFF' },
          { name: 'short-model', value: 1, fill: '#34C759' },
        ]}
      />
    )

    expect(html).toContain('aria-label="模型请求占比"')
    expect(html).toContain('sm:hidden')
    expect(html).toContain('ios-break-anywhere')
    expect(html).toContain(longModelName)
    expect(html).toContain('67%')
    expect(html).not.toContain('truncate')
  })
})
