'use client'

import * as React from 'react'
import * as TabsPrimitive from '@radix-ui/react-tabs'

import { cn } from '@/lib/utils'

const Tabs = TabsPrimitive.Root

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      'bg-muted/78 inline-flex min-h-[52px] items-center justify-center overflow-hidden rounded-[14px] p-1 text-muted-foreground shadow-[0_1px_0_rgba(255,255,255,0.54)_inset] ring-1 ring-black/[0.025] backdrop-blur-xl dark:shadow-[0_1px_0_rgba(255,255,255,0.06)_inset] dark:ring-white/[0.04]',
      className
    )}
    {...props}
  />
))
TabsList.displayName = TabsPrimitive.List.displayName

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      'data-[state=active]:bg-white/88 inline-flex min-h-11 items-center justify-center whitespace-nowrap rounded-[11px] px-4 py-2 text-sm font-medium ring-offset-background transition-[background-color,color,box-shadow,transform] duration-[var(--motion-duration-control)] ease-[var(--motion-ease-standard)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 data-[state=active]:text-foreground data-[state=active]:shadow-[0_1px_1px_rgba(255,255,255,0.82)_inset,0_2px_8px_rgba(0,0,0,0.05)] data-[state=active]:ring-1 data-[state=active]:ring-black/[0.035] dark:data-[state=active]:bg-[rgb(72_72_74_/_0.96)] dark:data-[state=active]:ring-white/[0.06]',
      className
    )}
    {...props}
  />
))
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      'motion-content mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
      className
    )}
    {...props}
  />
))
TabsContent.displayName = TabsPrimitive.Content.displayName

export { Tabs, TabsList, TabsTrigger, TabsContent }
