import { useState } from 'react'
import { AudioLines, FileWarning, Image as ImageIcon } from 'lucide-react'
import { buildModelTraceMediaUrl } from '../../lib/api/model-trace-api'
import type { ModelTraceMedia } from '../../types/model-trace'

function formatByteSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function UnavailableMedia({ label }: { label: string }) {
  return (
    <div
      className="flex min-h-24 items-center justify-center gap-2 px-4 text-[13px] text-muted-foreground"
      role="status"
    >
      <FileWarning className="h-4 w-4" aria-hidden="true" />
      {label}加载失败
    </div>
  )
}

function TraceImage({ traceId, media, index }: MediaItemProps) {
  const [failed, setFailed] = useState(false)
  const label = `模型请求图片 ${index + 1}`

  return (
    <figure className="min-w-0 overflow-hidden rounded-[8px] border border-border/70 bg-muted/20">
      <div className="flex aspect-video w-full items-center justify-center bg-[rgb(28_28_30)]">
        {failed ? (
          <UnavailableMedia label="图片" />
        ) : (
          <img
            src={buildModelTraceMediaUrl(traceId, media.media_id)}
            alt={label}
            loading="lazy"
            decoding="async"
            className="h-full w-full object-contain"
            onError={() => setFailed(true)}
          />
        )}
      </div>
      <figcaption className="flex min-h-10 items-center gap-2 px-3 text-[12px] text-muted-foreground">
        <ImageIcon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="truncate text-foreground">图片 {index + 1}</span>
        <span className="ml-auto shrink-0 uppercase">{media.format}</span>
        <span className="shrink-0">{formatByteSize(media.size_bytes)}</span>
      </figcaption>
    </figure>
  )
}

function TraceAudio({ traceId, media, index }: MediaItemProps) {
  const [failed, setFailed] = useState(false)
  const label = `模型请求音频 ${index + 1}`

  return (
    <figure className="min-w-0 rounded-[8px] border border-border/70 bg-muted/20 px-3 py-3">
      <figcaption className="mb-2 flex items-center gap-2 text-[12px] text-muted-foreground">
        <AudioLines className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="truncate text-foreground">音频 {index + 1}</span>
        <span className="ml-auto shrink-0 uppercase">{media.format}</span>
        <span className="shrink-0">{formatByteSize(media.size_bytes)}</span>
      </figcaption>
      {failed ? (
        <UnavailableMedia label="音频" />
      ) : (
        <audio
          src={buildModelTraceMediaUrl(traceId, media.media_id)}
          controls
          preload="metadata"
          className="h-10 w-full"
          aria-label={label}
          onError={() => setFailed(true)}
        />
      )}
    </figure>
  )
}

interface MediaItemProps {
  traceId: number
  media: ModelTraceMedia
  index: number
}

export function ModelTraceMediaPreview({
  traceId,
  media,
}: {
  traceId: number
  media: ModelTraceMedia[]
}) {
  if (media.length === 0) return null
  const images = media.filter((item) => item.kind === 'image')
  const audio = media.filter((item) => item.kind === 'audio')

  return (
    <section className="mb-3 space-y-3" aria-labelledby={`model-trace-media-${traceId}`}>
      <div className="flex items-baseline justify-between gap-3 px-0.5">
        <h3 id={`model-trace-media-${traceId}`} className="text-[13px] font-semibold">
          请求媒体
        </h3>
        <span className="text-[12px] text-muted-foreground">{media.length} 个文件</span>
      </div>
      {images.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {images.map((item, index) => (
            <TraceImage key={item.media_id} traceId={traceId} media={item} index={index} />
          ))}
        </div>
      )}
      {audio.map((item, index) => (
        <TraceAudio key={item.media_id} traceId={traceId} media={item} index={index} />
      ))}
    </section>
  )
}
