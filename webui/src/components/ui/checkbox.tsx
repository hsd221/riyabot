import * as React from 'react'
import * as CheckboxPrimitive from '@radix-ui/react-checkbox'
import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

const Checkbox = React.forwardRef<
  React.ElementRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
  <CheckboxPrimitive.Root
    ref={ref}
    className={cn(
      'dark:before:border-white/18 peer relative grid h-11 w-11 shrink-0 place-content-center rounded-[14px] border-0 bg-transparent text-white transition-[box-shadow,transform] duration-[var(--motion-duration-control)] ease-[var(--motion-ease-standard)] before:absolute before:left-1/2 before:top-1/2 before:h-6 before:w-6 before:-translate-x-1/2 before:-translate-y-1/2 before:rounded-[8px] before:border before:border-black/[0.14] before:bg-white/[0.92] before:shadow-[0_1px_0_rgba(255,255,255,0.78)_inset,0_1px_2px_rgba(0,0,0,0.06)] before:transition-[background-color,border-color,box-shadow] before:duration-[var(--motion-duration-control)] before:ease-[var(--motion-ease-standard)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35 active:scale-[0.94] disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:before:border-transparent data-[state=checked]:before:bg-[linear-gradient(180deg,hsl(var(--primary)_/_0.94),hsl(var(--primary)))] data-[state=checked]:before:shadow-[0_1px_0_rgba(255,255,255,0.24)_inset,0_4px_10px_hsl(var(--primary)_/_0.2)] dark:before:bg-white/[0.1] dark:before:shadow-[0_1px_0_rgba(255,255,255,0.08)_inset]',
      className
    )}
    {...props}
  >
    <CheckboxPrimitive.Indicator
      className={cn('motion-selection relative z-10 grid place-content-center text-current')}
    >
      <Check className="h-[17px] w-[17px]" strokeWidth={3.2} />
    </CheckboxPrimitive.Indicator>
  </CheckboxPrimitive.Root>
))
Checkbox.displayName = CheckboxPrimitive.Root.displayName

export { Checkbox }
