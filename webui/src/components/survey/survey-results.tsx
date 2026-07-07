/**
 * 问卷结果查看组件
 * 展示问卷统计数据和用户提交记录
 */

import { useState, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { Progress } from '@/components/ui/progress'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Loader2, Users, FileText, Clock, Star, BarChart3, AlertCircle } from 'lucide-react'
import { getSurveyStats, getUserSubmissions } from '@/lib/survey-api'
import type { SurveyConfig, SurveyStats, StoredSubmission } from '@/types/survey'

interface SurveyResultsProps {
  /** 问卷配置 */
  config: SurveyConfig
  /** 是否显示用户提交记录 */
  showUserSubmissions?: boolean
  /** 自定义类名 */
  className?: string
}

export function SurveyResults({
  config,
  showUserSubmissions = true,
  className,
}: SurveyResultsProps) {
  const [stats, setStats] = useState<SurveyStats | null>(null)
  const [userSubmissions, setUserSubmissions] = useState<StoredSubmission[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      setIsLoading(true)
      setError(null)

      try {
        // 获取统计数据
        const statsResult = await getSurveyStats(config.id)
        if (statsResult.success && statsResult.stats) {
          setStats(statsResult.stats)
        }

        // 获取用户提交记录
        if (showUserSubmissions) {
          const submissionsResult = await getUserSubmissions(config.id)
          if (submissionsResult.success && submissionsResult.submissions) {
            setUserSubmissions(submissionsResult.submissions)
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载数据失败')
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
  }, [config.id, showUserSubmissions])

  if (isLoading) {
    return (
      <div className={cn('ios-group mx-auto w-full max-w-3xl', className)}>
        <div className="ios-empty-state min-h-[220px]">
          <span className="ios-empty-illustration">
            <Loader2 className="relative z-10 h-7 w-7 animate-spin text-primary" />
          </span>
          <p className="text-[15px] leading-5 text-muted-foreground">正在读取统计结果</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={cn('ios-group mx-auto w-full max-w-3xl', className)}>
        <div className="ios-empty-state min-h-[220px]">
          <span className="ios-symbol ios-symbol-red h-14 w-14 rounded-[18px]">
            <AlertCircle className="h-6 w-6" />
          </span>
          <div>
            <p className="text-[16px] font-semibold leading-6 text-foreground">统计加载失败</p>
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{error}</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={cn('mx-auto w-full max-w-3xl space-y-5', className)}>
      <header className="space-y-2">
        <h2 className="flex items-center gap-2 text-[24px] font-semibold leading-[1.16] tracking-normal">
          <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
            <BarChart3 className="h-4 w-4" />
          </span>
          {config.title} - 统计结果
        </h2>
        {config.description && (
          <p className="text-[15px] leading-6 text-muted-foreground">{config.description}</p>
        )}
      </header>

      {/* 概览统计 */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="ios-group overflow-hidden p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[13px] font-medium leading-5 text-muted-foreground">总提交数</p>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground/80">全部记录</p>
            </div>
            <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
              <FileText className="h-4 w-4" />
            </span>
          </div>
          <p className="mt-5 text-[28px] font-semibold tabular-nums leading-none">
            {stats?.totalSubmissions || 0}
          </p>
        </div>

        <div className="ios-group overflow-hidden p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[13px] font-medium leading-5 text-muted-foreground">独立用户</p>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground/80">去重统计</p>
            </div>
            <span className="ios-symbol ios-symbol-sm ios-symbol-green">
              <Users className="h-4 w-4" />
            </span>
          </div>
          <p className="mt-5 text-[28px] font-semibold tabular-nums leading-none">
            {stats?.uniqueUsers || 0}
          </p>
        </div>

        <div className="ios-group overflow-hidden p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[13px] font-medium leading-5 text-muted-foreground">最后提交</p>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground/80">最近记录</p>
            </div>
            <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
              <Clock className="h-4 w-4" />
            </span>
          </div>
          <p className="mt-5 truncate text-[18px] font-semibold leading-none">
            {stats?.lastSubmissionAt ? new Date(stats.lastSubmissionAt).toLocaleDateString() : '-'}
          </p>
        </div>
      </div>

      <Tabs defaultValue="stats" className="w-full">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="stats">问题统计</TabsTrigger>
          {showUserSubmissions && <TabsTrigger value="submissions">我的提交</TabsTrigger>}
        </TabsList>

        <TabsContent value="stats" className="mt-4">
          <ScrollArea className="max-h-[60vh]">
            <div className="space-y-4 pr-4">
              {config.questions.map((question, index) => {
                const qStats = stats?.questionStats[question.id]

                return (
                  <div key={question.id} className="ios-group overflow-hidden p-4">
                    <div className="mb-3">
                      <div className="text-[12px] leading-4 text-muted-foreground">
                        问题 {index + 1}
                      </div>
                      <div className="mt-1 text-[15px] font-semibold leading-6">
                        {question.title}
                      </div>
                    </div>

                    {qStats ? (
                      <div className="space-y-3">
                        <div className="text-sm text-muted-foreground">
                          回答人数：{qStats.answered}
                        </div>

                        {/* 选择题统计 */}
                        {qStats.optionCounts && question.options && (
                          <div className="space-y-3">
                            {question.options.map((option) => {
                              const count = qStats.optionCounts?.[option.value] || 0
                              const percentage =
                                qStats.answered > 0 ? (count / qStats.answered) * 100 : 0

                              return (
                                <div key={option.id} className="space-y-1.5">
                                  <div className="flex justify-between gap-3 text-sm">
                                    <span className="min-w-0 truncate">{option.label}</span>
                                    <span className="shrink-0 text-muted-foreground">
                                      {count} ({percentage.toFixed(1)}%)
                                    </span>
                                  </div>
                                  <Progress value={percentage} className="h-2" />
                                </div>
                              )
                            })}
                          </div>
                        )}

                        {/* 评分/量表统计 */}
                        {qStats.average !== undefined && (
                          <div className="flex items-center gap-2">
                            <Star className="h-4 w-4 fill-[rgb(255_204_0)] text-[rgb(255_204_0)]" />
                            <span className="text-sm">平均分：{qStats.average.toFixed(2)}</span>
                          </div>
                        )}

                        {/* 文本答案样本 */}
                        {qStats.sampleAnswers && qStats.sampleAnswers.length > 0 && (
                          <div className="space-y-2">
                            <div className="text-sm text-muted-foreground">部分回答：</div>
                            <div className="space-y-1">
                              {qStats.sampleAnswers.map((answer, i) => (
                                <div
                                  key={i}
                                  className="rounded-[12px] bg-muted/45 p-2 text-sm text-muted-foreground"
                                >
                                  "{answer}"
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-sm text-muted-foreground">暂无数据</div>
                    )}
                  </div>
                )
              })}
            </div>
          </ScrollArea>
        </TabsContent>

        {showUserSubmissions && (
          <TabsContent value="submissions" className="mt-4">
            <ScrollArea className="max-h-[60vh]">
              {userSubmissions.length === 0 ? (
                <div className="ios-group">
                  <div className="ios-empty-state min-h-[180px]">
                    <span className="ios-empty-illustration">
                      <FileText className="relative z-10 h-7 w-7 text-primary" />
                    </span>
                    <p className="text-[15px] leading-5 text-muted-foreground">
                      你还没有提交过这份问卷
                    </p>
                  </div>
                </div>
              ) : (
                <div className="space-y-4 pr-4">
                  {userSubmissions.map((submission) => (
                    <div key={submission.id} className="ios-group overflow-hidden p-4">
                      <div className="mb-3 flex items-center justify-between gap-3">
                        <Badge variant="outline">
                          {new Date(submission.submittedAt).toLocaleString()}
                        </Badge>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          ID: {submission.id}
                        </span>
                      </div>

                      <div className="space-y-2">
                        {submission.answers.map((answer) => {
                          const question = config.questions.find((q) => q.id === answer.questionId)

                          if (!question) return null

                          // 格式化答案显示
                          let displayValue: string
                          if (Array.isArray(answer.value)) {
                            const labels = answer.value.map((v) => {
                              const opt = question.options?.find((o) => o.value === v)
                              return opt?.label || v
                            })
                            displayValue = labels.join('、')
                          } else if (typeof answer.value === 'number') {
                            displayValue = answer.value.toString()
                          } else {
                            const opt = question.options?.find((o) => o.value === answer.value)
                            displayValue = opt?.label || answer.value
                          }

                          return (
                            <div key={answer.questionId} className="text-sm leading-5">
                              <span className="text-muted-foreground">{question.title}：</span>
                              <span>{displayValue}</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </ScrollArea>
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}
