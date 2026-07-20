import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  CircleDot,
  Eye,
  EyeOff,
  Loader2,
  MessageCircle,
  Pencil,
  Radio,
  RefreshCw,
  Save,
  Server,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Volume2,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/hooks/use-toast'
import {
  getAdapterInstances,
  getManagedAdapterConfig,
  saveManagedAdapterConfig,
} from '@/lib/adapter-config-api'
import type {
  AdapterInstance,
  AdapterRuntimeStatus,
  ManagedAdapterConfig,
} from '@/lib/adapter-config-api'
import { cn } from '@/lib/utils'

const STATUS_PRESENTATION: Record<
  AdapterRuntimeStatus,
  { label: string; dot: string; badge: string }
> = {
  connected: {
    label: '已连接',
    dot: 'bg-emerald-500',
    badge: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  },
  listening: {
    label: '等待连接',
    dot: 'bg-sky-500',
    badge: 'border-sky-500/20 bg-sky-500/10 text-sky-700 dark:text-sky-300',
  },
  starting: {
    label: '启动中',
    dot: 'bg-amber-500',
    badge: 'border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  },
  error: {
    label: '异常',
    dot: 'bg-red-500',
    badge: 'border-red-500/20 bg-red-500/10 text-red-700 dark:text-red-300',
  },
  stopped: {
    label: '未运行',
    dot: 'bg-zinc-400',
    badge: 'border-zinc-500/15 bg-zinc-500/10 text-zinc-600 dark:text-zinc-300',
  },
}

interface AdapterConfigDraft {
  host: string
  port: string
  token: string
  heartbeatInterval: string
  groupListType: 'whitelist' | 'blacklist'
  groupList: string
  privateListType: 'whitelist' | 'blacklist'
  privateList: string
  bannedUsers: string
  banQqBot: boolean
  enablePoke: boolean
  useTts: boolean
  imageThreshold: string
  logLevel: ManagedAdapterConfig['debug']['level']
}

function createDraft(config: ManagedAdapterConfig): AdapterConfigDraft {
  return {
    host: config.napcat_server.host,
    port: String(config.napcat_server.port),
    token: config.napcat_server.token,
    heartbeatInterval: String(config.napcat_server.heartbeat_interval),
    groupListType: config.chat.group_list_type,
    groupList: config.chat.group_list.join(', '),
    privateListType: config.chat.private_list_type,
    privateList: config.chat.private_list.join(', '),
    bannedUsers: config.chat.ban_user_id.join(', '),
    banQqBot: config.chat.ban_qq_bot,
    enablePoke: config.chat.enable_poke,
    useTts: config.voice.use_tts,
    imageThreshold: String(config.forward.image_threshold),
    logLevel: config.debug.level,
  }
}

function parseInteger(value: string, label: string, minimum: number, maximum: number): number {
  const normalized = value.trim()
  if (!/^\d+$/.test(normalized)) {
    throw new Error(`${label}必须是整数`)
  }
  const parsed = Number(normalized)
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${label}必须在 ${minimum} 到 ${maximum} 之间`)
  }
  return parsed
}

function parseIdList(value: string, label: string): number[] {
  const entries = value
    .split(/[\s,，]+/)
    .map((entry) => entry.trim())
    .filter(Boolean)
  const parsed = entries.map((entry) => parseInteger(entry, label, 0, Number.MAX_SAFE_INTEGER))
  return [...new Set(parsed)]
}

function isLoopbackHost(host: string): boolean {
  const normalized = host
    .trim()
    .toLowerCase()
    .replace(/^\[|\]$/g, '')
    .replace(/\.$/, '')
  return normalized === 'localhost' || normalized === '::1' || normalized.startsWith('127.')
}

function buildConfig(draft: AdapterConfigDraft): ManagedAdapterConfig {
  const host = draft.host.trim()
  if (!host) throw new Error('监听地址不能为空')
  if (!isLoopbackHost(host) && !draft.token.trim()) {
    throw new Error('非本机监听地址必须设置访问令牌')
  }

  return {
    napcat_server: {
      host,
      port: parseInteger(draft.port, '监听端口', 1, 65535),
      token: draft.token,
      heartbeat_interval: parseInteger(draft.heartbeatInterval, '心跳间隔', 1, 3600),
    },
    chat: {
      group_list_type: draft.groupListType,
      group_list: parseIdList(draft.groupList, '群号'),
      private_list_type: draft.privateListType,
      private_list: parseIdList(draft.privateList, 'QQ 号'),
      ban_user_id: parseIdList(draft.bannedUsers, '禁用 QQ 号'),
      ban_qq_bot: draft.banQqBot,
      enable_poke: draft.enablePoke,
    },
    voice: { use_tts: draft.useTts },
    forward: {
      image_threshold: parseInteger(draft.imageThreshold, '图片阈值', 0, 1000),
    },
    debug: { level: draft.logLevel },
  }
}

function formatTimestamp(timestamp?: number | null): string | null {
  if (!timestamp) return null
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(timestamp * 1000))
}

export function AdapterConfigPage() {
  const { toast } = useToast()
  const [instances, setInstances] = useState<AdapterInstance[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingInstance, setEditingInstance] = useState<AdapterInstance | null>(null)
  const [draft, setDraft] = useState<AdapterConfigDraft | null>(null)
  const [configLoading, setConfigLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [showToken, setShowToken] = useState(false)

  const loadInstances = useCallback(
    async (showError = true) => {
      try {
        const nextInstances = await getAdapterInstances()
        setInstances(nextInstances)
        setEditingInstance((current) =>
          current
            ? nextInstances.find((instance) => instance.id === current.id) || current
            : current
        )
      } catch (error) {
        if (showError) {
          toast({
            title: '读取失败',
            description: error instanceof Error ? error.message : '无法读取平台实例',
            variant: 'destructive',
          })
        }
      } finally {
        setLoading(false)
        setRefreshing(false)
      }
    },
    [toast]
  )

  useEffect(() => {
    void loadInstances()
    const interval = window.setInterval(() => void loadInstances(false), 5000)
    return () => window.clearInterval(interval)
  }, [loadInstances])

  const handleRefresh = () => {
    setRefreshing(true)
    void loadInstances()
  }

  const openEditor = async (instance: AdapterInstance) => {
    setEditingInstance(instance)
    setDraft(null)
    setShowToken(false)
    setConfigLoading(true)
    setEditorOpen(true)
    try {
      const config = await getManagedAdapterConfig(instance.id)
      setDraft(createDraft(config))
    } catch (error) {
      toast({
        title: '读取失败',
        description: error instanceof Error ? error.message : '无法读取平台配置',
        variant: 'destructive',
      })
      setEditorOpen(false)
    } finally {
      setConfigLoading(false)
    }
  }

  const saveConfig = async () => {
    if (!editingInstance || !draft) return
    try {
      setSaving(true)
      await saveManagedAdapterConfig(editingInstance.id, buildConfig(draft))
      toast({ title: '保存成功', description: '平台配置已更新，连接参数将自动重载' })
      setEditorOpen(false)
      setRefreshing(true)
      await loadInstances(false)
    } catch (error) {
      toast({
        title: '保存失败',
        description: error instanceof Error ? error.message : '无法保存平台配置',
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <TooltipProvider delayDuration={250}>
      <ScrollArea className="h-full">
        <div className="ios-page space-y-5 sm:space-y-6">
          <header className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="ios-title">平台接入</h1>
              <p className="ios-subtitle hidden sm:block">消息平台实例与连接状态</p>
            </div>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="h-11 w-11 shrink-0"
                  onClick={handleRefresh}
                  disabled={refreshing}
                  aria-label="刷新平台状态"
                >
                  <RefreshCw className={cn('h-4 w-4', refreshing && 'animate-spin')} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>刷新状态</TooltipContent>
            </Tooltip>
          </header>

          <section aria-label="平台实例">
            {loading ? (
              <div className="ios-group flex min-h-40 items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : instances.length === 0 ? (
              <div className="ios-group flex min-h-40 flex-col items-center justify-center gap-3 text-muted-foreground">
                <AlertCircle className="h-6 w-6" />
                <span className="text-sm">未发现平台实例</span>
              </div>
            ) : (
              <div className="grid gap-4">
                {instances.map((instance) => (
                  <AdapterInstanceRow
                    key={instance.id}
                    instance={instance}
                    onEdit={() => void openEditor(instance)}
                  />
                ))}
              </div>
            )}
          </section>
        </div>
      </ScrollArea>

      <Dialog open={editorOpen} onOpenChange={(open) => !saving && setEditorOpen(open)}>
        <DialogContent className="max-h-[92svh] gap-4 overflow-hidden sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{editingInstance?.name || '平台配置'}</DialogTitle>
            <DialogDescription className="sr-only">编辑平台连接和消息策略</DialogDescription>
          </DialogHeader>

          {configLoading || !draft ? (
            <div className="flex min-h-80 items-center justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <AdapterEditor
              draft={draft}
              onChange={setDraft}
              showToken={showToken}
              onShowToken={setShowToken}
            />
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setEditorOpen(false)}
              disabled={saving}
            >
              取消
            </Button>
            <Button type="button" onClick={() => void saveConfig()} disabled={saving || !draft}>
              {saving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              {saving ? '保存中' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TooltipProvider>
  )
}

function AdapterInstanceRow({
  instance,
  onEdit,
}: {
  instance: AdapterInstance
  onEdit: () => void
}) {
  const presentation = STATUS_PRESENTATION[instance.status]
  const lastEvent = formatTimestamp(instance.last_event_at)
  const connectedAt = formatTimestamp(instance.connected_at)
  const identityLabel =
    instance.identity?.nickname || instance.identity?.account_id || '连接后自动识别'

  return (
    <article className="ios-group overflow-hidden">
      <div className="flex flex-col gap-5 p-5 sm:flex-row sm:items-center sm:p-6">
        <div className="flex min-w-0 flex-1 items-center gap-4">
          <span className="ios-symbol ios-symbol-md ios-symbol-green shrink-0">
            <MessageCircle className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-base font-semibold leading-6">{instance.name}</h2>
              <Badge variant="outline" className={presentation.badge}>
                <span className={cn('mr-1.5 h-1.5 w-1.5 rounded-full', presentation.dot)} />
                {presentation.label}
              </Badge>
            </div>
            <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
              <span className="truncate font-medium text-foreground">{identityLabel}</span>
              {instance.identity?.account_id && instance.identity.nickname ? (
                <span className="font-mono text-xs">{instance.identity.account_id}</span>
              ) : null}
              <span className="font-mono text-xs">
                {instance.connection.host}:{instance.connection.port}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border/60 pt-4 sm:justify-end sm:border-l sm:border-t-0 sm:pl-5 sm:pt-0">
          <div className="min-w-0 text-xs leading-5 text-muted-foreground sm:text-right">
            <div>
              {lastEvent
                ? `最近事件 ${lastEvent}`
                : connectedAt
                  ? `连接于 ${connectedAt}`
                  : '暂无连接记录'}
            </div>
            {instance.last_error ? (
              <div className="text-destructive">{instance.last_error}</div>
            ) : null}
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-11 w-11 shrink-0"
                onClick={onEdit}
              >
                <Pencil className="h-4 w-4" />
                <span className="sr-only">编辑平台配置</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>编辑配置</TooltipContent>
          </Tooltip>
        </div>
      </div>
    </article>
  )
}

function AdapterEditor({
  draft,
  onChange,
  showToken,
  onShowToken,
}: {
  draft: AdapterConfigDraft
  onChange: (draft: AdapterConfigDraft) => void
  showToken: boolean
  onShowToken: (show: boolean) => void
}) {
  const update = <Key extends keyof AdapterConfigDraft>(
    key: Key,
    value: AdapterConfigDraft[Key]
  ) => {
    onChange({ ...draft, [key]: value })
  }

  return (
    <Tabs defaultValue="connection" className="min-h-0 flex-1 overflow-hidden">
      <TabsList className="grid h-11 w-full grid-cols-3">
        <TabsTrigger value="connection" className="gap-2">
          <Server className="h-4 w-4" />
          <span>连接</span>
        </TabsTrigger>
        <TabsTrigger value="chat" className="gap-2">
          <ShieldCheck className="h-4 w-4" />
          <span>聊天</span>
        </TabsTrigger>
        <TabsTrigger value="advanced" className="gap-2">
          <Settings2 className="h-4 w-4" />
          <span>高级</span>
        </TabsTrigger>
      </TabsList>

      <ScrollArea className="mt-4 h-[min(58svh,520px)] pr-3">
        <TabsContent value="connection" className="m-0 space-y-5">
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_10rem]">
            <Field label="监听地址" htmlFor="adapter-host">
              <Input
                id="adapter-host"
                value={draft.host}
                onChange={(event) => update('host', event.target.value)}
              />
            </Field>
            <Field label="端口" htmlFor="adapter-port">
              <Input
                id="adapter-port"
                type="number"
                min={1}
                max={65535}
                inputMode="numeric"
                value={draft.port}
                onChange={(event) => update('port', event.target.value)}
              />
            </Field>
          </div>

          <Field label="访问令牌" htmlFor="adapter-token">
            <div className="relative">
              <Input
                id="adapter-token"
                type={showToken ? 'text' : 'password'}
                value={draft.token}
                onChange={(event) => update('token', event.target.value)}
                className="pr-11"
                autoComplete="new-password"
              />
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="ios-touch absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                    onClick={() => onShowToken(!showToken)}
                    aria-label={showToken ? '隐藏访问令牌' : '显示访问令牌'}
                  >
                    {showToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </TooltipTrigger>
                <TooltipContent>{showToken ? '隐藏令牌' : '显示令牌'}</TooltipContent>
              </Tooltip>
            </div>
          </Field>

          <Field label="心跳间隔（秒）" htmlFor="adapter-heartbeat">
            <Input
              id="adapter-heartbeat"
              type="number"
              min={1}
              max={3600}
              inputMode="numeric"
              value={draft.heartbeatInterval}
              onChange={(event) => update('heartbeatInterval', event.target.value)}
            />
          </Field>
        </TabsContent>

        <TabsContent value="chat" className="m-0 space-y-5">
          <ListPolicyField
            id="adapter-group-list"
            label="群聊名单"
            mode={draft.groupListType}
            value={draft.groupList}
            onModeChange={(value) => update('groupListType', value)}
            onValueChange={(value) => update('groupList', value)}
          />
          <ListPolicyField
            id="adapter-private-list"
            label="私聊名单"
            mode={draft.privateListType}
            value={draft.privateList}
            onModeChange={(value) => update('privateListType', value)}
            onValueChange={(value) => update('privateList', value)}
          />
          <Field label="全局禁用账号" htmlFor="adapter-banned-users">
            <Textarea
              id="adapter-banned-users"
              rows={3}
              value={draft.bannedUsers}
              onChange={(event) => update('bannedUsers', event.target.value)}
              placeholder="10001, 10002"
              className="resize-y"
            />
          </Field>
          <div className="ios-group divide-y divide-border/60 overflow-hidden">
            <SwitchRow
              icon={CircleDot}
              title="屏蔽 QQ 官方机器人"
              checked={draft.banQqBot}
              onCheckedChange={(checked) => update('banQqBot', checked)}
            />
            <SwitchRow
              icon={Radio}
              title="响应戳一戳"
              checked={draft.enablePoke}
              onCheckedChange={(checked) => update('enablePoke', checked)}
            />
          </div>
        </TabsContent>

        <TabsContent value="advanced" className="m-0 space-y-5">
          <div className="ios-group divide-y divide-border/60 overflow-hidden">
            <SwitchRow
              icon={Volume2}
              title="发送 TTS 语音"
              checked={draft.useTts}
              onCheckedChange={(checked) => update('useTts', checked)}
            />
          </div>
          <Field label="转发消息图片阈值" htmlFor="adapter-image-threshold">
            <Input
              id="adapter-image-threshold"
              type="number"
              min={0}
              max={1000}
              inputMode="numeric"
              value={draft.imageThreshold}
              onChange={(event) => update('imageThreshold', event.target.value)}
            />
          </Field>
          <Field label="日志等级" htmlFor="adapter-log-level">
            <Select
              value={draft.logLevel}
              onValueChange={(value) => update('logLevel', value as AdapterConfigDraft['logLevel'])}
            >
              <SelectTrigger id="adapter-log-level">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const).map((level) => (
                  <SelectItem key={level} value={level}>
                    {level}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        </TabsContent>
      </ScrollArea>
    </Tabs>
  )
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string
  htmlFor: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  )
}

function ListPolicyField({
  id,
  label,
  mode,
  value,
  onModeChange,
  onValueChange,
}: {
  id: string
  label: string
  mode: 'whitelist' | 'blacklist'
  value: string
  onModeChange: (mode: 'whitelist' | 'blacklist') => void
  onValueChange: (value: string) => void
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <Label htmlFor={id}>{label}</Label>
        <Select value={mode} onValueChange={(nextMode) => onModeChange(nextMode as typeof mode)}>
          <SelectTrigger className="h-9 w-28">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="whitelist">白名单</SelectItem>
            <SelectItem value="blacklist">黑名单</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <Textarea
        id={id}
        rows={3}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        placeholder="10001, 10002"
        className="resize-y"
      />
    </div>
  )
}

function SwitchRow({
  icon: Icon,
  title,
  checked,
  onCheckedChange,
}: {
  icon: typeof SlidersHorizontal
  title: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}) {
  const switchId = useMemo(() => `adapter-switch-${title.replace(/\s+/g, '-')}`, [title])
  return (
    <div className="ios-row min-h-16 gap-4 py-3">
      <Label
        htmlFor={switchId}
        className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 font-medium"
      >
        <span className="ios-symbol ios-symbol-sm ios-symbol-blue shrink-0">
          <Icon className="h-4 w-4" />
        </span>
        <span className="truncate">{title}</span>
      </Label>
      <Switch id={switchId} checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  )
}
