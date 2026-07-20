import { describe, expect, it } from 'bun:test'

describe('PersonManagementPage mobile layout', () => {
  it('constrains the vertical scroll content to the mobile viewport width', async () => {
    const source = await Bun.file(new URL('../src/routes/person.tsx', import.meta.url)).text()

    expect(source).toContain('[&>[data-radix-scroll-area-viewport]>div]:!block')
    expect(source).toContain('[&>[data-radix-scroll-area-viewport]>div]:!w-full')
    expect(source).toContain('[&>[data-radix-scroll-area-viewport]>div]:!min-w-0')
  })
})
