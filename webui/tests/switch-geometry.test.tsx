import { describe, expect, it, mock } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'

import { cn } from '../src/lib/utils'

mock.module('@/lib/utils', () => ({
  cn,
}))

const { Switch } = await import('../src/components/ui/switch')

describe('Switch geometry', () => {
  it('centers native iOS switch proportions inside a 44px touch target', () => {
    const html = renderToStaticMarkup(<Switch aria-label="Test setting" />)

    expect(html).toContain('h-11')
    expect(html).toContain('w-[51px]')
    expect(html).toContain('before:top-1/2')
    expect(html).toContain('before:h-[31px]')
    expect(html).toContain('before:-translate-y-1/2')
    expect(html).toContain('left-0.5')
    expect(html).toContain('top-1/2')
    expect(html).toContain('h-[27px]')
    expect(html).toContain('w-[27px]')
    expect(html).toContain('data-[state=checked]:translate-x-5')
    expect(html).toContain('data-[state=unchecked]:translate-x-0')
  })
})
