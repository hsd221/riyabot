import { useState, useEffect, useCallback } from 'react'
import {
  Search,
  FileText,
  Server,
  Boxes,
  Smile,
  MessageSquare,
  UserCircle,
  FileSearch,
  Package,
  Settings,
  Home,
  Hash,
  BrainCircuit,
  Activity,
  BarChart3,
  Sliders,
  MessageCircle,
  Globe,
  ChevronRight,
  ScanSearch,
  UploadCloud,
} from 'lucide-react'
import { useNavigate } from '@tanstack/react-router'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Kbd } from '@/components/ui/kbd'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'

interface SearchDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

interface SearchItem {
  icon: React.ComponentType<{ className?: string }>
  title: string
  description: string
  path: string
  category: string
}

const searchIconTileClasses: Record<string, string> = {
  '/': 'ios-symbol-blue',
  '/statistics': 'ios-symbol-blue',
  '/config/bot': 'ios-symbol-purple',
  '/config/modelProvider': 'ios-symbol-green',
  '/config/model': 'ios-symbol-teal',
  '/config/adapter': 'ios-symbol-purple',
  '/resource/emoji': 'ios-symbol-yellow',
  '/resource/expression': 'ios-symbol-orange',
  '/resource/behavior': 'ios-symbol-purple',
  '/resource/chat-history-import': 'ios-symbol-teal',
  '/resource/jargon': 'ios-symbol-pink',
  '/resource/person': 'ios-symbol-blue',
  '/resource/memory': 'ios-symbol-green',
  '/plugins': 'ios-symbol-purple',
  '/plugin-config': 'ios-symbol-teal',
  '/plugin-mirrors': 'ios-symbol-purple',
  '/chat': 'ios-symbol-green',
  '/model-traces': 'ios-symbol-teal',
  '/logs': 'ios-symbol-gray',
  '/settings': 'ios-symbol-gray',
}

const searchItems: SearchItem[] = [
  {
    icon: Home,
    title: '首页',
    description: '查看仪表板概览',
    path: '/',
    category: '概览',
  },
  {
    icon: BarChart3,
    title: '统计数据',
    description: '查看模型、模块、请求与聊天统计',
    path: '/statistics',
    category: '概览',
  },
  {
    icon: FileText,
    title: '主程序配置',
    description: '配置主程序的核心设置',
    path: '/config/bot',
    category: '配置',
  },
  {
    icon: Server,
    title: '模型提供商配置',
    description: '配置模型提供商',
    path: '/config/modelProvider',
    category: '配置',
  },
  {
    icon: Boxes,
    title: '模型配置',
    description: '配置模型参数',
    path: '/config/model',
    category: '配置',
  },
  {
    icon: Smile,
    title: '表情包管理',
    description: '管理当前 Bot 的表情包',
    path: '/resource/emoji',
    category: '资源',
  },
  {
    icon: MessageSquare,
    title: '表达方式管理',
    description: '管理当前 Bot 的表达方式',
    path: '/resource/expression',
    category: '资源',
  },
  {
    icon: Activity,
    title: '行为学习管理',
    description: '管理当前 Bot 学习到的行为模式',
    path: '/resource/behavior',
    category: '资源',
  },
  {
    icon: UploadCloud,
    title: '聊天记录学习',
    description: '导入群聊并学习表达、行为与黑话',
    path: '/resource/chat-history-import',
    category: '资源',
  },
  {
    icon: UserCircle,
    title: '人物信息管理',
    description: '管理人物信息',
    path: '/resource/person',
    category: '资源',
  },
  {
    icon: Hash,
    title: '黑话管理',
    description: '管理当前 Bot 学习到的黑话和俚语',
    path: '/resource/jargon',
    category: '资源',
  },
  {
    icon: BrainCircuit,
    title: '记忆系统概览',
    description: '查看记忆原子、梦境运行和洞见',
    path: '/resource/memory',
    category: '资源',
  },
  {
    icon: Sliders,
    title: '平台接入',
    description: '管理消息平台实例与连接',
    path: '/config/adapter',
    category: '配置',
  },
  {
    icon: Package,
    title: '插件市场',
    description: '浏览和安装插件',
    path: '/plugins',
    category: '扩展',
  },
  {
    icon: Sliders,
    title: '插件配置',
    description: '管理已安装插件的配置',
    path: '/plugin-config',
    category: '扩展',
  },
  {
    icon: Globe,
    title: '插件镜像源',
    description: '配置插件下载镜像源',
    path: '/plugin-mirrors',
    category: '扩展',
  },
  {
    icon: MessageCircle,
    title: '本地聊天室',
    description: '在 WebUI 中与当前 Bot 对话',
    path: '/chat',
    category: '监控',
  },
  {
    icon: ScanSearch,
    title: '模型请求追踪',
    description: '查看模型请求与返回内容',
    path: '/model-traces',
    category: '监控',
  },
  {
    icon: FileSearch,
    title: '日志查看器',
    description: '查看系统日志',
    path: '/logs',
    category: '监控',
  },
  {
    icon: Settings,
    title: '系统设置',
    description: '配置系统参数',
    path: '/settings',
    category: '系统',
  },
]

export function SearchDialog({ open, onOpenChange }: SearchDialogProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const navigate = useNavigate()

  // 过滤搜索结果
  const filteredItems = searchItems.filter(
    (item) =>
      item.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.category.toLowerCase().includes(searchQuery.toLowerCase())
  )
  const groupedItems = filteredItems.reduce<Array<{ category: string; items: SearchItem[] }>>(
    (groups, item) => {
      const group = groups.find((entry) => entry.category === item.category)
      if (group) {
        group.items.push(item)
      } else {
        groups.push({ category: item.category, items: [item] })
      }
      return groups
    },
    []
  )

  // 重置状态
  useEffect(() => {
    if (open) {
      setSearchQuery('')
      setSelectedIndex(0)
    }
  }, [open])

  // 导航到页面
  const handleNavigate = useCallback(
    (path: string) => {
      navigate({ to: path })
      onOpenChange(false)
    },
    [navigate, onOpenChange]
  )

  // 键盘导航
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        if (filteredItems.length === 0) return
        setSelectedIndex((prev) => (prev + 1) % filteredItems.length)
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        if (filteredItems.length === 0) return
        setSelectedIndex((prev) => (prev - 1 + filteredItems.length) % filteredItems.length)
      } else if (e.key === 'Enter' && filteredItems[selectedIndex]) {
        e.preventDefault()
        handleNavigate(filteredItems[selectedIndex].path)
      }
    },
    [filteredItems, selectedIndex, handleNavigate]
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="left-0 top-0 flex h-[100dvh] w-full max-w-none translate-x-0 translate-y-0 flex-col gap-0 rounded-none border-0 bg-background/95 p-0 shadow-none backdrop-blur-2xl sm:left-[50%] sm:top-[50%] sm:h-auto sm:max-h-[80vh] sm:max-w-2xl sm:translate-x-[-50%] sm:translate-y-[-50%] sm:rounded-[22px] sm:border sm:border-black/[0.035] sm:bg-white/[0.86] sm:shadow-[0_20px_64px_rgba(0,0,0,0.16),0_1px_1px_rgba(255,255,255,0.7)_inset] dark:sm:border-white/10 dark:sm:bg-zinc-950/[0.86] [&>button:last-child]:hidden sm:[&>button:last-child]:flex">
        <DialogHeader className="px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] sm:px-4 sm:pb-0 sm:pt-4">
          <DialogTitle className="sr-only">搜索</DialogTitle>
          <div className="flex items-center gap-2">
            <div className="relative min-w-0 flex-1">
              <Search className="absolute left-3 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-muted-foreground sm:h-5 sm:w-5" />
              <Input
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value)
                  setSelectedIndex(0)
                }}
                onKeyDown={handleKeyDown}
                placeholder="搜索页面"
                className="h-10 rounded-[14px] border-0 bg-muted/80 pl-10 text-[16px] shadow-[inset_0_1px_1px_rgba(0,0,0,0.035)] focus-visible:ring-0 sm:h-12 sm:rounded-[16px] sm:pl-11"
                autoFocus
              />
            </div>
            <DialogClose className="ios-touch shrink-0 rounded-full px-2 py-1 text-[16px] font-medium leading-6 text-primary focus-visible:bg-accent/70 focus-visible:ring-0 sm:hidden">
              取消
            </DialogClose>
          </div>
        </DialogHeader>

        <div className="min-h-0 flex-1 border-t border-border/45 px-4 py-4 sm:border-t sm:px-0 sm:py-0">
          <ScrollArea className="h-[calc(100dvh-5.75rem)] sm:h-[400px]">
            {filteredItems.length > 0 ? (
              <div className="space-y-5 sm:m-2 sm:space-y-2">
                {groupedItems.map((group) => (
                  <div key={group.category} className="space-y-2 sm:space-y-1">
                    <div className="px-1 sm:hidden">
                      <h3 className="text-[13px] font-medium leading-5 text-muted-foreground">
                        {group.category}
                      </h3>
                    </div>
                    <div className="ios-group overflow-hidden sm:rounded-none sm:border-0 sm:bg-transparent sm:shadow-none sm:backdrop-blur-none">
                      {group.items.map((item) => {
                        const index = filteredItems.findIndex(
                          (filteredItem) => filteredItem.path === item.path
                        )
                        const Icon = item.icon
                        const iconTileClass = searchIconTileClasses[item.path] ?? 'ios-symbol-gray'
                        return (
                          <button
                            key={item.path}
                            onClick={() => handleNavigate(item.path)}
                            onMouseEnter={() => setSelectedIndex(index)}
                            className={cn(
                              'ios-row ios-touch min-h-[64px] w-full text-left focus-visible:bg-accent/60 focus-visible:ring-0 sm:min-h-0 sm:rounded-md sm:border-b-0 sm:px-3 sm:py-2.5',
                              index === selectedIndex
                                ? 'sm:bg-accent/55 sm:text-accent-foreground'
                                : 'hover:bg-accent/50'
                            )}
                          >
                            <span className="flex min-w-0 items-center gap-3">
                              <span
                                className={cn(
                                  'ios-symbol h-8 w-8 rounded-[7px] sm:h-7 sm:w-7 sm:rounded-[6px]',
                                  iconTileClass
                                )}
                              >
                                <Icon className="h-[18px] w-[18px] sm:h-4 sm:w-4" />
                              </span>
                              <span className="min-w-0">
                                <span className="block truncate text-[16px] font-medium leading-6 sm:text-sm">
                                  {item.title}
                                </span>
                                <span className="block truncate text-[13px] leading-5 text-muted-foreground sm:text-xs">
                                  {item.description}
                                </span>
                              </span>
                            </span>
                            <span className="flex shrink-0 items-center gap-1.5 text-[14px] leading-5 text-muted-foreground sm:rounded sm:bg-muted sm:px-2 sm:py-1 sm:text-xs">
                              <span className="hidden sm:inline">{item.category}</span>
                              <ChevronRight className="h-4 w-4 sm:hidden" />
                            </span>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex h-full min-h-[260px] flex-col items-center justify-center py-12 text-center">
                <Search className="mb-4 h-12 w-12 text-muted-foreground/50" />
                <p className="text-sm text-muted-foreground">
                  {searchQuery ? '未找到匹配的页面' : '输入关键词开始搜索'}
                </p>
              </div>
            )}
          </ScrollArea>
        </div>

        <div className="hidden border-t border-border/55 px-4 py-3 text-xs text-muted-foreground sm:flex sm:items-center sm:justify-between">
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1">
              <Kbd size="sm">↑</Kbd>
              <Kbd size="sm">↓</Kbd>
              导航
            </span>
            <span className="flex items-center gap-1">
              <Kbd size="sm">Enter</Kbd>
              选择
            </span>
            <span className="flex items-center gap-1">
              <Kbd size="sm">Esc</Kbd>
              关闭
            </span>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
