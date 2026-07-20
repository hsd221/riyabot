import { useMemo, useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { Button } from '../ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip'

function formatPayload(payload: unknown): string {
  if (typeof payload === 'string') return payload
  try {
    return JSON.stringify(payload, null, 2) ?? String(payload)
  } catch {
    return String(payload)
  }
}

export function ModelTraceJson({ payload, label }: { payload: unknown; label: string }) {
  const [copied, setCopied] = useState(false)
  const formatted = useMemo(() => formatPayload(payload), [payload])

  const copy = async () => {
    if (!navigator.clipboard) return
    try {
      await navigator.clipboard.writeText(formatted)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="relative min-h-[24rem] overflow-hidden rounded-[8px] border border-border/70 bg-[rgb(28_28_30)] text-zinc-100 shadow-[0_1px_0_rgba(255,255,255,0.08)_inset]">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="absolute right-2 top-2 z-10 h-9 w-9 rounded-full bg-white/10 text-zinc-200 hover:bg-white/15 hover:text-white"
            onClick={copy}
            aria-label={`复制${label}`}
          >
            {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{copied ? '已复制' : `复制${label}`}</TooltipContent>
      </Tooltip>
      <pre className="max-h-[36rem] overflow-auto whitespace-pre-wrap break-words p-4 pr-14 font-mono text-[12px] leading-6 sm:p-5 sm:pr-16 sm:text-[13px]">
        {formatted}
      </pre>
    </div>
  )
}
