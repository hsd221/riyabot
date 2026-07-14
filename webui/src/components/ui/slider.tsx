import * as React from 'react'
import * as SliderPrimitive from '@radix-ui/react-slider'

import { cn } from '@/lib/utils'

const Slider = React.forwardRef<
  React.ElementRef<typeof SliderPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SliderPrimitive.Root
    ref={ref}
    className={cn('relative flex h-11 w-full touch-none select-none items-center', className)}
    {...props}
  >
    <SliderPrimitive.Track className="relative h-[7px] w-full grow overflow-hidden rounded-full bg-[rgb(120_120_128_/_0.2)] shadow-[0_1px_0_rgba(255,255,255,0.55)_inset] dark:bg-white/[0.14]">
      <SliderPrimitive.Range className="absolute h-full bg-[linear-gradient(180deg,hsl(var(--primary)_/_0.9),hsl(var(--primary)))]" />
    </SliderPrimitive.Track>
    <SliderPrimitive.Thumb className="relative block h-11 w-11 rounded-full bg-transparent transition-[box-shadow,transform] duration-[var(--motion-duration-control)] ease-[var(--motion-ease-standard)] before:absolute before:left-1/2 before:top-1/2 before:h-8 before:w-8 before:-translate-x-1/2 before:-translate-y-1/2 before:rounded-full before:border before:border-black/[0.035] before:bg-white before:shadow-[0_4px_12px_rgba(0,0,0,0.24),0_1px_2px_rgba(0,0,0,0.10),0_1px_0_rgba(255,255,255,0.9)_inset] before:content-[''] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35 active:scale-[0.94] disabled:pointer-events-none disabled:opacity-50 dark:before:border-white/10" />
  </SliderPrimitive.Root>
))
Slider.displayName = SliderPrimitive.Root.displayName

export { Slider }
