import React from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { Plus, Trash2 } from 'lucide-react'
import type { EmojiConfig, MemoryConfig, ToolConfig } from '../types'

interface FeaturesSectionProps {
  emojiConfig: EmojiConfig
  memoryConfig: MemoryConfig
  toolConfig: ToolConfig
  onEmojiChange: (config: EmojiConfig) => void
  onMemoryChange: (config: MemoryConfig) => void
  onToolChange: (config: ToolConfig) => void
}

export const FeaturesSection = React.memo(function FeaturesSection({
  emojiConfig,
  memoryConfig,
  toolConfig,
  onEmojiChange,
  onMemoryChange,
  onToolChange,
}: FeaturesSectionProps) {
  const globalMemoryBlacklist = memoryConfig.global_memory_blacklist ?? []

  const addGlobalMemoryBlacklistItem = () => {
    onMemoryChange({
      ...memoryConfig,
      global_memory_blacklist: [...globalMemoryBlacklist, ''],
    })
  }

  const updateGlobalMemoryBlacklistItem = (index: number, value: string) => {
    const newBlacklist = [...globalMemoryBlacklist]
    newBlacklist[index] = value
    onMemoryChange({
      ...memoryConfig,
      global_memory_blacklist: newBlacklist,
    })
  }

  const removeGlobalMemoryBlacklistItem = (index: number) => {
    onMemoryChange({
      ...memoryConfig,
      global_memory_blacklist: globalMemoryBlacklist.filter((_, i) => i !== index),
    })
  }

  return (
    <div className="space-y-6">
      {/* 工具设置 */}
      <div className="ios-group space-y-4 p-4 sm:p-6">
        <div>
          <h3 className="mb-4 text-lg font-semibold">工具设置</h3>
          <div className="flex items-center space-x-2">
            <Switch
              id="enable_tool"
              checked={toolConfig.enable_tool}
              onCheckedChange={(checked) => onToolChange({ ...toolConfig, enable_tool: checked })}
            />
            <Label htmlFor="enable_tool" className="cursor-pointer">
              启用工具系统
            </Label>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">允许当前实例使用各种工具来增强功能</p>
        </div>
      </div>

      {/* 记忆设置 */}
      <div className="ios-group space-y-4 p-4 sm:p-6">
        <div>
          <h3 className="mb-4 text-lg font-semibold">记忆设置</h3>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="max_agent_iterations">记忆思考深度</Label>
              <Input
                id="max_agent_iterations"
                type="number"
                min="1"
                value={memoryConfig.max_agent_iterations}
                onChange={(e) =>
                  onMemoryChange({
                    ...memoryConfig,
                    max_agent_iterations: parseInt(e.target.value),
                  })
                }
              />
              <p className="text-xs text-muted-foreground">最低为 1（不深入思考）</p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="agent_timeout_seconds">最长回忆时间（秒）</Label>
              <Input
                id="agent_timeout_seconds"
                type="number"
                min="1"
                step="0.1"
                value={memoryConfig.agent_timeout_seconds ?? 120}
                onChange={(e) =>
                  onMemoryChange({
                    ...memoryConfig,
                    agent_timeout_seconds: parseFloat(e.target.value),
                  })
                }
              />
              <p className="text-xs text-muted-foreground">记忆检索的超时时间，避免过长的等待</p>
            </div>

            <div className="flex items-center space-x-2">
              <Switch
                id="global_memory"
                checked={memoryConfig.global_memory ?? false}
                onCheckedChange={(checked) =>
                  onMemoryChange({ ...memoryConfig, global_memory: checked })
                }
              />
              <Label htmlFor="global_memory" className="cursor-pointer">
                全局记忆查询
              </Label>
            </div>
            <p className="-mt-2 text-xs text-muted-foreground">
              允许记忆检索在所有聊天记录中进行全局查询（忽略当前聊天流）
            </p>

            <div className="flex items-center space-x-2">
              <Switch
                id="planner_question"
                checked={memoryConfig.planner_question ?? true}
                onCheckedChange={(checked) =>
                  onMemoryChange({ ...memoryConfig, planner_question: checked })
                }
              />
              <Label htmlFor="planner_question" className="cursor-pointer">
                使用 Planner 提供的记忆检索问题
              </Label>
            </div>
            <p className="-mt-2 text-xs text-muted-foreground">
              开启后，Planner 在 reply 动作中提供 question 时会直接用于记忆检索
            </p>

            <div className="grid gap-2">
              <div className="flex items-center justify-between">
                <Label>全局记忆黑名单</Label>
                <Button onClick={addGlobalMemoryBlacklistItem} size="sm" variant="outline">
                  <Plus className="mr-1 h-4 w-4" />
                  添加
                </Button>
              </div>
              <div className="space-y-2">
                {globalMemoryBlacklist.map((item, index) => (
                  <div key={index} className="flex gap-2">
                    <Input
                      value={item}
                      onChange={(e) => updateGlobalMemoryBlacklistItem(index, e.target.value)}
                      placeholder="qq:123456:group"
                      className="font-mono text-sm"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      onClick={() => removeGlobalMemoryBlacklistItem(index)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                启用全局记忆后，黑名单中的聊天流不会被纳入全局检索
              </p>
            </div>

            <div className="grid gap-4 rounded-[16px] border border-border/45 bg-muted/35 p-4">
              <div>
                <h4 className="text-sm font-semibold">记忆存储</h4>
                <p className="mt-1 text-xs text-muted-foreground">
                  覆盖 MemoryStore 的 SQLite 与 Qdrant 存储参数
                </p>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="sqlite_path">SQLite 数据库路径</Label>
                <Input
                  id="sqlite_path"
                  value={memoryConfig.sqlite_path}
                  onChange={(e) => onMemoryChange({ ...memoryConfig, sqlite_path: e.target.value })}
                  className="font-mono text-sm"
                />
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <Label htmlFor="qdrant_url">Qdrant 服务器 URL</Label>
                  <Input
                    id="qdrant_url"
                    value={memoryConfig.qdrant_url}
                    onChange={(e) =>
                      onMemoryChange({ ...memoryConfig, qdrant_url: e.target.value })
                    }
                    placeholder="留空时使用本地模式"
                    className="font-mono text-sm"
                  />
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="qdrant_api_key">Qdrant API Key</Label>
                  <Input
                    id="qdrant_api_key"
                    value={memoryConfig.qdrant_api_key ?? ''}
                    onChange={(e) =>
                      onMemoryChange({ ...memoryConfig, qdrant_api_key: e.target.value })
                    }
                    className="font-mono text-sm"
                  />
                </div>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="qdrant_local_path">Qdrant 本地数据目录</Label>
                <Input
                  id="qdrant_local_path"
                  value={memoryConfig.qdrant_local_path}
                  onChange={(e) =>
                    onMemoryChange({ ...memoryConfig, qdrant_local_path: e.target.value })
                  }
                  className="font-mono text-sm"
                />
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <Label htmlFor="embedding_dimension">嵌入维度</Label>
                  <Input
                    id="embedding_dimension"
                    type="number"
                    min="1"
                    value={memoryConfig.embedding_dimension}
                    onChange={(e) =>
                      onMemoryChange({
                        ...memoryConfig,
                        embedding_dimension: parseInt(e.target.value),
                      })
                    }
                  />
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="vector_batch_size">向量批量写入大小</Label>
                  <Input
                    id="vector_batch_size"
                    type="number"
                    min="1"
                    value={memoryConfig.vector_batch_size}
                    onChange={(e) =>
                      onMemoryChange({
                        ...memoryConfig,
                        vector_batch_size: parseInt(e.target.value),
                      })
                    }
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <Label htmlFor="collection_name_atoms">记忆原子集合名</Label>
                  <Input
                    id="collection_name_atoms"
                    value={memoryConfig.collection_name_atoms}
                    onChange={(e) =>
                      onMemoryChange({ ...memoryConfig, collection_name_atoms: e.target.value })
                    }
                    className="font-mono text-sm"
                  />
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="collection_name_graph">图条目集合名</Label>
                  <Input
                    id="collection_name_graph"
                    value={memoryConfig.collection_name_graph}
                    onChange={(e) =>
                      onMemoryChange({ ...memoryConfig, collection_name_graph: e.target.value })
                    }
                    className="font-mono text-sm"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 表情包设置 */}
      <div className="ios-group space-y-4 p-4 sm:p-6">
        <div>
          <h3 className="mb-4 text-lg font-semibold">表情包设置</h3>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="emoji_chance">表情包激活概率</Label>
              <Input
                id="emoji_chance"
                type="number"
                step="0.1"
                min="0"
                max="1"
                value={emojiConfig.emoji_chance}
                onChange={(e) =>
                  onEmojiChange({ ...emojiConfig, emoji_chance: parseFloat(e.target.value) })
                }
              />
              <p className="text-xs text-muted-foreground">范围 0-1，越大越容易发送表情包</p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="max_reg_num">最大注册数量</Label>
              <Input
                id="max_reg_num"
                type="number"
                min="1"
                value={emojiConfig.max_reg_num}
                onChange={(e) =>
                  onEmojiChange({ ...emojiConfig, max_reg_num: parseInt(e.target.value) })
                }
              />
              <p className="text-xs text-muted-foreground">当前实例最多可以注册的表情包数量</p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="check_interval">检查间隔（分钟）</Label>
              <Input
                id="check_interval"
                type="number"
                min="1"
                value={emojiConfig.check_interval}
                onChange={(e) =>
                  onEmojiChange({ ...emojiConfig, check_interval: parseInt(e.target.value) })
                }
              />
              <p className="text-xs text-muted-foreground">
                检查表情包（注册、破损、删除）的时间间隔
              </p>
            </div>

            <div className="flex items-center space-x-2">
              <Switch
                id="do_replace"
                checked={emojiConfig.do_replace}
                onCheckedChange={(checked) =>
                  onEmojiChange({ ...emojiConfig, do_replace: checked })
                }
              />
              <Label htmlFor="do_replace" className="cursor-pointer">
                达到最大数量时替换表情包
              </Label>
            </div>

            <div className="flex items-center space-x-2">
              <Switch
                id="steal_emoji"
                checked={emojiConfig.steal_emoji}
                onCheckedChange={(checked) =>
                  onEmojiChange({ ...emojiConfig, steal_emoji: checked })
                }
              />
              <Label htmlFor="steal_emoji" className="cursor-pointer">
                偷取表情包
              </Label>
            </div>
            <p className="-mt-2 text-xs text-muted-foreground">
              允许当前实例将看到的表情包据为己有
            </p>

            <div className="grid gap-2">
              <Label htmlFor="selection_candidate_count">最终候选数量</Label>
              <Input
                id="selection_candidate_count"
                type="number"
                min="1"
                max="30"
                value={emojiConfig.selection_candidate_count}
                onChange={(event) => {
                  const value = Number.parseInt(event.target.value, 10)
                  if (Number.isFinite(value)) {
                    onEmojiChange({
                      ...emojiConfig,
                      selection_candidate_count: Math.max(1, Math.min(30, value)),
                    })
                  }
                }}
              />
            </div>

            <div className="flex items-center space-x-2 border-t pt-4">
              <Switch
                id="usage_scene_enabled"
                checked={emojiConfig.usage_scene_enabled}
                onCheckedChange={(checked) =>
                  onEmojiChange({ ...emojiConfig, usage_scene_enabled: checked })
                }
              />
              <Label htmlFor="usage_scene_enabled" className="cursor-pointer">
                学习真人使用场景
              </Label>
            </div>

            {emojiConfig.usage_scene_enabled && (
              <div className="grid gap-4 border-l-2 border-primary/20 pl-4">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div className="grid gap-2">
                    <Label htmlFor="usage_scene_context_messages">学习上下文消息数</Label>
                    <Input
                      id="usage_scene_context_messages"
                      type="number"
                      min="1"
                      max="32"
                      value={emojiConfig.usage_scene_context_messages}
                      onChange={(event) => {
                        const value = Number.parseInt(event.target.value, 10)
                        if (Number.isFinite(value)) {
                          onEmojiChange({
                            ...emojiConfig,
                            usage_scene_context_messages: Math.max(1, Math.min(32, value)),
                          })
                        }
                      }}
                    />
                  </div>

                  <div className="grid gap-2">
                    <Label htmlFor="usage_scene_max_scenes">单表情场景软上限</Label>
                    <Input
                      id="usage_scene_max_scenes"
                      type="number"
                      min="1"
                      max="32"
                      value={emojiConfig.usage_scene_max_scenes}
                      onChange={(event) => {
                        const value = Number.parseInt(event.target.value, 10)
                        if (Number.isFinite(value)) {
                          onEmojiChange({
                            ...emojiConfig,
                            usage_scene_max_scenes: Math.max(1, Math.min(32, value)),
                          })
                        }
                      }}
                    />
                  </div>
                </div>

                <div className="grid gap-2">
                  <div className="flex items-center justify-between gap-4">
                    <Label htmlFor="usage_scene_weight">初筛场景权重</Label>
                    <span className="text-sm tabular-nums text-muted-foreground">
                      {Math.round(emojiConfig.usage_scene_weight * 100)}%
                    </span>
                  </div>
                  <Slider
                    id="usage_scene_weight"
                    value={[emojiConfig.usage_scene_weight]}
                    min={0}
                    max={1}
                    step={0.05}
                    onValueChange={(values) =>
                      onEmojiChange({ ...emojiConfig, usage_scene_weight: values[0] })
                    }
                  />
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>仅情感</span>
                    <span>仅场景</span>
                  </div>
                </div>
              </div>
            )}

            <div className="flex items-center space-x-2">
              <Switch
                id="content_filtration"
                checked={emojiConfig.content_filtration}
                onCheckedChange={(checked) =>
                  onEmojiChange({ ...emojiConfig, content_filtration: checked })
                }
              />
              <Label htmlFor="content_filtration" className="cursor-pointer">
                启用表情包过滤
              </Label>
            </div>

            {emojiConfig.content_filtration && (
              <div className="grid gap-2 border-l-2 border-primary/20 pl-6">
                <Label htmlFor="filtration_prompt">过滤要求</Label>
                <Input
                  id="filtration_prompt"
                  value={emojiConfig.filtration_prompt}
                  onChange={(e) =>
                    onEmojiChange({ ...emojiConfig, filtration_prompt: e.target.value })
                  }
                  placeholder="符合公序良俗"
                />
                <p className="text-xs text-muted-foreground">只有符合此要求的表情包才会被保存</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
})
