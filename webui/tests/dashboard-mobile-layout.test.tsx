import { describe, expect, it } from 'bun:test'

describe('Dashboard mobile layout', () => {
  it('constrains the dashboard scroll area to the viewport width', async () => {
    const source = await Bun.file(new URL('../src/routes/index.tsx', import.meta.url)).text()

    expect(source).toContain(
      '[&>[data-radix-scroll-area-viewport]>div]:!block [&>[data-radix-scroll-area-viewport]>div]:!w-full [&>[data-radix-scroll-area-viewport]>div]:!min-w-0'
    )
  })

  it('clips model detail scrolling to its rounded surface', async () => {
    const source = await Bun.file(new URL('../src/routes/index.tsx', import.meta.url)).text()

    expect(source).toContain(
      'ios-group h-[300px] min-w-0 overflow-hidden sm:h-[400px] [&>[data-radix-scroll-area-viewport]>div]:!block'
    )
    expect(source).toContain('className="w-full min-w-0 max-w-full"')
    expect(source).toContain(
      'ios-row min-h-[86px] flex-col !items-stretch !justify-start gap-2 py-3 sm:flex-row sm:!items-center sm:!justify-between'
    )
  })

  it('stacks activity metadata on compact widths instead of forcing horizontal scrolling', async () => {
    const source = await Bun.file(new URL('../src/routes/index.tsx', import.meta.url)).text()

    expect(source).toContain(
      'ios-row min-h-[92px] flex-col !items-stretch !justify-start gap-2 py-3 sm:flex-row sm:!items-center sm:!justify-between'
    )
    expect(source).toContain('break-words')
  })
})
