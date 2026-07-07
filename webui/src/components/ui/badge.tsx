import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex min-h-6 items-center whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[12px] font-medium leading-4 shadow-[0_1px_0_rgba(255,255,255,0.52)_inset] transition-colors focus:outline-none focus:ring-2 focus:ring-ring/35 focus:ring-offset-2',
  {
    variants: {
      variant: {
        default:
          'border-transparent bg-[linear-gradient(180deg,hsl(var(--primary)_/_0.9),hsl(var(--primary)))] text-primary-foreground hover:brightness-[0.98]',
        secondary:
          'border-black/[0.025] bg-white/[0.68] text-secondary-foreground backdrop-blur-xl hover:bg-white/[0.82] dark:border-white/10 dark:bg-white/[0.1]',
        destructive:
          'border-transparent bg-[linear-gradient(180deg,hsl(var(--destructive)_/_0.92),hsl(var(--destructive)))] text-destructive-foreground hover:brightness-[0.98]',
        outline:
          'border-black/[0.055] bg-white/[0.42] text-foreground backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.06]',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

// eslint-disable-next-line react-refresh/only-export-components
export { Badge, badgeVariants }
