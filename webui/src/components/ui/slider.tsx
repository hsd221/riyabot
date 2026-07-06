import * as React from "react"
import * as SliderPrimitive from "@radix-ui/react-slider"

import { cn } from "@/lib/utils"

const Slider = React.forwardRef<
  React.ElementRef<typeof SliderPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SliderPrimitive.Root
    ref={ref}
    className={cn(
      "relative flex h-8 w-full touch-none select-none items-center",
      className
    )}
    {...props}
  >
    <SliderPrimitive.Track className="relative h-2 w-full grow overflow-hidden rounded-full bg-input shadow-inner shadow-black/[0.03]">
      <SliderPrimitive.Range className="absolute h-full bg-primary" />
    </SliderPrimitive.Track>
    <SliderPrimitive.Thumb className="block h-6 w-6 rounded-full border border-black/5 bg-white shadow-[0_2px_8px_rgba(0,0,0,0.24),0_1px_2px_rgba(0,0,0,0.10)] transition-[box-shadow,transform] duration-[260ms] ease-[cubic-bezier(0.2,0,0,1)] active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35 disabled:pointer-events-none disabled:opacity-50 dark:border-white/10" />
  </SliderPrimitive.Root>
))
Slider.displayName = SliderPrimitive.Root.displayName

export { Slider }
