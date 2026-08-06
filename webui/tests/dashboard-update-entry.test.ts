import { describe, expect, it } from 'bun:test'
import { parseSettingsTab } from '../src/lib/settings-route'

describe('dashboard update entry', () => {
  it('checks the selected channel on dashboard mount and offers an update action', async () => {
    const hookSource = await Bun.file(
      new URL('../src/hooks/use-dashboard-update-check.tsx', import.meta.url)
    ).text()

    expect(hookSource).toContain('await getUpdateStatus()')
    expect(hookSource).toContain('if (!status.update_available) return')
    expect(hookSource).toContain("title: '发现新版本'")
    expect(hookSource).toContain('<ToastAction altText="打开系统更新" asChild>')
    expect(hookSource).toContain('href="/settings?tab=about"')
    expect(hookSource).not.toContain("import { Link } from '@tanstack/react-router'")
  })

  it('makes both responsive dashboard version rows navigable and labels available updates', async () => {
    const dashboardSource = await Bun.file(
      new URL('../src/routes/index.tsx', import.meta.url)
    ).text()
    const linkSource = await Bun.file(
      new URL('../src/components/dashboard-version-link.tsx', import.meta.url)
    ).text()

    expect(dashboardSource).toContain('const updateStatus = useDashboardUpdateCheck()')
    expect(dashboardSource.match(/<DashboardVersionLink/g)).toHaveLength(2)
    expect(linkSource).toContain("search={{ tab: 'about' }}")
    expect(linkSource).toContain('updateAvailable &&')
    expect(linkSource).toContain('有更新')
    expect(linkSource).toContain('aria-label={accessibleLabel}')
  })

  it('opens the validated About settings tab from the update link', async () => {
    const routerSource = await Bun.file(new URL('../src/router.tsx', import.meta.url)).text()
    const settingsSource = await Bun.file(
      new URL('../src/routes/settings.tsx', import.meta.url)
    ).text()

    expect(routerSource).toContain('parseSettingsTab(search.tab)')
    expect(parseSettingsTab('about')).toBe('about')
    expect(parseSettingsTab('updates')).toBeUndefined()
    expect(settingsSource).toContain('useSearch({ strict: false })')
    expect(settingsSource).toContain("parseSettingsTab(search.tab) ?? 'appearance'")
    expect(settingsSource).toContain('useState<SettingsTab>(initialTab)')
  })
})
