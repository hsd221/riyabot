import React from 'react'
import { Brain, MessageCircle } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import type { PersonalityConfig } from '../types'

interface PersonalitySectionProps {
  config: PersonalityConfig
  onChange: (config: PersonalityConfig) => void
}

interface MobileTextareaBlockProps {
  icon: React.ReactNode
  iconClassName: string
  label: string
  description?: string
  value: string
  placeholder: string
  rows: number
  onChange: (value: string) => void
}

const MobileTextareaBlock = React.memo(function MobileTextareaBlock({
  icon,
  iconClassName,
  label,
  description,
  value,
  placeholder,
  rows,
  onChange,
}: MobileTextareaBlockProps) {
  return (
    <div className="border-b border-border/70 px-4 py-4 last:border-b-0">
      <div className="flex items-start gap-3">
        <span className={`ios-symbol ios-symbol-sm mt-0.5 ${iconClassName}`}>{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-[15px] font-medium leading-tight">{label}</p>
            {description ? (
              <p className="shrink-0 text-[12px] text-muted-foreground">{description}</p>
            ) : null}
          </div>
          <Textarea
            aria-label={label}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder={placeholder}
            rows={rows}
            className="mt-2 min-h-0 resize-none border-0 bg-transparent px-0 py-0 text-[14px] leading-relaxed shadow-none focus-visible:ring-0"
          />
        </div>
      </div>
    </div>
  )
})

export const PersonalitySection = React.memo(function PersonalitySection({
  config,
  onChange,
}: PersonalitySectionProps) {
  return (
    <>
      <div className="ios-group overflow-hidden sm:hidden">
        <MobileTextareaBlock
          icon={<Brain className="h-4 w-4" />}
          iconClassName="ios-symbol-purple"
          label="人格特质"
          description="120 字内"
          value={config.personality}
          onChange={(personality) => onChange({ ...config, personality })}
          placeholder="描述人格特质和身份特征"
          rows={3}
        />
        <MobileTextareaBlock
          icon={<MessageCircle className="h-4 w-4" />}
          iconClassName="ios-symbol-blue"
          label="表达风格"
          value={config.reply_style}
          onChange={(reply_style) => onChange({ ...config, reply_style })}
          placeholder="描述说话的表达风格和习惯"
          rows={3}
        />
      </div>

      <div className="ios-group hidden space-y-6 p-4 sm:block sm:p-6">
        <div>
          <h3 className="mb-4 text-lg font-semibold">人格设置</h3>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="personality">人格特质</Label>
              <Textarea
                id="personality"
                value={config.personality}
                onChange={(event) => onChange({ ...config, personality: event.target.value })}
                placeholder="描述人格特质和身份特征（建议120字以内）"
                rows={3}
              />
              <p className="text-xs text-muted-foreground">建议120字以内，描述人格特质和身份特征</p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="reply_style">表达风格</Label>
              <Textarea
                id="reply_style"
                value={config.reply_style}
                onChange={(event) => onChange({ ...config, reply_style: event.target.value })}
                placeholder="描述说话的表达风格和习惯"
                rows={3}
              />
            </div>
          </div>
        </div>
      </div>
    </>
  )
})
