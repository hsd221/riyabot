import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium transition-[background-color,color,box-shadow,transform,filter] duration-[260ms] ease-[cubic-bezier(0.2,0,0,1)] active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35 disabled:pointer-events-none disabled:opacity-50 disabled:active:scale-100 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-[linear-gradient(180deg,hsl(var(--primary)_/_0.94),hsl(var(--primary)))] text-primary-foreground shadow-[0_4px_12px_hsl(var(--primary)_/_0.13),0_1px_2px_rgba(0,0,0,0.08),inset_0_1px_0_rgba(255,255,255,0.18)] hover:brightness-[0.985] active:brightness-[0.94] active:shadow-[0_2px_7px_hsl(var(--primary)_/_0.12),inset_0_1px_2px_rgba(0,0,0,0.12)]",
        destructive:
          "bg-destructive text-destructive-foreground shadow-[0_5px_14px_hsl(var(--destructive)_/_0.15),0_1px_2px_rgba(0,0,0,0.08)] hover:bg-destructive/90 active:shadow-[0_2px_8px_hsl(var(--destructive)_/_0.12)]",
        outline:
          "border border-black/5 bg-white/70 shadow-[0_1px_1px_rgba(255,255,255,0.65)_inset,0_2px_8px_rgba(0,0,0,0.035),0_1px_2px_rgba(0,0,0,0.03)] backdrop-blur-xl hover:bg-white/85 hover:text-accent-foreground active:bg-muted active:shadow-[0_1px_1px_rgba(255,255,255,0.5)_inset,0_1px_4px_rgba(0,0,0,0.05)] dark:border-white/10 dark:bg-white/[0.08] dark:hover:bg-white/[0.12]",
        secondary:
          "bg-secondary text-secondary-foreground shadow-[0_2px_8px_rgba(0,0,0,0.035)] hover:bg-secondary/80 active:bg-secondary/70 active:brightness-[0.96]",
        ghost: "hover:bg-accent hover:text-accent-foreground active:bg-muted active:brightness-[0.96]",
        link: "text-primary underline-offset-4 hover:underline active:brightness-[0.9]",
      },
      size: {
        default: "h-11 px-5 py-2",
        sm: "h-11 min-w-11 px-4 text-[13px]",
        lg: "h-12 px-8",
        icon: "h-11 w-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

// eslint-disable-next-line react-refresh/only-export-components
export { Button, buttonVariants }
