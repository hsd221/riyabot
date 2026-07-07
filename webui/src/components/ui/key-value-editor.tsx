'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Plus, Trash2, AlertCircle, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

type ValueType = 'string' | 'number' | 'boolean'

interface KeyValuePair {
  id: string
  key: string
  value: string | number | boolean
  type: ValueType
}

interface KeyValueEditorProps {
  value: Record<string, unknown>
  onChange: (value: Record<string, unknown>) => void
  className?: string
  placeholder?: string
}

// 推断值的类型
function inferType(value: unknown): ValueType {
  if (typeof value === 'boolean') return 'boolean'
  if (typeof value === 'number') return 'number'
  return 'string'
}

// 将值转换为指定类型
function convertValue(value: string, type: ValueType): string | number | boolean {
  switch (type) {
    case 'boolean':
      return value === 'true'
    case 'number': {
      const num = parseFloat(value)
      return isNaN(num) ? 0 : num
    }
    default:
      return value
  }
}

// 将 Record 转换为 KeyValuePair 数组
function recordToPairs(record: Record<string, unknown>): KeyValuePair[] {
  return Object.entries(record).map(([key, value]) => ({
    id: crypto.randomUUID(),
    key,
    value: value as string | number | boolean,
    type: inferType(value),
  }))
}

// 将 KeyValuePair 数组转换为 Record
function pairsToRecord(pairs: KeyValuePair[]): Record<string, unknown> {
  const record: Record<string, unknown> = {}
  for (const pair of pairs) {
    if (pair.key.trim()) {
      record[pair.key.trim()] = pair.value
    }
  }
  return record
}

// 验证 JSON 字符串
function validateJson(jsonStr: string): {
  valid: boolean
  error?: string
  parsed?: Record<string, unknown>
} {
  if (!jsonStr.trim()) {
    return { valid: true, parsed: {} }
  }
  try {
    const parsed = JSON.parse(jsonStr)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return { valid: false, error: '必须是一个 JSON 对象 {}' }
    }
    // 检查值类型是否支持
    for (const [key, value] of Object.entries(parsed)) {
      if (value !== null && !['string', 'number', 'boolean'].includes(typeof value)) {
        return { valid: false, error: `键 "${key}" 的值类型不支持（仅支持 string/number/boolean）` }
      }
    }
    return { valid: true, parsed: parsed as Record<string, unknown> }
  } catch {
    return { valid: false, error: 'JSON 格式错误' }
  }
}

// 获取类型的显示标签
function getTypeLabel(type: ValueType): string {
  switch (type) {
    case 'boolean':
      return '布尔'
    case 'number':
      return '数字'
    default:
      return '字符串'
  }
}

// 获取类型的颜色
function getTypeColor(type: ValueType): string {
  switch (type) {
    case 'boolean':
      return 'border-0 bg-[rgb(175_82_222_/_0.12)] text-[rgb(137_68_171)] dark:text-[rgb(218_143_255)]'
    case 'number':
      return 'border-0 bg-[rgb(0_122_255_/_0.11)] text-[rgb(0_102_204)] dark:text-[rgb(100_210_255)]'
    default:
      return 'border-0 bg-[rgb(52_199_89_/_0.11)] text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]'
  }
}

function getPreviewValueColor(type: ValueType, value: unknown): string {
  if (type === 'boolean') {
    return value
      ? 'text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]'
      : 'text-[rgb(174_37_31)] dark:text-[rgb(255_105_97)]'
  }
  if (type === 'number') {
    return 'text-[rgb(0_102_204)] dark:text-[rgb(100_210_255)]'
  }
  return 'text-[rgb(178_93_0)] dark:text-[rgb(255_159_10)]'
}

const destructiveIconButtonClass =
  'h-11 w-11 text-muted-foreground hover:bg-[rgb(255_59_48_/_0.08)] hover:text-[rgb(215_0_21)] dark:hover:bg-[rgb(255_69_58_/_0.12)] dark:hover:text-[rgb(255_105_97)] md:justify-self-end'

export function KeyValueEditor({
  value,
  onChange,
  className,
  placeholder = '添加额外参数...',
}: KeyValueEditorProps) {
  const [mode, setMode] = useState<'list' | 'json'>('list')
  const [pairs, setPairs] = useState<KeyValuePair[]>(() => recordToPairs(value || {}))
  const [jsonText, setJsonText] = useState(() =>
    Object.keys(value || {}).length > 0 ? JSON.stringify(value, null, 2) : ''
  )
  const [jsonError, setJsonError] = useState<string | null>(null)

  // 当外部 value 变化时同步内部状态
  useEffect(() => {
    const newPairs = recordToPairs(value || {})
    setPairs(newPairs)
    setJsonText(Object.keys(value || {}).length > 0 ? JSON.stringify(value, null, 2) : '')
  }, [value])

  // JSON 预览数据
  const previewData = useMemo(() => {
    const validation = validateJson(jsonText)
    if (validation.valid && validation.parsed) {
      return { success: true, data: validation.parsed }
    }
    return { success: false, data: {} }
  }, [jsonText])

  // 切换模式时同步数据
  const handleModeChange = useCallback(
    (newMode: string) => {
      const targetMode = newMode as 'list' | 'json'
      if (targetMode === 'json' && mode === 'list') {
        // 从列表模式切换到 JSON 模式
        const record = pairsToRecord(pairs)
        setJsonText(Object.keys(record).length > 0 ? JSON.stringify(record, null, 2) : '')
        setJsonError(null)
      } else if (targetMode === 'list' && mode === 'json') {
        // 从 JSON 模式切换到列表模式
        const validation = validateJson(jsonText)
        if (validation.valid && validation.parsed) {
          setPairs(recordToPairs(validation.parsed))
          setJsonError(null)
        }
      }
      setMode(targetMode)
    },
    [mode, pairs, jsonText]
  )

  // 添加新的键值对
  const addPair = useCallback(() => {
    const newPair: KeyValuePair = {
      id: crypto.randomUUID(),
      key: '',
      value: '',
      type: 'string',
    }
    const newPairs = [...pairs, newPair]
    setPairs(newPairs)
  }, [pairs])

  // 删除键值对
  const removePair = useCallback(
    (id: string) => {
      const newPairs = pairs.filter((p) => p.id !== id)
      setPairs(newPairs)
      onChange(pairsToRecord(newPairs))
    },
    [pairs, onChange]
  )

  // 更新键值对
  const updatePair = useCallback(
    (id: string, field: 'key' | 'value' | 'type', newValue: string | ValueType) => {
      const newPairs = pairs.map((pair) => {
        if (pair.id !== id) return pair

        if (field === 'type') {
          // 类型变化时转换值
          const newType = newValue as ValueType
          let convertedValue: string | number | boolean
          if (newType === 'boolean') {
            convertedValue = pair.value === 'true' || pair.value === true
          } else if (newType === 'number') {
            convertedValue =
              typeof pair.value === 'number' ? pair.value : parseFloat(String(pair.value)) || 0
          } else {
            convertedValue = String(pair.value)
          }
          return { ...pair, type: newType, value: convertedValue }
        } else if (field === 'value') {
          // 值变化时按类型转换
          return { ...pair, value: convertValue(newValue as string, pair.type) }
        } else {
          return { ...pair, [field]: newValue }
        }
      })
      setPairs(newPairs)
      onChange(pairsToRecord(newPairs))
    },
    [pairs, onChange]
  )

  // JSON 文本变化
  const handleJsonChange = useCallback(
    (text: string) => {
      setJsonText(text)
      const validation = validateJson(text)
      if (validation.valid && validation.parsed) {
        setJsonError(null)
        onChange(validation.parsed)
      } else {
        setJsonError(validation.error || 'JSON 格式错误')
      }
    },
    [onChange]
  )

  return (
    <div className={cn('space-y-4', className)}>
      {/* 标题 */}
      <Label className="text-sm font-medium">额外参数</Label>

      <Tabs value={mode} onValueChange={handleModeChange} className="w-full">
        <TabsList className="h-10 rounded-[14px] bg-muted/60 p-1">
          <TabsTrigger value="list" className="h-8 px-4 text-xs">
            键值对
          </TabsTrigger>
          <TabsTrigger value="json" className="h-8 px-4 text-xs">
            JSON
          </TabsTrigger>
        </TabsList>

        {/* 键值对列表模式 */}
        <TabsContent value="list" className="mt-3 space-y-2">
          {pairs.length === 0 ? (
            <div className="ios-empty-state min-h-[128px] rounded-[16px] border border-dashed border-border/55 bg-muted/25 px-5 py-6 text-sm leading-relaxed text-muted-foreground">
              {placeholder}
            </div>
          ) : (
            <div className="ios-group overflow-hidden">
              {/* 表头 */}
              <div className="hidden grid-cols-[1fr_1fr_104px_44px] gap-3 border-b border-border/70 bg-muted/45 px-5 py-3 text-xs font-semibold text-muted-foreground md:grid">
                <span>键名</span>
                <span>值</span>
                <span>类型</span>
                <span></span>
              </div>
              {/* 键值对列表 */}
              {pairs.map((pair) => (
                <div
                  key={pair.id}
                  className="grid gap-3 border-b border-border/70 p-4 last:border-b-0 md:grid-cols-[1fr_1fr_104px_44px] md:items-center md:px-5"
                >
                  <Input
                    value={pair.key}
                    onChange={(e) => updatePair(pair.id, 'key', e.target.value)}
                    placeholder="key"
                    className="h-11 text-sm"
                  />
                  {pair.type === 'boolean' ? (
                    <div className="flex h-11 items-center rounded-[13px] bg-muted/80 px-4 shadow-[0_1px_0_rgba(255,255,255,0.56)_inset]">
                      <Switch
                        checked={pair.value === true}
                        onCheckedChange={(checked) => updatePair(pair.id, 'value', String(checked))}
                      />
                      <span className="ml-2 text-sm text-muted-foreground">
                        {pair.value ? 'true' : 'false'}
                      </span>
                    </div>
                  ) : (
                    <Input
                      type={pair.type === 'number' ? 'number' : 'text'}
                      value={pair.value as string | number}
                      onChange={(e) => updatePair(pair.id, 'value', e.target.value)}
                      placeholder="value"
                      className="h-11 text-sm"
                      step={pair.type === 'number' ? 'any' : undefined}
                    />
                  )}
                  <Select
                    value={pair.type}
                    onValueChange={(v) => updatePair(pair.id, 'type', v as ValueType)}
                  >
                    <SelectTrigger className="h-11 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="string">字符串</SelectItem>
                      <SelectItem value="number">数字</SelectItem>
                      <SelectItem value="boolean">布尔</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className={destructiveIconButtonClass}
                    onClick={() => removePair(pair.id)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}
          <Button type="button" variant="outline" className="h-11 w-full" onClick={addPair}>
            <Plus className="mr-1 h-4 w-4" />
            添加参数
          </Button>
        </TabsContent>

        {/* JSON 编辑模式 - 左右分栏 */}
        <TabsContent value="json" className="mt-3">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {/* 左侧：JSON 编辑器 */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-muted-foreground">编辑</span>
                {jsonError ? (
                  <div className="text-destructive flex items-center gap-1 text-xs">
                    <AlertCircle className="h-3 w-3" />
                    <span className="max-w-[150px] truncate">{jsonError}</span>
                  </div>
                ) : (
                  jsonText.trim() && (
                    <div className="flex items-center gap-1 text-xs text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]">
                      <Check className="h-3 w-3" />
                      <span>有效</span>
                    </div>
                  )
                )}
              </div>
              <Textarea
                value={jsonText}
                onChange={(e) => handleJsonChange(e.target.value)}
                placeholder={'{\n  "key": "value"\n}'}
                className={cn(
                  'min-h-[160px] flex-1 resize-y font-mono text-sm md:h-[160px]',
                  jsonError && 'border-destructive focus-visible:ring-destructive'
                )}
              />
              <p className="text-xs text-muted-foreground">支持 string、number、boolean 类型</p>
            </div>

            {/* 右侧：预览 */}
            <div className="flex flex-col gap-2">
              <span className="text-xs font-semibold text-muted-foreground">预览</span>
              <div className="min-h-[160px] flex-1 overflow-auto rounded-[16px] border border-black/[0.035] bg-white/[0.72] p-4 shadow-[0_1px_0_rgba(255,255,255,0.7)_inset] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.08] md:h-[160px]">
                {previewData.success && Object.keys(previewData.data).length > 0 ? (
                  <div className="space-y-2">
                    {Object.entries(previewData.data).map(([key, val]) => {
                      const type = inferType(val)
                      return (
                        <div key={key} className="flex items-center gap-2 text-sm">
                          <code className="rounded-[7px] border border-black/[0.035] bg-white/[0.58] px-1.5 py-0.5 text-xs font-medium shadow-[0_1px_0_rgba(255,255,255,0.54)_inset] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.08]">
                            {key}
                          </code>
                          <span className="text-muted-foreground">=</span>
                          <span className={cn('font-mono', getPreviewValueColor(type, val))}>
                            {type === 'string' ? `"${val}"` : String(val)}
                          </span>
                          <Badge
                            variant="secondary"
                            className={cn('h-5 px-1.5 text-[10px]', getTypeColor(type))}
                          >
                            {getTypeLabel(type)}
                          </Badge>
                        </div>
                      )
                    })}
                  </div>
                ) : previewData.success ? (
                  <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                    暂无参数
                  </div>
                ) : (
                  <div className="text-destructive flex h-full items-center justify-center text-sm">
                    JSON 格式错误
                  </div>
                )}
              </div>
              <p className="text-xs text-muted-foreground">实时预览解析结果</p>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
