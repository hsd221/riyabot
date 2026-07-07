import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const kbdVariants = cva(
  'pointer-events-none inline-flex select-none items-center gap-1 rounded-[7px] border border-black/[0.045] bg-white/[0.72] px-1.5 font-mono font-medium text-muted-foreground opacity-100 shadow-[0_1px_0_rgba(255,255,255,0.7)_inset,0_1px_2px_rgba(0,0,0,0.035)] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.08]',
  {
    variants: {
      size: {
        sm: 'h-5 text-[10px]',
        default: 'h-6 text-xs',
        lg: 'h-7 text-sm',
      },
    },
    defaultVariants: {
      size: 'default',
    },
  }
)

export interface KbdProps
  extends React.HTMLAttributes<HTMLElement>,
    VariantProps<typeof kbdVariants> {
  abbrTitle?: string
}

const Kbd = React.forwardRef<HTMLElement, KbdProps>(
  ({ className, size, abbrTitle, children, ...props }, ref) => {
    return (
      <kbd className={cn(kbdVariants({ size, className }))} ref={ref} {...props}>
        {abbrTitle ? <abbr title={abbrTitle}>{children}</abbr> : children}
      </kbd>
    )
  }
)
Kbd.displayName = 'Kbd'

export { Kbd }
