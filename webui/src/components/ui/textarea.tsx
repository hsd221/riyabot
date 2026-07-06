import * as React from 'react'

import { cn } from '@/lib/utils'

const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<'textarea'>>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(
          'flex min-h-[112px] w-full rounded-[14px] border border-transparent bg-muted/[0.78] px-4 py-3 text-base leading-relaxed shadow-[0_1px_0_rgba(255,255,255,0.56)_inset] transition-[background-color,box-shadow,transform] duration-[260ms] ease-[cubic-bezier(0.2,0,0,1)] placeholder:text-muted-foreground focus-visible:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35 active:scale-[0.995] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 md:text-sm',
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
