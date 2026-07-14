import * as React from 'react'

import { cn } from '@/lib/utils'

const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<'textarea'>>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(
          'placeholder:text-muted-foreground/82 flex min-h-[112px] w-full rounded-[15px] border border-transparent bg-[rgb(120_120_128_/_0.13)] px-4 py-3 text-base leading-relaxed shadow-[0_1px_0_rgba(255,255,255,0.58)_inset] transition-[background-color,box-shadow,transform] duration-[var(--motion-duration-control)] ease-[var(--motion-ease-standard)] hover:bg-[rgb(120_120_128_/_0.16)] focus-visible:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35 active:scale-[0.995] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 dark:bg-white/[0.08] dark:shadow-[0_1px_0_rgba(255,255,255,0.07)_inset] dark:hover:bg-white/[0.11] dark:focus-visible:bg-[rgb(58_58_60_/_0.98)] md:text-sm',
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Textarea.displayName = 'Textarea'

export { Textarea }
