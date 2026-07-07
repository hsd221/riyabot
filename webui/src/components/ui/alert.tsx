import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const alertVariants = cva(
  'relative w-full rounded-[18px] border border-black/[0.035] bg-white/[0.78] px-5 py-4 text-sm leading-relaxed shadow-[0_1px_0_rgba(255,255,255,0.68)_inset,0_10px_28px_rgba(31,41,55,0.052)] backdrop-blur-2xl dark:border-white/10 dark:bg-white/[0.08] dark:shadow-[0_1px_0_rgba(255,255,255,0.08)_inset,0_12px_30px_rgba(0,0,0,0.22)] [&>svg+div]:translate-y-[-2px] [&>svg]:absolute [&>svg]:left-5 [&>svg]:top-5 [&>svg]:text-foreground [&>svg~*]:pl-7',
  {
    variants: {
      variant: {
        default: 'text-foreground',
        destructive:
          'border-[rgb(255_59_48_/_0.24)] bg-[rgb(255_59_48_/_0.075)] text-[rgb(174_37_31)] dark:border-[rgb(255_69_58_/_0.28)] dark:bg-[rgb(255_69_58_/_0.12)] dark:text-[rgb(255_105_97)] [&>svg]:text-[rgb(255_59_48)]',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
)

const Alert = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>
>(({ className, variant, ...props }, ref) => (
  <div ref={ref} role="alert" className={cn(alertVariants({ variant }), className)} {...props} />
))
Alert.displayName = 'Alert'

const AlertTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h5
      ref={ref}
      className={cn('mb-1 text-[15px] font-semibold leading-5 tracking-normal', className)}
      {...props}
    />
  )
)
AlertTitle.displayName = 'AlertTitle'

const AlertDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn('text-current/85 text-[14px] leading-6 [&_p]:leading-6', className)}
    {...props}
  />
))
AlertDescription.displayName = 'AlertDescription'

export { Alert, AlertTitle, AlertDescription }
