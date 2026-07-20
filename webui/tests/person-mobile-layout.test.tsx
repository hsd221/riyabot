import { describe, expect, it } from 'bun:test'

describe('PersonManagementPage mobile layout', () => {
  it('constrains the vertical scroll content to the mobile viewport width', async () => {
    const source = await Bun.file(new URL('../src/routes/person.tsx', import.meta.url)).text()

    expect(source).toContain('[&>[data-radix-scroll-area-viewport]>div]:!block')
    expect(source).toContain('[&>[data-radix-scroll-area-viewport]>div]:!w-full')
    expect(source).toContain('[&>[data-radix-scroll-area-viewport]>div]:!min-w-0')
  })

  it('keeps the profile content aligned to the leading edge on compact widths', async () => {
    const source = await Bun.file(new URL('../src/routes/person.tsx', import.meta.url)).text()

    expect(source).toContain('className="flex min-w-0 flex-1 items-start gap-3"')
    expect(source).not.toContain('flex shrink-0 justify-end pl-14 sm:pl-0')
  })
})
