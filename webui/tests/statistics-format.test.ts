import { describe, expect, it } from 'bun:test'

import { formatCompactCurrency, formatDuration } from '../src/components/statistics/format'

describe('statistics summary formatting', () => {
  it('keeps large currency values compact enough for narrow metric cards', () => {
    expect(formatCompactCurrency(123_456_789)).toBe('¥1.2亿')
    expect(formatCompactCurrency(Number.NaN)).toBe('¥0.00')
  })

  it('uses concise duration labels for long online periods', () => {
    expect(formatDuration(23 * 3600 + 59 * 60)).toBe('23时 59分')
    expect(formatDuration(90 * 24 * 3600)).toBe('90天')
    expect(formatDuration(65 * 60)).toBe('1时 5分')
  })
})
