import { describe, expect, it } from 'bun:test'

import {
  buildChartStyle,
  getChartColorVariable,
  getChartId,
  sanitizeChartColor,
} from '../src/components/ui/chart-style'

describe('chart style security', () => {
  it('keeps existing safe variable names and supported color formats', () => {
    expect(getChartColorVariable('requests')).toBe('var(--color-requests)')

    const acceptedColors = [
      '#fff',
      '#007AFFCC',
      'rgb(255, 0, 0)',
      'rgba(255 0 0 / 50%)',
      'hsl(210 100% 50%)',
      'hsla(210, 100%, 50%, 0.5)',
      'var(--chart-1)',
      'hsl(var(--chart-1))',
      'hsl(var(--chart-1) / 0.5)',
      'transparent',
    ]

    for (const color of acceptedColors) {
      expect(sanitizeChartColor(` ${color} `)).toBe(color)
    }
  })

  it('maps attacker-controlled keys to deterministic CSS identifiers', () => {
    const maliciousKeys = [
      'x}body{background:red',
      'x;--evil',
      'line\nbreak',
      'price\u202Egnp',
      '',
      'x'.repeat(512),
    ]

    for (const key of maliciousKeys) {
      const first = getChartColorVariable(key)
      const second = getChartColorVariable(key)

      expect(first).toBe(second)
      expect(first).toMatch(/^var\(--color-[a-z0-9_-]+\)$/)
      expect(first).not.toContain('body')
      expect(first).not.toContain(';')
      expect(first).not.toContain('\n')
      expect(first).not.toContain('\u202E')
    }
  })

  it('rejects unsafe or unsupported color expressions', () => {
    const rejectedColors = [
      'red;}body{display:none}',
      'url(https://attacker.example/track)',
      'var(--chart-1, red)',
      'hsl(var(--chart-1)); color: red',
      'expression(alert(1))',
      'rgb(calc(1 + 1) 0 0)',
      'red\n!important',
      'red\u202E',
      'x'.repeat(512),
    ]

    for (const color of rejectedColors) {
      expect(sanitizeChartColor(color)).toBeNull()
    }
  })

  it('emits only sanitized selectors, property names, and declarations', () => {
    const css = buildChartStyle('x"]} body { display:none } /*', {
      'x}body{background:red': { color: '#007AFF' },
      safe: { color: 'red;}body{display:none}' },
      themed: {
        theme: {
          light: 'rgb(52 199 89)',
          dark: 'hsl(var(--chart-2))',
        },
      },
    })

    expect(css).toContain('--color-encoded-')
    expect(css).toContain('--color-themed: rgb(52 199 89);')
    expect(css).toContain('.dark ')
    expect(css).toContain('--color-themed: hsl(var(--chart-2));')
    expect(css).not.toContain('body {')
    expect(css).not.toContain('display:none')
    expect(css).not.toContain('--color-safe')
  })

  it('keeps generated data attributes aligned with their CSS selectors', () => {
    const ids = ['requests', '图表：请求量', '图'.repeat(30), 'x'.repeat(96), 'x'.repeat(512)]

    for (const id of ids) {
      const chartId = getChartId(id)
      const css = buildChartStyle(chartId, { requests: { color: '#007AFF' } })

      expect(css).toContain(`[data-chart="${chartId}"]`)
    }
  })
})
