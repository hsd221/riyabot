/**
 * WebUI 使用反馈问卷页面
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Loader2, AlertCircle } from 'lucide-react'
import { SurveyRenderer } from '@/components/survey'
import { webuiFeedbackSurvey } from '@/config/surveys'
import { APP_VERSION } from '@/lib/version'
import type { SurveyConfig, QuestionAnswer } from '@/types/survey'

export function WebUIFeedbackSurveyPage() {
  const [surveyConfig, setSurveyConfig] = useState<SurveyConfig | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // 初始化问卷配置，自动填充版本号
  useEffect(() => {
    // 深拷贝配置以避免修改原始对象
    const config = JSON.parse(JSON.stringify(webuiFeedbackSurvey)) as SurveyConfig
    setSurveyConfig(config)
    setIsLoading(false)
  }, [])

  // 预填充的答案（版本号自动填写）
  const initialAnswers: QuestionAnswer[] = useMemo(
    () => [
      {
        questionId: 'webui_version',
        value: `v${APP_VERSION}`,
      },
    ],
    []
  )

  // 提交成功回调
  const handleSubmitSuccess = useCallback(() => {}, [])

  // 提交错误回调
  const handleSubmitError = useCallback((error: string) => {
    console.error('WebUI Survey submission error:', error)
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
          <h1 className="ios-title">WebUI 反馈</h1>
          <p className="ios-subtitle">帮助我们改进控制台的可用性、稳定性和视觉体验。</p>
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

export default WebUIFeedbackSurveyPage
