/**
 * 插件统计组件
 * 显示点赞、点踩、评分和下载量
 */

import { useState, useEffect } from 'react'
import { ThumbsUp, ThumbsDown, Star, Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/hooks/use-toast'
import {
  getPluginStats,
  likePlugin,
  dislikePlugin,
  ratePlugin,
  type PluginStatsData,
} from '@/lib/plugin-stats'

interface PluginStatsProps {
  pluginId: string
  compact?: boolean // 紧凑模式（只显示数字）
}

const starActiveClass = 'fill-[rgb(255_204_0)] text-[rgb(255_204_0)]'
const starInactiveClass = 'text-muted-foreground/35 hover:text-[rgb(255_204_0)]'

export function PluginStats({ pluginId, compact = false }: PluginStatsProps) {
  const [stats, setStats] = useState<PluginStatsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [userRating, setUserRating] = useState(0)
  const [userComment, setUserComment] = useState('')
  const [isRatingDialogOpen, setIsRatingDialogOpen] = useState(false)
  const { toast } = useToast()

  // 加载统计数据
  const loadStats = async () => {
    setLoading(true)
    const data = await getPluginStats(pluginId)
    if (data) {
      setStats(data)
    }
    setLoading(false)
  }

  useEffect(() => {
    loadStats()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pluginId])

  // 处理点赞
  const handleLike = async () => {
    const result = await likePlugin(pluginId)

    if (result.success) {
      toast({ title: '已点赞', description: '感谢你的支持！' })
      loadStats() // 重新加载统计数据
    } else {
      toast({
        title: '点赞失败',
        description: result.error || '未知错误',
        variant: 'destructive',
      })
    }
  }

  // 处理点踩
  const handleDislike = async () => {
    const result = await dislikePlugin(pluginId)

    if (result.success) {
      toast({ title: '已反馈', description: '感谢你的反馈！' })
      loadStats()
    } else {
      toast({
        title: '操作失败',
        description: result.error || '未知错误',
        variant: 'destructive',
      })
    }
  }

  // 提交评分
  const handleSubmitRating = async () => {
    if (userRating === 0) {
      toast({
        title: '请选择评分',
        description: '至少选择 1 颗星',
        variant: 'destructive',
      })
      return
    }

    const result = await ratePlugin(pluginId, userRating, userComment || undefined)

    if (result.success) {
      toast({ title: '评分成功', description: '感谢你的评价！' })
      setIsRatingDialogOpen(false)
      setUserRating(0)
      setUserComment('')
      loadStats()
    } else {
      toast({
        title: '评分失败',
        description: result.error || '未知错误',
        variant: 'destructive',
      })
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        <div className="flex items-center gap-1">
          <Download className="h-4 w-4" />
          <span>-</span>
        </div>
        <div className="flex items-center gap-1">
          <Star className="h-4 w-4" />
          <span>-</span>
        </div>
      </div>
    )
  }

  if (!stats) {
    return null
  }

  // 紧凑模式
  if (compact) {
    return (
      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        <div
          className="flex items-center gap-1"
          title={`下载量: ${stats.downloads.toLocaleString()}`}
        >
          <Download className="h-4 w-4" />
          <span>{stats.downloads.toLocaleString()}</span>
        </div>
        <div
          className="flex items-center gap-1"
          title={`评分: ${stats.rating.toFixed(1)} (${stats.rating_count} 条评价)`}
        >
          <Star className={`h-4 w-4 ${starActiveClass}`} />
          <span>{stats.rating.toFixed(1)}</span>
        </div>
        <div className="flex items-center gap-1" title={`点赞数: ${stats.likes}`}>
          <ThumbsUp className="h-4 w-4" />
          <span>{stats.likes}</span>
        </div>
      </div>
    )
  }

  // 完整模式
  return (
    <div className="space-y-4">
      {/* 统计数字 */}
      <div className="ios-group overflow-hidden">
        <div className="ios-row min-h-[58px]">
          <span className="flex min-w-0 items-center gap-3">
            <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
              <Download className="h-4 w-4" />
            </span>
            <span className="text-[15px] font-medium leading-5">下载量</span>
          </span>
          <span className="text-[16px] font-semibold tabular-nums leading-5">
            {stats.downloads.toLocaleString()}
          </span>
        </div>
        <div className="ios-row min-h-[58px]">
          <span className="flex min-w-0 items-center gap-3">
            <span className="ios-symbol ios-symbol-sm ios-symbol-yellow">
              <Star className="h-4 w-4 fill-white" />
            </span>
            <span className="min-w-0">
              <span className="block text-[15px] font-medium leading-5">评分</span>
              <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                {stats.rating_count} 条评价
              </span>
            </span>
          </span>
          <span className="text-[16px] font-semibold tabular-nums leading-5">
            {stats.rating.toFixed(1)}
          </span>
        </div>
        <div className="ios-row min-h-[58px]">
          <span className="flex min-w-0 items-center gap-3">
            <span className="ios-symbol ios-symbol-sm ios-symbol-green">
              <ThumbsUp className="h-4 w-4" />
            </span>
            <span className="text-[15px] font-medium leading-5">点赞</span>
          </span>
          <span className="text-[16px] font-semibold tabular-nums leading-5">{stats.likes}</span>
        </div>
        <div className="ios-row min-h-[58px]">
          <span className="flex min-w-0 items-center gap-3">
            <span className="ios-symbol ios-symbol-sm ios-symbol-red">
              <ThumbsDown className="h-4 w-4" />
            </span>
            <span className="text-[15px] font-medium leading-5">点踩</span>
          </span>
          <span className="text-[16px] font-semibold tabular-nums leading-5">{stats.dislikes}</span>
        </div>
      </div>

      {/* 操作按钮 */}
      <div className="ios-group overflow-hidden">
        <button type="button" className="ios-row ios-touch w-full text-left" onClick={handleLike}>
          <span className="flex min-w-0 items-center gap-3">
            <span className="ios-symbol ios-symbol-sm ios-symbol-green">
              <ThumbsUp className="h-4 w-4" />
            </span>
            <span className="text-[15px] font-medium leading-5">点赞</span>
          </span>
          <span className="text-[15px] leading-5 text-muted-foreground">发送</span>
        </button>
        <button
          type="button"
          className="ios-row ios-touch w-full text-left"
          onClick={handleDislike}
        >
          <span className="flex min-w-0 items-center gap-3">
            <span className="ios-symbol ios-symbol-sm ios-symbol-red">
              <ThumbsDown className="h-4 w-4" />
            </span>
            <span className="text-[15px] font-medium leading-5">反馈</span>
          </span>
          <span className="text-[15px] leading-5 text-muted-foreground">发送</span>
        </button>
        <Dialog open={isRatingDialogOpen} onOpenChange={setIsRatingDialogOpen}>
          <DialogTrigger asChild>
            <button type="button" className="ios-row ios-touch w-full text-left">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-yellow">
                  <Star className="h-4 w-4 fill-white" />
                </span>
                <span className="text-[15px] font-medium leading-5">评分</span>
              </span>
              <span className="text-[15px] leading-5 text-primary">评价</span>
            </button>
          </DialogTrigger>
          <DialogContent className="ios-sheet">
            <DialogHeader>
              <DialogTitle>为插件评分</DialogTitle>
              <DialogDescription>分享你的使用体验，帮助其他用户</DialogDescription>
            </DialogHeader>

            <div className="space-y-4 py-4">
              {/* 星级评分 */}
              <div className="flex flex-col items-center gap-2">
                <div className="flex gap-2">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <button
                      key={star}
                      onClick={() => setUserRating(star)}
                      className="focus:outline-none"
                    >
                      <Star
                        className={`h-8 w-8 transition-colors ${
                          star <= userRating ? starActiveClass : starInactiveClass
                        }`}
                      />
                    </button>
                  ))}
                </div>
                <span className="text-sm text-muted-foreground">
                  {userRating === 0 && '点击星星进行评分'}
                  {userRating === 1 && '很差'}
                  {userRating === 2 && '一般'}
                  {userRating === 3 && '还行'}
                  {userRating === 4 && '不错'}
                  {userRating === 5 && '非常好'}
                </span>
              </div>

              {/* 评论 */}
              <div>
                <label className="mb-2 block text-sm font-medium">评论（可选）</label>
                <Textarea
                  value={userComment}
                  onChange={(e) => setUserComment(e.target.value)}
                  placeholder="分享你的使用体验..."
                  rows={4}
                  maxLength={500}
                />
                <div className="mt-1 text-right text-xs text-muted-foreground">
                  {userComment.length} / 500
                </div>
              </div>
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => setIsRatingDialogOpen(false)}>
                取消
              </Button>
              <Button onClick={handleSubmitRating} disabled={userRating === 0}>
                提交评分
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* 最近评价 */}
      {stats.recent_ratings && stats.recent_ratings.length > 0 && (
        <div className="space-y-2">
          <h4 className="px-1 text-[13px] font-medium leading-5 text-muted-foreground">最近评价</h4>
          <div className="ios-group overflow-hidden">
            {stats.recent_ratings.map((rating, index) => (
              <div key={index} className="ios-row min-h-[74px] items-start">
                <div className="min-w-0 flex-1">
                  <div className="flex gap-1">
                    {[1, 2, 3, 4, 5].map((star) => (
                      <Star
                        key={star}
                        className={`h-3 w-3 ${
                          star <= rating.rating ? starActiveClass : 'text-muted-foreground/35'
                        }`}
                      />
                    ))}
                  </div>
                  {rating.comment && (
                    <p className="mt-1 line-clamp-2 text-[13px] leading-5 text-muted-foreground">
                      {rating.comment}
                    </p>
                  )}
                </div>
                <span className="shrink-0 text-[12px] leading-5 text-muted-foreground">
                  {new Date(rating.created_at).toLocaleDateString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
