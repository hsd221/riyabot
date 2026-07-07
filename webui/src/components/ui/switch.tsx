import * as React from 'react'
import * as SwitchPrimitives from '@radix-ui/react-switch'

import { cn } from '@/lib/utils'

const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitives.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitives.Root
    className={cn(
      'peer inline-flex h-8 w-14 shrink-0 cursor-pointer items-center rounded-full border border-transparent bg-[rgb(120_120_128_/_0.22)] p-0.5 shadow-[0_1px_0_rgba(255,255,255,0.55)_inset,0_1px_2px_rgba(0,0,0,0.06)] transition-[background-color,box-shadow,transform] duration-[260ms] ease-[cubic-bezier(0.2,0,0,1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35 active:scale-[0.985] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 data-[state=checked]:bg-[#34c759] data-[state=unchecked]:bg-[rgb(120_120_128_/_0.22)] data-[state=checked]:shadow-[0_1px_0_rgba(255,255,255,0.26)_inset,0_4px_12px_rgb(52_199_89_/_0.16)] dark:data-[state=unchecked]:bg-white/[0.18]',
      className
    )}
    {...props}
    ref={ref}
  >
    <SwitchPrimitives.Thumb
      className={cn(
        'pointer-events-none block h-7 w-7 rounded-full bg-white shadow-[0_2px_6px_rgba(0,0,0,0.28),0_1px_1px_rgba(0,0,0,0.12),0_1px_0_rgba(255,255,255,0.9)_inset] ring-0 transition-transform duration-[260ms] ease-[cubic-bezier(0.2,0,0,1)] data-[state=checked]:translate-x-6 data-[state=unchecked]:translate-x-0'
      )}
    />
  </SwitchPrimitives.Root>
))
Switch.displayName = SwitchPrimitives.Root.displayName

export { Switch }
