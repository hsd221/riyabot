/**
 * 当前 Bot 使用体验反馈问卷页面
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Loader2, AlertCircle } from 'lucide-react'
import { SurveyRenderer } from '@/components/survey'
import { riyabotFeedbackSurvey } from '@/config/surveys'
import { getRiyaBotStatus } from '@/lib/system-api'
import type { SurveyConfig, QuestionAnswer } from '@/types/survey'

export function RiyaBotFeedbackSurveyPage() {
  const [surveyConfig, setSurveyConfig] = useState<SurveyConfig | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [riyabotVersion, setRiyabotVersion] = useState<string>('未知版本')

  // 初始化问卷配置，获取主程序版本
  useEffect(() => {
    const init = async () => {
      try {
        // 获取主程序版本
        const status = await getRiyaBotStatus()
        setRiyabotVersion(status.version || '未知版本')
      } catch (error) {
        console.error('Failed to get RiyaBot version:', error)
        setRiyabotVersion('获取失败')
      }

      // 深拷贝配置以避免修改原始对象
      const config = JSON.parse(JSON.stringify(riyabotFeedbackSurvey)) as SurveyConfig
      setSurveyConfig(config)
      setIsLoading(false)
    }

    init()
  }, [])

  // 预填充的答案（版本号自动填写）
  const initialAnswers: QuestionAnswer[] = useMemo(
    () => [
      {
        questionId: 'riyabot_version',
        value: riyabotVersion,
      },
    ],
    [riyabotVersion]
  )

  // 提交成功回调
  const handleSubmitSuccess = useCallback(() => {}, [])

  // 提交错误回调
  const handleSubmitError = useCallback((error: string) => {
    console.error('RiyaBot Survey submission error:', error)
  }, [])

  if (isLoading) {
    return (
      <div className="ios-page">
        <div className="ios-card flex min-h-32 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      </div>
    )
  }

  if (!surveyConfig) {
    return (
      <div className="ios-page flex min-h-full flex-col items-center justify-center gap-4">
        <Alert variant="destructive" className="max-w-md">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>无法加载问卷配置</AlertDescription>
        </Alert>
        <Button variant="outline" onClick={() => window.location.reload()}>
          重试
        </Button>
      </div>
    )
  }

  return (
    <div className="ios-page flex h-full min-h-0 flex-col">
      <div className="ios-content flex min-h-0 max-w-3xl flex-1 flex-col">
        <div>
          <h1 className="ios-title">RiyaBot 反馈</h1>
          <p className="ios-subtitle">分享真实使用感受，帮助我们调整体验和能力优先级。</p>
        </div>
        <SurveyRenderer
          config={surveyConfig}
          initialAnswers={initialAnswers}
          showProgress={true}
          paginateQuestions={false}
          onSubmitSuccess={handleSubmitSuccess}
          onSubmitError={handleSubmitError}
          className="min-h-0 flex-1"
        />
      </div>
    </div>
  )
}

export default RiyaBotFeedbackSurveyPage
