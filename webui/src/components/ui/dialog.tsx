import * as React from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { cn } from "@/lib/utils"
import { X } from "lucide-react"

const Dialog = DialogPrimitive.Root

const DialogTrigger = DialogPrimitive.Trigger

const DialogPortal = DialogPrimitive.Portal

const DialogClose = DialogPrimitive.Close

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-50 bg-black/[0.18] backdrop-blur-md data-[state=open]:animate-fade-in data-[state=closed]:animate-fade-out dark:bg-black/[0.34]",
      className
    )}
    {...props}
  />
))
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName

interface DialogContentProps
  extends React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> {
  /** 阻止点击外部关闭（用于 Tour 运行时） */
  preventOutsideClose?: boolean
}

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  DialogContentProps
>(({ className, children, preventOutsideClose = false, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed bottom-0 left-0 top-auto z-50 grid w-full max-w-none translate-x-0 translate-y-0 gap-5 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 border-t border-black/[0.035] bg-white/[0.9] p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] text-card-foreground shadow-[0_-16px_56px_rgba(31,41,55,0.15),0_1px_1px_rgba(255,255,255,0.72)_inset] backdrop-blur-2xl duration-[360ms] ease-[cubic-bezier(0.2,0,0,1)] data-[state=open]:animate-slide-in-from-bottom data-[state=closed]:animate-slide-out-to-bottom dark:border-white/10 dark:bg-zinc-950/[0.88] dark:shadow-[0_-18px_58px_rgba(0,0,0,0.46),0_1px_0_rgba(255,255,255,0.08)_inset] sm:bottom-auto sm:left-[50%] sm:top-[50%] sm:w-[calc(100%-2rem)] sm:max-w-lg sm:translate-x-[-50%] sm:translate-y-[-50%] sm:rounded-[24px] sm:border sm:p-6 sm:shadow-[0_24px_70px_rgba(31,41,55,0.16),0_1px_1px_rgba(255,255,255,0.72)_inset] sm:data-[state=open]:animate-fade-in sm:data-[state=closed]:animate-fade-out dark:sm:shadow-[0_24px_70px_rgba(0,0,0,0.48)]",
        className
      )}
      onPointerDownOutside={preventOutsideClose ? (e) => e.preventDefault() : undefined}
      onInteractOutside={preventOutsideClose ? (e) => e.preventDefault() : undefined}
      {...props}
    >
      {children}
      <DialogPrimitive.Close className="ios-dialog-close ios-touch absolute right-3 top-3 flex h-10 w-10 items-center justify-center rounded-full bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:bg-muted disabled:pointer-events-none">
        <X className="h-4 w-4" />
        <span className="sr-only">Close</span>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPortal>
))
DialogContent.displayName = DialogPrimitive.Content.displayName

const DialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col space-y-2 pr-12 text-left",
      className
    )}
    {...props}
  />
)
DialogHeader.displayName = "DialogHeader"

const DialogFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
      className
    )}
    {...props}
  />
)
DialogFooter.displayName = "DialogFooter"

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn(
      "text-lg font-semibold leading-tight tracking-normal sm:text-xl",
      className
    )}
    {...props}
  />
))
DialogTitle.displayName = DialogPrimitive.Title.displayName

const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-sm leading-relaxed text-muted-foreground", className)}
    {...props}
  />
))
DialogDescription.displayName = DialogPrimitive.Description.displayName

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogTrigger,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
}
