import * as React from 'react'
import * as PopoverPrimitive from '@radix-ui/react-popover'

import { cn } from '@/lib/utils'

const Popover = PopoverPrimitive.Root

const PopoverTrigger = PopoverPrimitive.Trigger

const PopoverAnchor = PopoverPrimitive.Anchor

const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(({ className, align = 'center', sideOffset = 4, ...props }, ref) => (
  <PopoverPrimitive.Portal>
    <PopoverPrimitive.Content
      ref={ref}
      align={align}
      sideOffset={sideOffset}
      className={cn(
        'motion-layer z-50 w-72 origin-[--radix-popover-content-transform-origin] rounded-[18px] border border-black/[0.035] bg-white/[0.88] p-3 text-card-foreground shadow-[0_1px_0_rgba(255,255,255,0.74)_inset,0_18px_48px_rgba(31,41,55,0.14),0_4px_12px_rgba(0,0,0,0.055)] outline-none backdrop-blur-2xl dark:border-white/10 dark:bg-zinc-950/[0.88] dark:shadow-[0_1px_0_rgba(255,255,255,0.08)_inset,0_18px_48px_rgba(0,0,0,0.42)]',
        className
      )}
      {...props}
    />
  </PopoverPrimitive.Portal>
))
PopoverContent.displayName = PopoverPrimitive.Content.displayName

export { Popover, PopoverTrigger, PopoverContent, PopoverAnchor }
