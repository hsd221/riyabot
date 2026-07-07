import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Switch } from '@/components/ui/switch'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  ArrowLeft,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Cloud,
  GitFork,
  Hash,
  Link2,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  XCircle,
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'

interface MirrorConfig {
  id: string
  name: string
  raw_prefix: string
  clone_prefix: string
  enabled: boolean
  priority: number
  created_at?: string
  updated_at?: string
}

export function PluginMirrorsPage() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const [mirrors, setMirrors] = useState<MirrorConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingMirror, setEditingMirror] = useState<MirrorConfig | null>(null)
  const [selectedMirror, setSelectedMirror] = useState<MirrorConfig | null>(null)
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false)
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false)
  const [isDetailDialogOpen, setIsDetailDialogOpen] = useState(false)

  // 表单状态
  const [formData, setFormData] = useState({
    id: '',
    name: '',
    raw_prefix: '',
    clone_prefix: '',
    enabled: true,
    priority: 1,
  })

  // 加载镜像源列表
  const loadMirrors = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)

      const token = localStorage.getItem('access-token')
      const response = await fetch('/api/webui/plugins/mirrors', {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      })

      if (!response.ok) {
        throw new Error('获取镜像源列表失败')
      }

      const data = await response.json()
      setMirrors(data.mirrors || [])
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : '加载镜像源失败'
      setError(errorMessage)
      toast({
        title: '加载失败',
        description: errorMessage,
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    loadMirrors()
  }, [loadMirrors])

  const resetForm = () => {
    setFormData({
      id: '',
      name: '',
      raw_prefix: '',
      clone_prefix: '',
      enabled: true,
      priority: 1,
    })
  }

  const openAddDialog = () => {
    resetForm()
    setIsAddDialogOpen(true)
  }

  // 添加镜像源
  const handleAddMirror = async () => {
    try {
      const token = localStorage.getItem('access-token')
      const response = await fetch('/api/webui/plugins/mirrors', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || '添加镜像源失败')
      }

      toast({
        title: '添加成功',
        description: '镜像源已添加',
      })

      setIsAddDialogOpen(false)
      resetForm()
      loadMirrors()
    } catch (err) {
      toast({
        title: '添加失败',
        description: err instanceof Error ? err.message : '未知错误',
        variant: 'destructive',
      })
    }
  }

  // 更新镜像源
  const handleUpdateMirror = async () => {
    if (!editingMirror) return

    try {
      const token = localStorage.getItem('access-token')
      const response = await fetch(`/api/webui/plugins/mirrors/${editingMirror.id}`, {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: formData.name,
          raw_prefix: formData.raw_prefix,
          clone_prefix: formData.clone_prefix,
          enabled: formData.enabled,
          priority: formData.priority,
        }),
      })

      if (!response.ok) {
        throw new Error('更新镜像源失败')
      }

      toast({
        title: '更新成功',
        description: '镜像源已更新',
      })

      setIsEditDialogOpen(false)
      setEditingMirror(null)
      loadMirrors()
    } catch (err) {
      toast({
        title: '更新失败',
        description: err instanceof Error ? err.message : '未知错误',
        variant: 'destructive',
      })
    }
  }

  // 删除镜像源
  const handleDeleteMirror = async (id: string): Promise<boolean> => {
    if (!confirm('确定要删除这个镜像源吗？')) return false

    try {
      const token = localStorage.getItem('access-token')
      const response = await fetch(`/api/webui/plugins/mirrors/${id}`, {
        method: 'DELETE',
        headers: {
          Authorization: `Bearer ${token}`,
        },
      })

      if (!response.ok) {
        throw new Error('删除镜像源失败')
      }

      toast({
        title: '删除成功',
        description: '镜像源已删除',
      })

      loadMirrors()
      return true
    } catch (err) {
      toast({
        title: '删除失败',
        description: err instanceof Error ? err.message : '未知错误',
        variant: 'destructive',
      })
      return false
    }
  }

  // 切换启用状态
  const handleToggleEnabled = async (mirror: MirrorConfig) => {
    try {
      const token = localStorage.getItem('access-token')
      const response = await fetch(`/api/webui/plugins/mirrors/${mirror.id}`, {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          enabled: !mirror.enabled,
        }),
      })

      if (!response.ok) {
        throw new Error('更新状态失败')
      }

      loadMirrors()
    } catch (err) {
      toast({
        title: '更新失败',
        description: err instanceof Error ? err.message : '未知错误',
        variant: 'destructive',
      })
    }
  }

  // 打开编辑对话框
  const openEditDialog = (mirror: MirrorConfig) => {
    setIsDetailDialogOpen(false)
    setEditingMirror(mirror)
    setFormData({
      id: mirror.id,
      name: mirror.name,
      raw_prefix: mirror.raw_prefix,
      clone_prefix: mirror.clone_prefix,
      enabled: mirror.enabled,
      priority: mirror.priority,
    })
    setIsEditDialogOpen(true)
  }

  const openDetailDialog = (mirror: MirrorConfig) => {
    setSelectedMirror(mirror)
    setIsDetailDialogOpen(true)
  }

  const toggleSelectedMirror = async () => {
    if (!selectedMirror) return
    setSelectedMirror({ ...selectedMirror, enabled: !selectedMirror.enabled })
    await handleToggleEnabled(selectedMirror)
  }

  const deleteSelectedMirror = async () => {
    if (!selectedMirror) return
    const deleted = await handleDeleteMirror(selectedMirror.id)
    if (deleted) {
      setIsDetailDialogOpen(false)
      setSelectedMirror(null)
    }
  }

  // 调整优先级
  const adjustPriority = async (mirror: MirrorConfig, direction: 'up' | 'down') => {
    const newPriority = direction === 'up' ? mirror.priority - 1 : mirror.priority + 1
    if (newPriority < 1) return

    try {
      const token = localStorage.getItem('access-token')
      const response = await fetch(`/api/webui/plugins/mirrors/${mirror.id}`, {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          priority: newPriority,
        }),
      })

      if (!response.ok) {
        throw new Error('更新优先级失败')
      }

      setSelectedMirror((current) =>
        current?.id === mirror.id ? { ...current, priority: newPriority } : current
      )
      loadMirrors()
    } catch (err) {
      toast({
        title: '更新失败',
        description: err instanceof Error ? err.message : '未知错误',
        variant: 'destructive',
      })
    }
  }

  const activeMirrors = mirrors.filter((mirror) => mirror.enabled).length

  const mirrorSummary = (mirror: MirrorConfig) => {
    if (!mirror.raw_prefix && !mirror.clone_prefix) return '未配置下载前缀'
    try {
      const url = new URL(mirror.raw_prefix || mirror.clone_prefix)
      return url.host
    } catch {
      return mirror.raw_prefix || mirror.clone_prefix
    }
  }

  const MirrorIcon = ({ index, enabled }: { index: number; enabled: boolean }) => {
    const colors = ['bg-[#007AFF]', 'bg-[#34C759]', 'bg-[#FF9500]', 'bg-[#AF52DE]', 'bg-[#FF2D55]']
    return (
      <span
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] text-white shadow-[0_4px_10px_rgba(0,0,0,0.12)] ${
          enabled ? colors[index % colors.length] : 'bg-muted-foreground/40'
        }`}
      >
        <Cloud className="h-4 w-4" />
      </span>
    )
  }

  return (
    <ScrollArea className="h-full w-full max-w-full overflow-x-hidden">
      <div className="ios-page w-screen max-w-full overflow-x-hidden sm:w-full">
        <div className="ios-content min-w-0 max-w-full">
          {/* 标题栏 */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3 sm:items-center sm:gap-4">
              <Button
                variant="ghost"
                size="icon"
                className="ios-touch mt-0.5 h-10 w-10 shrink-0 rounded-full sm:mt-0"
                onClick={() => navigate({ to: '/plugins' })}
              >
                <ArrowLeft className="h-5 w-5" />
              </Button>
              <div className="min-w-0">
                <h1 className="ios-title">镜像源配置</h1>
                <p className="ios-subtitle">管理 Git 克隆和文件下载的镜像源</p>
              </div>
            </div>
            <Button onClick={openAddDialog} className="hidden sm:inline-flex">
              <Plus className="mr-2 h-4 w-4" />
              添加镜像源
            </Button>
          </div>

          {/* 加载状态 */}
          {loading ? (
            <div className="ios-group p-6">
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              </div>
            </div>
          ) : error ? (
            <div className="ios-group p-6">
              <div className="flex flex-col items-center justify-center py-8 text-center">
                <AlertTriangle className="text-destructive mb-4 h-12 w-12" />
                <h3 className="mb-2 text-lg font-semibold">加载失败</h3>
                <p className="mb-4 text-sm text-muted-foreground">{error}</p>
                <Button onClick={loadMirrors}>重新加载</Button>
              </div>
            </div>
          ) : (
            <>
              {/* 镜像源分组列表 */}
              <div className="space-y-5">
                <div className="ios-group overflow-hidden">
                  <button
                    type="button"
                    onClick={openAddDialog}
                    className="ios-row ios-touch min-h-[56px] w-full text-left md:hidden"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-[#007AFF] text-white shadow-[0_4px_10px_rgba(0,122,255,0.22)]">
                        <Plus className="h-4 w-4" />
                      </span>
                      <span className="truncate text-[16px] font-medium leading-6">添加镜像源</span>
                    </div>
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                  </button>

                  <div className="ios-row min-h-[54px]">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-[#34C759] text-white shadow-[0_4px_10px_rgba(52,199,89,0.22)]">
                        <CheckCircle2 className="h-4 w-4" />
                      </span>
                      <span className="text-[16px] font-medium leading-6">已启用</span>
                    </div>
                    <span className="shrink-0 text-[16px] leading-6 text-muted-foreground">
                      {activeMirrors}/{mirrors.length}
                    </span>
                  </div>
                </div>

                {mirrors.length === 0 ? (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between px-1">
                      <p className="text-[13px] font-medium leading-5 text-muted-foreground">
                        镜像源列表
                      </p>
                      <span className="text-[13px] leading-5 text-muted-foreground">共 0 个</span>
                    </div>
                    <div className="ios-group overflow-hidden">
                      <div className="ios-row ios-row-plain min-h-[132px] !justify-center text-center text-muted-foreground">
                        <div className="space-y-2">
                          <span className="mx-auto grid h-10 w-10 place-items-center rounded-[12px] bg-muted text-muted-foreground">
                            <Cloud className="h-5 w-5" />
                          </span>
                          <p className="text-[15px] leading-5">暂无镜像源</p>
                          <p className="max-w-xs text-[13px] leading-5">
                            添加镜像源后，会在这里按优先级显示。
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between px-1">
                      <p className="text-[13px] font-medium leading-5 text-muted-foreground">
                        镜像源列表
                      </p>
                      <span className="text-[13px] leading-5 text-muted-foreground">
                        共 {mirrors.length} 个
                      </span>
                    </div>
                    <div className="ios-group overflow-hidden">
                      {mirrors.map((mirror, index) => (
                        <div
                          key={mirror.id}
                          role="button"
                          tabIndex={0}
                          onClick={() => openDetailDialog(mirror)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault()
                              openDetailDialog(mirror)
                            }
                          }}
                          className="ios-row ios-touch min-h-[76px] cursor-pointer py-3"
                        >
                          <div className="flex min-w-0 items-center gap-3">
                            <MirrorIcon index={index} enabled={mirror.enabled} />
                            <div className="min-w-0">
                              <div className="flex min-w-0 flex-wrap items-center gap-2">
                                <h3 className="truncate text-[16px] font-medium leading-6">
                                  {mirror.name}
                                </h3>
                                <Badge variant="outline" className="shrink-0 font-mono text-[11px]">
                                  {mirror.id}
                                </Badge>
                              </div>
                              <div className="mt-0.5 line-clamp-1 text-[13px] leading-5 text-muted-foreground">
                                {mirrorSummary(mirror)}
                              </div>
                            </div>
                          </div>
                          <div className="ml-auto flex shrink-0 items-center gap-2">
                            <span className="rounded-full bg-secondary px-2 py-0.5 font-mono text-[12px] leading-5 text-secondary-foreground">
                              #{mirror.priority}
                            </span>
                            <div
                              className="hidden items-center gap-1 md:flex"
                              onClick={(event) => event.stopPropagation()}
                            >
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 rounded-full"
                                onClick={() => adjustPriority(mirror, 'up')}
                                disabled={mirror.priority === 1}
                                title="提高优先级"
                              >
                                <ChevronUp className="h-4 w-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 rounded-full"
                                onClick={() => adjustPriority(mirror, 'down')}
                                title="降低优先级"
                              >
                                <ChevronDown className="h-4 w-4" />
                              </Button>
                            </div>
                            <div onClick={(event) => event.stopPropagation()}>
                              <Switch
                                checked={mirror.enabled}
                                onCheckedChange={() => handleToggleEnabled(mirror)}
                              />
                            </div>
                            <div
                              className="hidden items-center gap-1 md:flex"
                              onClick={(event) => event.stopPropagation()}
                            >
                              <Button
                                variant="outline"
                                size="icon"
                                className="h-9 w-9 rounded-full"
                                onClick={() => openEditDialog(mirror)}
                                title="编辑"
                              >
                                <Pencil className="h-4 w-4" />
                              </Button>
                              <Button
                                variant="outline"
                                size="icon"
                                className="text-destructive hover:text-destructive h-9 w-9 rounded-full"
                                onClick={() => handleDeleteMirror(mirror.id)}
                                title="删除"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                            <ChevronRight className="h-4 w-4 text-muted-foreground md:hidden" />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}

          {/* 镜像源详情 */}
          <Dialog open={isDetailDialogOpen} onOpenChange={setIsDetailDialogOpen}>
            <DialogContent className="bottom-0 top-auto max-h-[86vh] translate-y-0 overflow-hidden rounded-b-none rounded-t-[28px] p-0 sm:bottom-auto sm:top-[50%] sm:max-w-lg sm:translate-y-[-50%] sm:rounded-[24px] sm:p-0">
              {selectedMirror && (
                <div className="flex max-h-[86vh] flex-col">
                  <DialogHeader className="px-5 pb-3 pt-6 sm:px-6">
                    <DialogTitle>{selectedMirror.name}</DialogTitle>
                    <DialogDescription>{selectedMirror.id}</DialogDescription>
                  </DialogHeader>

                  <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-4 sm:px-6">
                    <div className="ios-group overflow-hidden">
                      <div className="ios-row min-h-[54px]">
                        <div className="flex min-w-0 items-center gap-3">
                          <span
                            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] text-white ${
                              selectedMirror.enabled ? 'bg-[#34C759]' : 'bg-muted-foreground/40'
                            }`}
                          >
                            {selectedMirror.enabled ? (
                              <CheckCircle2 className="h-4 w-4" />
                            ) : (
                              <XCircle className="h-4 w-4" />
                            )}
                          </span>
                          <span className="text-[16px] font-medium">启用镜像源</span>
                        </div>
                        <Switch
                          checked={selectedMirror.enabled}
                          onCheckedChange={toggleSelectedMirror}
                        />
                      </div>

                      <div className="ios-row min-h-[54px]">
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-[#5856D6] text-white">
                            <Hash className="h-4 w-4" />
                          </span>
                          <span className="text-[16px] font-medium">优先级</span>
                        </div>
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-9 w-9 rounded-full"
                            onClick={() => adjustPriority(selectedMirror, 'up')}
                            disabled={selectedMirror.priority === 1}
                          >
                            <ChevronUp className="h-4 w-4" />
                          </Button>
                          <span className="min-w-8 text-center font-mono text-[15px]">
                            {selectedMirror.priority}
                          </span>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-9 w-9 rounded-full"
                            onClick={() => adjustPriority(selectedMirror, 'down')}
                          >
                            <ChevronDown className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>
                    </div>

                    <div className="ios-group overflow-hidden">
                      <div className="ios-row min-h-[64px] items-start py-3">
                        <div className="flex shrink-0 items-center gap-3">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-[#FF9500] text-white">
                            <Link2 className="h-4 w-4" />
                          </span>
                          <span className="text-[16px] font-medium">Raw 前缀</span>
                        </div>
                        <span className="min-w-0 max-w-[58%] break-all text-right text-[13px] leading-5 text-muted-foreground">
                          {selectedMirror.raw_prefix || '未配置'}
                        </span>
                      </div>

                      <div className="ios-row min-h-[64px] items-start py-3">
                        <div className="flex shrink-0 items-center gap-3">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-[#007AFF] text-white">
                            <GitFork className="h-4 w-4" />
                          </span>
                          <span className="text-[16px] font-medium">克隆前缀</span>
                        </div>
                        <span className="min-w-0 max-w-[58%] break-all text-right text-[13px] leading-5 text-muted-foreground">
                          {selectedMirror.clone_prefix || '未配置'}
                        </span>
                      </div>
                    </div>
                  </div>

                  <DialogFooter className="border-t border-border/45 bg-white/[0.72] px-5 py-4 backdrop-blur-2xl dark:bg-zinc-950/[0.66] sm:px-6">
                    <Button variant="destructive" onClick={deleteSelectedMirror}>
                      <Trash2 className="h-4 w-4" />
                      删除
                    </Button>
                    <Button variant="outline" onClick={() => openEditDialog(selectedMirror)}>
                      <Pencil className="h-4 w-4" />
                      编辑
                    </Button>
                  </DialogFooter>
                </div>
              )}
            </DialogContent>
          </Dialog>

          {/* 添加镜像源对话框 */}
          <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
            <DialogContent className="bottom-0 top-auto max-h-[86vh] translate-y-0 overflow-y-auto rounded-b-none rounded-t-[28px] sm:bottom-auto sm:top-[50%] sm:max-w-lg sm:translate-y-[-50%] sm:rounded-[24px]">
              <DialogHeader>
                <DialogTitle>添加镜像源</DialogTitle>
                <DialogDescription>添加新的 Git 镜像源配置</DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label htmlFor="add-id">镜像源 ID *</Label>
                  <Input
                    id="add-id"
                    placeholder="例如: my-mirror"
                    value={formData.id}
                    onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="add-name">名称 *</Label>
                  <Input
                    id="add-name"
                    placeholder="例如: 我的镜像源"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="add-raw">Raw 文件前缀 *</Label>
                  <Input
                    id="add-raw"
                    placeholder="https://example.com/raw"
                    value={formData.raw_prefix}
                    onChange={(e) => setFormData({ ...formData, raw_prefix: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="add-clone">克隆前缀 *</Label>
                  <Input
                    id="add-clone"
                    placeholder="https://example.com/clone"
                    value={formData.clone_prefix}
                    onChange={(e) => setFormData({ ...formData, clone_prefix: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="add-priority">优先级</Label>
                  <Input
                    id="add-priority"
                    type="number"
                    min="1"
                    value={formData.priority}
                    onChange={(e) =>
                      setFormData({ ...formData, priority: parseInt(e.target.value) || 1 })
                    }
                  />
                  <p className="text-xs text-muted-foreground">数字越小优先级越高</p>
                </div>
                <div className="flex items-center space-x-2">
                  <Switch
                    id="add-enabled"
                    checked={formData.enabled}
                    onCheckedChange={(checked) => setFormData({ ...formData, enabled: checked })}
                  />
                  <Label htmlFor="add-enabled">启用此镜像源</Label>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setIsAddDialogOpen(false)}>
                  取消
                </Button>
                <Button onClick={handleAddMirror}>添加</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          {/* 编辑镜像源对话框 */}
          <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}>
            <DialogContent className="bottom-0 top-auto max-h-[86vh] translate-y-0 overflow-y-auto rounded-b-none rounded-t-[28px] sm:bottom-auto sm:top-[50%] sm:max-w-lg sm:translate-y-[-50%] sm:rounded-[24px]">
              <DialogHeader>
                <DialogTitle>编辑镜像源</DialogTitle>
                <DialogDescription>修改镜像源配置</DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label>镜像源 ID</Label>
                  <Input value={formData.id} disabled />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="edit-name">名称 *</Label>
                  <Input
                    id="edit-name"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="edit-raw">Raw 文件前缀 *</Label>
                  <Input
                    id="edit-raw"
                    value={formData.raw_prefix}
                    onChange={(e) => setFormData({ ...formData, raw_prefix: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="edit-clone">克隆前缀 *</Label>
                  <Input
                    id="edit-clone"
                    value={formData.clone_prefix}
                    onChange={(e) => setFormData({ ...formData, clone_prefix: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="edit-priority">优先级</Label>
                  <Input
                    id="edit-priority"
                    type="number"
                    min="1"
                    value={formData.priority}
                    onChange={(e) =>
                      setFormData({ ...formData, priority: parseInt(e.target.value) || 1 })
                    }
                  />
                  <p className="text-xs text-muted-foreground">数字越小优先级越高</p>
                </div>
                <div className="flex items-center space-x-2">
                  <Switch
                    id="edit-enabled"
                    checked={formData.enabled}
                    onCheckedChange={(checked) => setFormData({ ...formData, enabled: checked })}
                  />
                  <Label htmlFor="edit-enabled">启用此镜像源</Label>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setIsEditDialogOpen(false)}>
                  取消
                </Button>
                <Button onClick={handleUpdateMirror}>保存</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>
    </ScrollArea>
  )
}
