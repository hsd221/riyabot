/**
 * 问卷渲染器组件
 * 读取 JSON 配置并展示问卷界面
 */

import { useState, useCallback, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Loader2, CheckCircle2, AlertCircle, ChevronLeft, ChevronRight } from 'lucide-react'
import { SurveyQuestion } from './survey-question'
import { submitSurvey, checkUserSubmission } from '@/lib/survey-api'
import type { SurveyConfig, QuestionAnswer } from '@/types/survey'

export interface SurveyRendererProps {
  /** 问卷配置 */
  config: SurveyConfig
  /** 初始答案（用于预填充，如自动填写版本号） */
  initialAnswers?: QuestionAnswer[]
  /** 提交成功回调 */
  onSubmitSuccess?: (submissionId: string) => void
  /** 提交失败回调 */
  onSubmitError?: (error: string) => void
  /** 是否显示进度条 */
  showProgress?: boolean
  /** 是否分页显示（每页一题） */
  paginateQuestions?: boolean
  /** 自定义类名 */
  className?: string
}

type AnswerMap = Record<string, string | string[] | number | undefined>
type SubmissionCheckResult = { success: boolean; hasSubmitted?: boolean; error?: string }

const SUBMISSION_CHECK_TIMEOUT_MS = 1800

export function SurveyRenderer({
  config,
  initialAnswers,
  onSubmitSuccess,
  onSubmitError,
  showProgress = true,
  paginateQuestions = false,
  className,
}: SurveyRendererProps) {
  // 将 initialAnswers 转换为 AnswerMap
  const getInitialAnswerMap = useCallback((): AnswerMap => {
    if (!initialAnswers || initialAnswers.length === 0) return {}
    return initialAnswers.reduce((acc, answer) => {
      acc[answer.questionId] = answer.value
      return acc
    }, {} as AnswerMap)
  }, [initialAnswers])

  const [answers, setAnswers] = useState<AnswerMap>(() => getInitialAnswerMap())
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [currentPage, setCurrentPage] = useState(0)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSubmitted, setIsSubmitted] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submissionId, setSubmissionId] = useState<string | null>(null)
  const [hasAlreadySubmitted, setHasAlreadySubmitted] = useState(false)
  const [isCheckingSubmission, setIsCheckingSubmission] = useState(true)

  // 当 initialAnswers 变化时更新答案（合并而非替换）
  useEffect(() => {
    if (initialAnswers && initialAnswers.length > 0) {
      setAnswers((prev) => ({
        ...prev,
        ...getInitialAnswerMap(),
      }))
    }
  }, [initialAnswers, getInitialAnswerMap])

  // 检查是否已提交过
  useEffect(() => {
    let isActive = true

    const checkSubmissionWithTimeout = (surveyId: string): Promise<SubmissionCheckResult> => {
      let timeoutId: number | undefined

      return new Promise((resolve) => {
        timeoutId = window.setTimeout(() => {
          resolve({ success: false, error: '检查超时' })
        }, SUBMISSION_CHECK_TIMEOUT_MS)

        checkUserSubmission(surveyId)
          .then(resolve)
          .catch(() => resolve({ success: false, error: '网络错误' }))
          .finally(() => {
            if (timeoutId !== undefined) {
              window.clearTimeout(timeoutId)
            }
          })
      })
    }

    const checkSubmission = async () => {
      try {
        if (!config.settings?.allowMultiple) {
          const result = await checkSubmissionWithTimeout(config.id)
          if (isActive && result.success && result.hasSubmitted) {
            setHasAlreadySubmitted(true)
          }
        }
      } finally {
        if (isActive) {
          setIsCheckingSubmission(false)
        }
      }
    }

    checkSubmission()

    return () => {
      isActive = false
    }
  }, [config.id, config.settings?.allowMultiple])

  // 检查问卷是否在有效期内
  const isWithinTimeRange = useCallback(() => {
    const now = new Date()
    if (config.settings?.startTime && new Date(config.settings.startTime) > now) {
      return false
    }
    if (config.settings?.endTime && new Date(config.settings.endTime) < now) {
      return false
    }
    return true
  }, [config.settings?.startTime, config.settings?.endTime])

  // 计算进度
  const answeredCount = config.questions.filter((q) => {
    const answer = answers[q.id]
    if (answer === undefined || answer === null) return false
    if (Array.isArray(answer)) return answer.length > 0
    if (typeof answer === 'string') return answer.trim() !== ''
    return true
  }).length

  const progress = (answeredCount / config.questions.length) * 100

  // 更新答案
  const handleAnswerChange = useCallback(
    (questionId: string, value: string | string[] | number) => {
      setAnswers((prev) => ({ ...prev, [questionId]: value }))
      // 清除该问题的错误
      setErrors((prev) => {
        const newErrors = { ...prev }
        delete newErrors[questionId]
        return newErrors
      })
    },
    []
  )

  // 验证答案
  const validateAnswers = useCallback(() => {
    const newErrors: Record<string, string> = {}

    for (const question of config.questions) {
      if (question.required) {
        const answer = answers[question.id]

        if (answer === undefined || answer === null) {
          newErrors[question.id] = '此题为必填项'
          continue
        }

        if (Array.isArray(answer) && answer.length === 0) {
          newErrors[question.id] = '请至少选择一项'
          continue
        }

        if (typeof answer === 'string' && answer.trim() === '') {
          newErrors[question.id] = '此题为必填项'
          continue
        }
      }

      // 文本长度验证
      if (question.minLength && typeof answers[question.id] === 'string') {
        const text = answers[question.id] as string
        if (text.length < question.minLength) {
          newErrors[question.id] = `至少需要 ${question.minLength} 个字符`
        }
      }
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }, [config.questions, answers])

  // 提交问卷
  const handleSubmit = useCallback(async () => {
    if (!validateAnswers()) {
      // 如果是分页模式，跳转到第一个有错误的问题
      if (paginateQuestions) {
        const firstErrorIndex = config.questions.findIndex((q) => errors[q.id])
        if (firstErrorIndex >= 0) {
          setCurrentPage(firstErrorIndex)
        }
      }
      return
    }

    setIsSubmitting(true)
    setSubmitError(null)

    try {
      // 构建答案列表
      const answerList: QuestionAnswer[] = config.questions
        .filter((q) => answers[q.id] !== undefined)
        .map((q) => ({
          questionId: q.id,
          value: answers[q.id]!,
        }))

      const result = await submitSurvey(config.id, config.version, answerList, {
        allowMultiple: config.settings?.allowMultiple,
      })

      if (result.success && result.submissionId) {
        setIsSubmitted(true)
        setSubmissionId(result.submissionId)
        onSubmitSuccess?.(result.submissionId)
      } else {
        const error = result.error || '提交失败'
        setSubmitError(error)
        onSubmitError?.(error)
      }
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '提交失败'
      setSubmitError(errorMsg)
      onSubmitError?.(errorMsg)
    } finally {
      setIsSubmitting(false)
    }
  }, [validateAnswers, paginateQuestions, config, answers, errors, onSubmitSuccess, onSubmitError])

  // 分页导航
  const goToPage = useCallback(
    (page: number) => {
      if (page >= 0 && page < config.questions.length) {
        setCurrentPage(page)
      }
    },
    [config.questions.length]
  )

  // 检查中
  if (isCheckingSubmission) {
    return (
      <div className={cn('ios-group flex min-h-28 items-center justify-center', className)}>
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  // 已提交过
  if (hasAlreadySubmitted && !config.settings?.allowMultiple) {
    return (
      <div className={cn('ios-group overflow-hidden', className)}>
        <div className="ios-row flex-col items-stretch gap-3">
          <h2 className="text-[17px] font-semibold leading-6">{config.title}</h2>
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>你已经提交过这份问卷了，感谢参与！</AlertDescription>
          </Alert>
        </div>
      </div>
    )
  }

  // 不在有效期内
  if (!isWithinTimeRange()) {
    return (
      <div className={cn('ios-group overflow-hidden', className)}>
        <div className="ios-row flex-col items-stretch gap-3">
          <h2 className="text-[17px] font-semibold leading-6">{config.title}</h2>
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>问卷不在有效期内</AlertDescription>
          </Alert>
        </div>
      </div>
    )
  }

  // 提交成功
  if (isSubmitted) {
    return (
      <div className={cn('ios-group overflow-hidden', className)}>
        <div className="ios-row flex-col items-center gap-4 py-8 text-center">
          <div className="grid h-12 w-12 place-items-center rounded-[16px] bg-[#34C759]/15 text-[#34C759]">
            <CheckCircle2 className="h-6 w-6" />
          </div>
          <h2 className="text-[20px] font-semibold leading-7 text-foreground">提交成功</h2>
          <p className="max-w-md text-[15px] leading-6 text-muted-foreground">
            {config.settings?.thankYouMessage || '感谢你的参与！'}
          </p>
          {submissionId && (
            <p className="text-xs leading-5 text-muted-foreground">提交编号：{submissionId}</p>
          )}
        </div>
      </div>
    )
  }

  // 问卷展示
  const questionsToShow = paginateQuestions ? [config.questions[currentPage]] : config.questions
  const questionContent = (
    <>
      {/* 问卷内容 */}
      <div className="ios-group overflow-hidden">
        {questionsToShow.map((question, index) => (
          <div
            key={question.id}
            className={cn(
              'ios-row flex-col items-stretch gap-3 py-4 sm:py-5',
              errors[question.id] && 'bg-destructive/5'
            )}
          >
            <SurveyQuestion
              question={question}
              value={answers[question.id]}
              onChange={(value) => handleAnswerChange(question.id, value)}
              error={errors[question.id]}
              disabled={isSubmitting}
              indexLabel={
                paginateQuestions
                  ? `${currentPage + 1}/${config.questions.length}`
                  : String(index + 1).padStart(2, '0')
              }
            />
          </div>
        ))}
      </div>

      <div className="space-y-4">
        {submitError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}

        {/* 提交按钮区域 */}
        <div className="flex flex-col gap-3 pb-[max(1rem,env(safe-area-inset-bottom))] pt-1 sm:flex-row sm:items-center sm:justify-between">
          {paginateQuestions ? (
            <>
              <Button
                variant="outline"
                onClick={() => goToPage(currentPage - 1)}
                disabled={currentPage === 0 || isSubmitting}
              >
                <ChevronLeft className="mr-1 h-4 w-4" />
                上一题
              </Button>

              {currentPage === config.questions.length - 1 ? (
                <Button onClick={handleSubmit} disabled={isSubmitting}>
                  {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  提交问卷
                </Button>
              ) : (
                <Button onClick={() => goToPage(currentPage + 1)} disabled={isSubmitting}>
                  下一题
                  <ChevronRight className="ml-1 h-4 w-4" />
                </Button>
              )}
            </>
          ) : (
            <>
              <div className="min-w-0 text-[13px] leading-5 text-muted-foreground">
                {Object.keys(errors).length > 0 && (
                  <span className="text-destructive">
                    还有 {Object.keys(errors).length} 个必填项未完成
                  </span>
                )}
              </div>
              <Button
                onClick={handleSubmit}
                disabled={isSubmitting}
                size="lg"
                className="h-12 w-full min-w-32 rounded-full px-6 shadow-[0_10px_24px_hsl(var(--primary)_/_0.18)] sm:w-auto"
              >
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                提交问卷
              </Button>
            </>
          )}
        </div>
      </div>
    </>
  )

  return (
    <div className={cn('flex min-h-0 flex-col gap-4', className)}>
      {/* 问卷头部 */}
      <div className="ios-group overflow-hidden">
        <div className="ios-row min-h-[72px] py-4">
          <div className="min-w-0">
            <h2 className="text-[17px] font-semibold leading-6">{config.title}</h2>
            {config.description && (
              <p className="mt-1 text-[14px] leading-5 text-muted-foreground">
                {config.description}
              </p>
            )}
          </div>
          <div className="shrink-0 rounded-full bg-secondary px-2.5 py-1 text-[12px] font-medium leading-4 text-muted-foreground">
            {answeredCount}/{config.questions.length}
          </div>
        </div>
        {showProgress && (
          <div className="px-4 py-3 sm:px-5">
            <Progress value={progress} className="h-1.5 bg-muted/70" />
          </div>
        )}
      </div>

      {paginateQuestions ? (
        <div className="space-y-4">{questionContent}</div>
      ) : (
        <ScrollArea className="min-h-0 flex-1 rounded-[19px]">
          <div className="space-y-4 pr-3">{questionContent}</div>
        </ScrollArea>
      )}
    </div>
  )
}
