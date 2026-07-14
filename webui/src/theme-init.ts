try {
  const storedTheme = localStorage.getItem('ui-theme') || localStorage.getItem('riyabot-ui-theme')
  const theme =
    storedTheme === 'light' || storedTheme === 'dark' || storedTheme === 'system'
      ? storedTheme
      : 'system'
  const resolvedTheme =
    theme === 'system'
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
      : theme
  const root = document.documentElement
  root.classList.remove('light', 'dark')
  root.classList.add(resolvedTheme)
  root.style.colorScheme = resolvedTheme
} catch {
  // localStorage 可能被浏览器隐私策略禁用，保留系统默认外观即可。
}
