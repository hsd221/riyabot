import { useCallback, useEffect, useRef, useState } from 'react'
import { ImageIcon } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchWithAuth } from '@/lib/fetch-with-auth'
import { cn } from '@/lib/utils'

interface EmojiThumbnailProps {
  src: string
  alt?: string
  className?: string
  /** 最大重试次数 */
  maxRetries?: number
  /** 重试间隔（毫秒） */
  retryInterval?: number
}

type LoadingState = 'loading' | 'loaded' | 'generating' | 'error'

export function EmojiThumbnail({
  src,
  alt = '表情包',
  className,
  maxRetries = 5,
  retryInterval = 1500,
}: EmojiThumbnailProps) {
  const [state, setState] = useState<LoadingState>('loading')
  const [imageSrc, setImageSrc] = useState<string | null>(null)
  const retryTimerRef = useRef<number | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const objectUrlRef = useRef<string | null>(null)
  const requestIdRef = useRef(0)

  const clearResources = useCallback(() => {
    requestIdRef.current += 1
    abortControllerRef.current?.abort()
    abortControllerRef.current = null

    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }

    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
  }, [])

  useEffect(() => {
    clearResources()
    const requestId = requestIdRef.current
    setState('loading')
    setImageSrc(null)

    const loadImage = async (attempt: number): Promise<void> => {
      if (requestIdRef.current !== requestId) return

      const controller = new AbortController()
      abortControllerRef.current = controller

      try {
        const response = await fetchWithAuth(src, {
          cache: 'no-store',
          signal: controller.signal,
        })

        if (requestIdRef.current !== requestId) return

        if (response.status === 202) {
          if (attempt >= maxRetries) {
            setState('error')
            return
          }

          setState('generating')
          retryTimerRef.current = window.setTimeout(
            () => void loadImage(attempt + 1),
            retryInterval
          )
          return
        }

        if (!response.ok) {
          setState('error')
          return
        }

        const blob = await response.blob()
        if (requestIdRef.current !== requestId) return

        const objectUrl = URL.createObjectURL(blob)
        objectUrlRef.current = objectUrl
        setImageSrc(objectUrl)
        setState('loaded')
      } catch (error) {
        if (requestIdRef.current !== requestId || controller.signal.aborted) return
        console.error('加载缩略图失败:', error)
        setState('error')
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null
        }
      }
    }

    void loadImage(0)
    return clearResources
  }, [clearResources, maxRetries, retryInterval, src])

  if (state === 'loading' || state === 'generating') {
    return (
      <Skeleton
        className={cn('h-full w-full rounded-[14px]', className)}
        aria-label={state === 'generating' ? '正在生成表情包缩略图' : '正在加载表情包缩略图'}
      />
    )
  }

  if (state === 'error' || !imageSrc) {
    return (
      <div
        className={cn(
          'flex h-full w-full flex-col items-center justify-center gap-2 rounded-[14px] bg-secondary/70 p-2 text-center text-muted-foreground shadow-[0_1px_0_rgba(255,255,255,0.7)_inset]',
          className
        )}
        role="img"
        aria-label={`${alt}加载失败`}
      >
        <ImageIcon className="h-8 w-8" strokeWidth={2.35} aria-hidden="true" />
        <span className="text-[11px] leading-4">图片不可用</span>
      </div>
    )
  }

  return <img src={imageSrc} alt={alt} className={cn('h-full w-full object-contain', className)} />
}
