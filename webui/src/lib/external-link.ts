export type ExternalLinkOptions = {
  allowHttp?: boolean
}

export function getSafeExternalUrl(
  value: string,
  { allowHttp = false }: ExternalLinkOptions = {}
): URL | null {
  try {
    const url = new URL(value)
    if (url.protocol === 'https:' || (allowHttp && url.protocol === 'http:')) return url
  } catch {
    // 非法或非绝对 URL 不应交给 window.open。
  }
  return null
}

export function openExternalLink(value: string, options?: ExternalLinkOptions): boolean {
  const url = getSafeExternalUrl(value, options)
  if (!url || typeof window === 'undefined') return false

  const openedWindow = window.open(url.href, '_blank', 'noopener,noreferrer')
  if (openedWindow) openedWindow.opener = null
  return true
}
