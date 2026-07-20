import { AlertCircle, Clock3, Cpu, Hash, Route, Server } from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs'
import { ModelTraceJson } from './model-trace-json'
import { ModelTraceMediaPreview } from './model-trace-media'
import { formatTraceDuration, formatTraceOperation } from './model-trace-format'
import { ModelTraceStatusBadge } from './model-trace-status'
import type { ModelTraceDetail } from '../../types/model-trace'

function formatFullDateTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function MetadataItem({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Clock3
  label: string
  value: string
}) {
  return (
    <div className="min-w-0 rounded-[8px] border border-border/60 bg-muted/30 px-3 py-2.5">
      <dt className="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </dt>
      <dd className="mt-1 break-words text-[13px] font-medium leading-5 text-foreground">
        {value}
      </dd>
    </div>
  )
}

export function ModelTraceDetailPanel({ detail }: { detail: ModelTraceDetail }) {
  return (
    <section className="min-w-0 p-4 sm:p-5" aria-labelledby="model-trace-detail-title">
      <div className="flex flex-col gap-3 border-b border-border/60 pb-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2
              id="model-trace-detail-title"
              className="truncate text-[18px] font-semibold leading-7"
            >
              {detail.model_name}
            </h2>
            <ModelTraceStatusBadge status={detail.status} />
          </div>
          <p className="mt-1 break-all font-mono text-[12px] leading-5 text-muted-foreground">
            {detail.model_identifier}
          </p>
        </div>
        <div className="shrink-0 text-left sm:text-right">
          <p className="text-[13px] font-medium text-foreground">
            {formatTraceDuration(detail.duration_ms)}
          </p>
          <p className="text-[12px] leading-5 text-muted-foreground">
            {formatFullDateTime(detail.started_at)}
          </p>
        </div>
      </div>

      {detail.error_message && (
        <div className="border-destructive/20 bg-destructive/[0.08] text-destructive mt-4 flex items-start gap-3 rounded-[8px] border px-3.5 py-3 text-sm">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0">
            <p className="font-medium">{detail.error_type || '请求失败'}</p>
            <p className="mt-0.5 break-words text-[13px] leading-5">{detail.error_message}</p>
          </div>
        </div>
      )}

      <dl className="mt-4 grid grid-cols-2 gap-2 xl:grid-cols-3">
        <MetadataItem icon={Route} label="请求类型" value={detail.request_type || 'unknown'} />
        <MetadataItem icon={Cpu} label="操作" value={formatTraceOperation(detail.operation)} />
        <MetadataItem icon={Server} label="提供商" value={detail.provider_name} />
        <MetadataItem icon={Hash} label="尝试次数" value={`第 ${detail.attempt} 次`} />
        <MetadataItem
          icon={Clock3}
          label="输入 Token"
          value={detail.prompt_tokens.toLocaleString()}
        />
        <MetadataItem icon={Clock3} label="总 Token" value={detail.total_tokens.toLocaleString()} />
      </dl>

      <Tabs defaultValue="request" className="mt-5">
        <TabsList className="w-full justify-start overflow-x-auto sm:w-auto">
          <TabsTrigger value="request">请求内容</TabsTrigger>
          <TabsTrigger value="response">返回内容</TabsTrigger>
          <TabsTrigger value="metadata">元数据</TabsTrigger>
        </TabsList>
        <TabsContent value="request" forceMount className="data-[state=inactive]:hidden">
          <ModelTraceMediaPreview traceId={detail.id} media={detail.media} />
          <ModelTraceJson payload={detail.request_payload} label="请求内容" />
        </TabsContent>
        <TabsContent value="response" forceMount className="data-[state=inactive]:hidden">
          <ModelTraceJson payload={detail.response_payload ?? { content: null }} label="返回内容" />
        </TabsContent>
        <TabsContent value="metadata" forceMount className="data-[state=inactive]:hidden">
          <ModelTraceJson
            label="追踪元数据"
            payload={{
              id: detail.id,
              status: detail.status,
              request_type: detail.request_type,
              operation: detail.operation,
              model_name: detail.model_name,
              model_identifier: detail.model_identifier,
              provider_name: detail.provider_name,
              attempt: detail.attempt,
              started_at: detail.started_at,
              completed_at: detail.completed_at,
              duration_ms: detail.duration_ms,
              status_code: detail.status_code,
              prompt_tokens: detail.prompt_tokens,
              completion_tokens: detail.completion_tokens,
              total_tokens: detail.total_tokens,
            }}
          />
        </TabsContent>
      </Tabs>
    </section>
  )
}
