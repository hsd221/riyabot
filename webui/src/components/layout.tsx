import {
  Menu,
  Moon,
  Sun,
  ChevronLeft,
  Home,
  Settings,
  LogOut,
  FileText,
  Server,
  Boxes,
  Smile,
  MessageSquare,
  UserCircle,
  FileSearch,
  Package,
  BookOpen,
  Search,
  Sliders,
  Hash,
  BrainCircuit,
  MoreHorizontal,
  X,
  ChevronRight,
} from 'lucide-react'
import { useState, useEffect } from 'react'
import { Link, useMatchRoute } from '@tanstack/react-router'
import { useTheme, toggleThemeWithTransition } from './use-theme'
import { useAuthGuard } from '@/hooks/use-auth'
import { logout } from '@/lib/fetch-with-auth'
import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { SearchDialog } from '@/components/search-dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { APP_NAME } from '@/lib/version'
import type { ReactNode, ComponentType } from 'react'
import type { LucideProps } from 'lucide-react'

interface LayoutProps {
  children: ReactNode
}

interface MenuItem {
  icon: ComponentType<LucideProps>
  label: string
  path: string
  tourId?: string
}

interface MenuSection {
  title: string
  items: MenuItem[]
}

const menuIconTileClasses: Record<string, string> = {
  '/': 'ios-symbol-blue',
  '/config/bot': 'ios-symbol-purple',
  '/config/modelProvider': 'ios-symbol-green',
  '/config/model': 'ios-symbol-teal',
  '/config/adapter': 'ios-symbol-purple',
  '/resource/emoji': 'ios-symbol-yellow',
  '/resource/expression': 'ios-symbol-orange',
  '/resource/jargon': 'ios-symbol-pink',
  '/resource/person': 'ios-symbol-blue',
  '/resource/memory': 'ios-symbol-green',
  '/plugins': 'ios-symbol-purple',
  '/plugin-config': 'ios-symbol-teal',
  '/logs': 'ios-symbol-gray',
  '/chat': 'ios-symbol-green',
  '/settings': 'ios-symbol-gray',
}

export function Layout({ children }: LayoutProps) {
  const { checking } = useAuthGuard() // 检查认证状态

  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [mobileActionsOpen, setMobileActionsOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const { theme, setTheme } = useTheme()
  const matchRoute = useMatchRoute()

  // 搜索快捷键监听（Cmd/Ctrl + K）
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setSearchOpen(true)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // 认证检查中，显示加载状态
  if (checking) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="text-muted-foreground">正在验证登录状态...</div>
      </div>
    )
  }

  // 菜单项配置 - 分块结构
  const menuSections: MenuSection[] = [
    {
      title: '概览',
      items: [{ icon: Home, label: '首页', path: '/' }],
    },
    {
      title: '配置编辑',
      items: [
        { icon: FileText, label: '主程序配置', path: '/config/bot' },
        {
          icon: Server,
          label: 'AI模型厂商配置',
          path: '/config/modelProvider',
          tourId: 'sidebar-model-provider',
        },
        {
          icon: Boxes,
          label: '模型管理与分配',
          path: '/config/model',
          tourId: 'sidebar-model-management',
        },
        { icon: Sliders, label: '适配器配置', path: '/config/adapter' },
      ],
    },
    {
      title: '资源管理',
      items: [
        { icon: Smile, label: '表情包管理', path: '/resource/emoji' },
        { icon: MessageSquare, label: '表达方式管理', path: '/resource/expression' },
        { icon: Hash, label: '黑话管理', path: '/resource/jargon' },
        { icon: UserCircle, label: '人物信息管理', path: '/resource/person' },
        { icon: BrainCircuit, label: '记忆系统概览', path: '/resource/memory' },
      ],
    },
    {
      title: '扩展与监控',
      items: [
        { icon: Package, label: '插件市场', path: '/plugins' },
        { icon: Sliders, label: '插件配置', path: '/plugin-config' },
        { icon: FileSearch, label: '日志查看器', path: '/logs' },
        { icon: MessageSquare, label: '本地聊天室', path: '/chat' },
      ],
    },
    {
      title: '系统',
      items: [{ icon: Settings, label: '系统设置', path: '/settings' }],
    },
  ]

  // 获取实际应用的主题（处理 system 情况）
  const getActualTheme = () => {
    if (theme === 'system') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }
    return theme
  }

  const actualTheme = getActualTheme()

  // 登出处理
  const handleLogout = async () => {
    await logout()
  }

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-screen overflow-hidden bg-background">
        {/* Sidebar */}
        <aside
          className={cn(
            'lg:bg-background/72 fixed inset-y-0 left-0 z-50 flex w-[min(86vw,22rem)] max-w-[22rem] flex-col overflow-hidden rounded-r-[28px] border-r border-white/70 bg-white/[0.86] shadow-[18px_0_48px_rgba(31,41,55,0.14)] backdrop-blur-2xl transition-all duration-[520ms] ease-[cubic-bezier(0.2,0,0,1)] dark:border-white/10 dark:bg-zinc-950/[0.86] dark:shadow-[18px_0_54px_rgba(0,0,0,0.38)] lg:relative lg:z-0 lg:w-auto lg:max-w-none lg:rounded-none lg:border-border/45 lg:shadow-none lg:backdrop-blur-2xl',
            sidebarOpen ? 'lg:w-64' : 'lg:w-16',
            mobileMenuOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
          )}
        >
          {/* Logo 区域 */}
          <div className="flex h-[4.25rem] items-center justify-between border-b border-border/35 bg-white/[0.42] px-5 dark:bg-white/[0.04] lg:h-16 lg:border-border/45 lg:bg-transparent lg:px-4">
            <div
              className={cn(
                'relative flex min-w-0 flex-1 items-center justify-center overflow-hidden transition-all duration-[420ms] ease-[cubic-bezier(0.2,0,0,1)] lg:justify-center',
                // 移动端始终完整显示,桌面端根据 sidebarOpen 切换
                'lg:flex-1',
                !sidebarOpen && 'lg:w-8 lg:flex-none'
              )}
            >
              {/* 移动端始终显示完整 Logo，桌面端根据 sidebarOpen 切换 */}
              <div className={cn('flex min-w-0 flex-1 items-center', !sidebarOpen && 'lg:hidden')}>
                <span
                  className="lg:text-primary-gradient min-w-0 truncate text-[21px] font-semibold leading-tight text-foreground lg:text-xl"
                  title={APP_NAME}
                >
                  {APP_NAME}
                </span>
              </div>
              {/* 折叠时的 Logo - 仅桌面端显示 */}
              {!sidebarOpen && (
                <span className="text-primary-gradient hidden text-2xl font-semibold lg:block">
                  R
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => setMobileMenuOpen(false)}
              className="ios-touch ml-3 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted/70 text-muted-foreground hover:bg-muted lg:hidden"
              aria-label="关闭菜单"
              title="关闭菜单"
            >
              <X className="h-[17px] w-[17px]" />
            </button>
          </div>

          <ScrollArea className={cn('flex-1 overflow-x-hidden', !sidebarOpen && 'lg:w-16')}>
            <nav className={cn('px-5 py-4 lg:p-3', !sidebarOpen && 'lg:w-16 lg:p-2')}>
              <ul
                className={cn(
                  // 移动端始终使用正常间距,桌面端根据 sidebarOpen 切换
                  'space-y-5 lg:space-y-5',
                  !sidebarOpen && 'lg:w-full lg:space-y-3'
                )}
              >
                {menuSections.map((section, sectionIndex) => (
                  <li key={section.title}>
                    {/* 块标题 - 移动端始终可见，桌面端根据 sidebarOpen 切换 */}
                    <div
                      className={cn(
                        'mb-2 h-[1.25rem] px-1.5 lg:px-3',
                        // 移动端始终显示，桌面端根据状态切换
                        !sidebarOpen && 'lg:invisible lg:mb-1'
                      )}
                    >
                      <h3 className="whitespace-nowrap text-[12px] font-medium leading-5 text-muted-foreground/80 lg:text-xs lg:font-semibold lg:uppercase lg:text-muted-foreground/70">
                        {section.title}
                      </h3>
                    </div>

                    {/* 分割线 - 仅在桌面端折叠时显示 */}
                    {!sidebarOpen && sectionIndex > 0 && (
                      <div className="mb-2 hidden border-t border-border lg:block" />
                    )}

                    {/* 菜单项列表 */}
                    <ul className="ios-group overflow-hidden lg:space-y-1 lg:overflow-visible lg:rounded-none lg:border-0 lg:bg-transparent lg:shadow-none lg:backdrop-blur-none">
                      {section.items.map((item) => {
                        const isActive = matchRoute({ to: item.path })
                        const Icon = item.icon
                        const iconTileClass = menuIconTileClasses[item.path] ?? 'ios-symbol-gray'

                        const menuItemContent = (
                          <>
                            {/* 左侧高亮条 */}
                            {isActive && (
                              <div className="absolute inset-y-3 left-0 w-1 rounded-full bg-primary transition-opacity duration-[360ms] lg:inset-y-1 lg:left-1" />
                            )}
                            <div
                              className={cn(
                                'flex items-center transition-all duration-[360ms] ease-[cubic-bezier(0.2,0,0,1)]',
                                sidebarOpen ? 'gap-3' : 'gap-3 lg:gap-0'
                              )}
                            >
                              <span
                                className={cn(
                                  'ios-symbol ios-symbol-sm',
                                  iconTileClass,
                                  'lg:h-auto lg:w-auto lg:bg-transparent lg:text-muted-foreground lg:shadow-none',
                                  isActive && 'lg:text-primary'
                                )}
                              >
                                <Icon
                                  className="h-[18px] w-[18px] flex-shrink-0 lg:h-5 lg:w-5"
                                  strokeWidth={2}
                                  fill="none"
                                />
                              </span>
                              <span
                                className={cn(
                                  'whitespace-nowrap text-[16px] font-medium leading-6 transition-all duration-[360ms] ease-[cubic-bezier(0.2,0,0,1)] lg:text-sm lg:leading-normal',
                                  isActive && 'font-semibold',
                                  sidebarOpen
                                    ? 'max-w-[200px] opacity-100'
                                    : 'max-w-[200px] opacity-100 lg:max-w-0 lg:overflow-hidden lg:opacity-0'
                                )}
                              >
                                {item.label}
                              </span>
                            </div>
                          </>
                        )

                        return (
                          <li key={item.path} className="relative">
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Link
                                  to={item.path}
                                  data-tour={item.tourId}
                                  className={cn(
                                    'group relative flex min-h-[58px] items-center border-b border-border/50 py-3 transition-[background-color,color,box-shadow,transform] duration-[260ms] ease-[cubic-bezier(0.2,0,0,1)] last:border-b-0 active:scale-[0.99] lg:min-h-12 lg:rounded-lg lg:border-b-0 lg:py-2 lg:active:scale-[0.98]',
                                    'hover:bg-accent/45 hover:text-accent-foreground dark:hover:bg-white/[0.08] lg:hover:bg-white/55 lg:hover:shadow-[0_4px_14px_rgba(31,41,55,0.045)]',
                                    isActive
                                      ? 'lg:bg-white/62 bg-primary/[0.075] text-foreground dark:bg-white/[0.08] lg:shadow-[inset_0_0_0_1px_rgba(0,0,0,0.025),0_6px_18px_rgba(31,41,55,0.055)]'
                                      : 'text-muted-foreground hover:text-foreground',
                                    sidebarOpen
                                      ? 'px-4 lg:px-3'
                                      : 'px-4 lg:mx-auto lg:w-12 lg:justify-center lg:px-0'
                                  )}
                                  onClick={() => setMobileMenuOpen(false)}
                                >
                                  {menuItemContent}
                                  <ChevronRight className="ml-auto h-4 w-4 text-muted-foreground/70 lg:hidden" />
                                </Link>
                              </TooltipTrigger>
                              {!sidebarOpen && (
                                <TooltipContent side="right" className="hidden lg:block">
                                  <p>{item.label}</p>
                                </TooltipContent>
                              )}
                            </Tooltip>
                          </li>
                        )
                      })}
                    </ul>
                  </li>
                ))}
              </ul>
            </nav>
          </ScrollArea>
        </aside>

        {/* Mobile overlay */}
        {mobileMenuOpen && (
          <div
            className="fixed inset-0 z-40 bg-black/20 backdrop-blur-[6px] lg:hidden"
            onClick={() => setMobileMenuOpen(false)}
          />
        )}

        {/* Main content */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Topbar */}
          <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-border/25 bg-white/[0.76] px-4 backdrop-blur-2xl dark:bg-zinc-950/[0.72] sm:h-16 sm:px-4">
            <div className="z-10 flex min-w-0 items-center gap-2 sm:gap-4">
              {/* 移动端菜单按钮 */}
              <button
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                className="ios-touch flex h-8 w-8 items-center justify-center rounded-full bg-muted/70 text-foreground/85 hover:bg-muted lg:hidden"
                aria-label={mobileMenuOpen ? '关闭菜单' : '打开菜单'}
              >
                <Menu className="h-[17px] w-[17px]" />
              </button>

              {/* 桌面端侧边栏收起/展开按钮 */}
              <button
                onClick={() => setSidebarOpen(!sidebarOpen)}
                className="ios-touch hidden h-11 w-11 items-center justify-center rounded-full hover:bg-accent lg:flex"
                title={sidebarOpen ? '收起侧边栏' : '展开侧边栏'}
              >
                <ChevronLeft
                  className={cn('h-5 w-5 transition-transform', !sidebarOpen && 'rotate-180')}
                />
              </button>
            </div>

            <div className="pointer-events-none absolute inset-x-16 flex justify-center lg:hidden">
              <span className="truncate text-[17px] font-semibold leading-6 text-foreground">
                {APP_NAME}
              </span>
            </div>

            <div className="z-10 flex items-center gap-1.5 sm:gap-2">
              {/* 搜索框 */}
              <button
                onClick={() => setSearchOpen(true)}
                className="ios-touch relative hidden h-10 w-64 items-center rounded-full border border-black/[0.025] bg-muted/65 pl-10 pr-16 text-left shadow-[inset_0_1px_1px_rgba(0,0,0,0.025)] hover:bg-muted/80 md:flex"
              >
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <span className="text-sm text-muted-foreground">搜索...</span>
                <Kbd size="sm" className="absolute right-2 top-1/2 -translate-y-1/2">
                  <span className="text-xs">⌘</span>K
                </Kbd>
              </button>

              {/* 搜索对话框 */}
              <SearchDialog open={searchOpen} onOpenChange={setSearchOpen} />

              <button
                onClick={() => setSearchOpen(true)}
                className="ios-touch flex h-8 w-8 items-center justify-center rounded-full bg-muted/70 text-foreground/85 hover:bg-muted md:hidden"
                aria-label="搜索"
                title="搜索"
              >
                <Search className="h-[17px] w-[17px]" />
              </button>

              {/* 项目文档链接 */}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => window.open('https://docs.mai-mai.org', '_blank')}
                className="hidden h-10 w-10 gap-2 px-0 sm:inline-flex sm:h-11 sm:w-auto sm:px-4"
                title="查看项目文档"
              >
                <BookOpen className="h-4 w-4" />
                <span className="hidden sm:inline">项目文档</span>
              </Button>

              {/* 主题切换按钮 */}
              <button
                onClick={(e) => {
                  const newTheme = actualTheme === 'dark' ? 'light' : 'dark'
                  toggleThemeWithTransition(newTheme, setTheme, e)
                }}
                className="ios-touch hidden h-10 w-10 items-center justify-center rounded-full hover:bg-accent sm:flex sm:h-11 sm:w-11"
                title={actualTheme === 'dark' ? '切换到浅色模式' : '切换到深色模式'}
              >
                {actualTheme === 'dark' ? (
                  <Sun className="h-5 w-5" />
                ) : (
                  <Moon className="h-5 w-5" />
                )}
              </button>

              {/* 分隔线 */}
              <div className="hidden h-6 w-px bg-border/70 sm:block" />

              {/* 登出按钮 */}
              <Button
                variant="ghost"
                size="sm"
                onClick={handleLogout}
                className="hidden h-10 w-10 gap-2 px-0 sm:inline-flex sm:h-11 sm:w-auto sm:px-4"
                title="登出系统"
              >
                <LogOut className="h-4 w-4" />
                <span className="hidden sm:inline">登出</span>
              </Button>

              <button
                className="ios-touch flex h-8 w-8 items-center justify-center rounded-full bg-muted/70 text-foreground/85 hover:bg-muted sm:hidden"
                aria-label="更多操作"
                title="更多操作"
                onClick={() => setMobileActionsOpen(true)}
              >
                <MoreHorizontal className="h-[18px] w-[18px]" />
              </button>

              <Dialog open={mobileActionsOpen} onOpenChange={setMobileActionsOpen}>
                <DialogContent className="ios-sheet bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-0 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1rem,env(safe-area-inset-bottom))] sm:hidden [&>button:last-child]:hidden">
                  <DialogHeader className="sr-only">
                    <DialogTitle>更多操作</DialogTitle>
                  </DialogHeader>
                  <div className="space-y-3 px-5 pb-2 pt-4">
                    <div className="ios-group overflow-hidden">
                      <button
                        type="button"
                        className="ios-row ios-touch min-h-[58px] w-full text-left focus-visible:bg-accent/60 focus-visible:ring-0"
                        onClick={() => {
                          setMobileActionsOpen(false)
                          window.open('https://docs.mai-mai.org', '_blank')
                        }}
                      >
                        <span className="flex items-center gap-3">
                          <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                            <BookOpen className="h-[18px] w-[18px]" />
                          </span>
                          <span className="text-[17px] font-medium leading-6">项目文档</span>
                        </span>
                      </button>
                      <button
                        type="button"
                        className="ios-row ios-touch min-h-[58px] w-full text-left focus-visible:bg-accent/60 focus-visible:ring-0"
                        onClick={(e) => {
                          setMobileActionsOpen(false)
                          const newTheme = actualTheme === 'dark' ? 'light' : 'dark'
                          toggleThemeWithTransition(newTheme, setTheme, e)
                        }}
                      >
                        <span className="flex items-center gap-3">
                          <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                            {actualTheme === 'dark' ? (
                              <Sun className="h-[18px] w-[18px]" />
                            ) : (
                              <Moon className="h-[18px] w-[18px]" />
                            )}
                          </span>
                          <span className="text-[17px] font-medium leading-6">
                            {actualTheme === 'dark' ? '浅色模式' : '深色模式'}
                          </span>
                        </span>
                      </button>
                      <button
                        type="button"
                        className="ios-row ios-touch text-destructive min-h-[58px] w-full text-left focus-visible:bg-accent/60 focus-visible:ring-0"
                        onClick={() => {
                          setMobileActionsOpen(false)
                          void handleLogout()
                        }}
                      >
                        <span className="flex items-center gap-3">
                          <span className="ios-symbol ios-symbol-sm ios-symbol-red">
                            <LogOut className="h-[18px] w-[18px]" />
                          </span>
                          <span className="text-[17px] font-medium leading-6">登出系统</span>
                        </span>
                      </button>
                    </div>

                    <button
                      type="button"
                      className="ios-group ios-touch flex min-h-[52px] w-full items-center justify-center px-4 text-[17px] font-semibold leading-6 text-primary focus-visible:bg-accent/60 focus-visible:ring-0"
                      onClick={() => setMobileActionsOpen(false)}
                    >
                      取消
                    </button>
                  </div>
                </DialogContent>
              </Dialog>
            </div>
          </header>

          {/* Page content */}
          <main className="flex-1 overflow-hidden bg-background">{children}</main>
        </div>
      </div>
    </TooltipProvider>
  )
}
