import { useContext } from 'react'
import { ThemeProviderContext } from '@/lib/theme-context'

export const useTheme = () => {
  const context = useContext(ThemeProviderContext)

  if (context === undefined) throw new Error('useTheme must be used within a ThemeProvider')

  return context
}

export const toggleThemeWithTransition = (
  theme: 'dark' | 'light' | 'system',
  setTheme: (theme: 'dark' | 'light' | 'system') => void,
  event: React.MouseEvent
) => {
  const motionMode = document.documentElement.dataset.motion ?? 'full'

  // 检查浏览器是否支持 View Transitions API
  if (!document.startViewTransition || motionMode === 'none') {
    setTheme(theme)
    return
  }

  if (motionMode === 'reduced') {
    document.startViewTransition(() => setTheme(theme))
    return
  }

  const triggeredByKeyboard = event.detail === 0
  const x = triggeredByKeyboard ? window.innerWidth / 2 : event.clientX
  const y = triggeredByKeyboard ? window.innerHeight / 2 : event.clientY
  const endRadius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y))

  const transition = document.startViewTransition(() => {
    setTheme(theme)
  })

  void transition.ready
    .then(() => {
      // 始终在新内容层应用动画(z-index: 999)
      document.documentElement.animate(
        {
          clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${endRadius}px at ${x}px ${y}px)`],
        },
        {
          duration: 420,
          easing: 'cubic-bezier(0.2, 0, 0, 1)',
          pseudoElement: '::view-transition-new(root)',
        }
      )
    })
    .catch(() => undefined)
}
