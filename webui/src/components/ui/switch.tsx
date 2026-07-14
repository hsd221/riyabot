import * as React from 'react'
import * as SwitchPrimitives from '@radix-ui/react-switch'

import { cn } from '@/lib/utils'

const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitives.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitives.Root
    className={cn(
      'peer relative inline-flex h-11 w-16 shrink-0 cursor-pointer items-center rounded-full border border-transparent bg-transparent p-0 transition-transform duration-[var(--motion-duration-control)] ease-[var(--motion-ease-standard)] before:absolute before:left-1 before:right-1 before:top-1.5 before:h-8 before:rounded-full before:bg-[rgb(120_120_128_/_0.22)] before:shadow-[0_1px_0_rgba(255,255,255,0.55)_inset,0_1px_2px_rgba(0,0,0,0.06)] before:transition-[background-color,box-shadow] before:duration-[var(--motion-duration-control)] before:ease-[var(--motion-ease-standard)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35 active:scale-[0.985] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 data-[state=checked]:before:bg-[#34c759] data-[state=unchecked]:before:bg-[rgb(120_120_128_/_0.22)] data-[state=checked]:before:shadow-[0_1px_0_rgba(255,255,255,0.26)_inset,0_4px_12px_rgb(52_199_89_/_0.16)] dark:data-[state=unchecked]:before:bg-white/[0.18]',
      className
    )}
    {...props}
    ref={ref}
  >
    <SwitchPrimitives.Thumb
      className={cn(
        'pointer-events-none relative z-10 ml-1.5 block h-7 w-7 rounded-full bg-white shadow-[0_2px_6px_rgba(0,0,0,0.28),0_1px_1px_rgba(0,0,0,0.12),0_1px_0_rgba(255,255,255,0.9)_inset] ring-0 transition-transform duration-[var(--motion-duration-control)] ease-[var(--motion-ease-standard)] data-[state=checked]:translate-x-6 data-[state=unchecked]:translate-x-0'
      )}
    />
  </SwitchPrimitives.Root>
))
Switch.displayName = SwitchPrimitives.Root.displayName

export { Switch }
