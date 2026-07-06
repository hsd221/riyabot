import * as React from "react"

import { cn } from "@/lib/utils"

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-12 w-full rounded-[13px] border-0 bg-muted/80 px-4 py-2 text-base leading-relaxed shadow-[0_1px_0_rgba(255,255,255,0.56)_inset] transition-[background-color,box-shadow,transform] duration-[260ms] ease-[cubic-bezier(0.2,0,0,1)] file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35 active:scale-[0.995] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 md:text-sm",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }
