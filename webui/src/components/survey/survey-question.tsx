/**
 * 单个问题渲染组件
 */

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Checkbox } from '@/components/ui/checkbox'
import { Slider } from '@/components/ui/slider'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Star } from 'lucide-react'
import type { SurveyQuestion as SurveyQuestionType } from '@/types/survey'

const starActiveClass = 'fill-[rgb(255_204_0)] text-[rgb(255_204_0)]'
const starInactiveClass = 'text-muted-foreground/35 hover:text-[rgb(255_204_0)]'

interface SurveyQuestionProps {
  question: SurveyQuestionType
  value: string | string[] | number | undefined
  onChange: (value: string | string[] | number) => void
  error?: string
  disabled?: boolean
  indexLabel?: string
}

export function SurveyQuestion({
  question,
  value,
  onChange,
  error,
  disabled = false,
  indexLabel,
}: SurveyQuestionProps) {
  const [hoverRating, setHoverRating] = useState<number | null>(null)

  // 如果问题设置了只读，则禁用输入
  const isDisabled = disabled || question.readOnly

  const renderQuestion = () => {
    switch (question.type) {
      case 'single':
        return (
          <RadioGroup
            value={(value as string) || ''}
            onValueChange={onChange}
            disabled={isDisabled}
            className="gap-0 overflow-hidden rounded-[16px] border border-border/35 bg-secondary/45"
          >
            {question.options?.map((option) => (
              <Label
                key={option.id}
                htmlFor={`${question.id}-${option.id}`}
                className="ios-touch flex min-h-[52px] cursor-pointer items-center gap-3 border-b border-border/35 px-3.5 py-2.5 text-[15px] font-normal leading-5 last:border-b-0 hover:bg-accent/45"
              >
                <RadioGroupItem value={option.value} id={`${question.id}-${option.id}`} />
                <span className="min-w-0 flex-1">{option.label}</span>
              </Label>
            ))}
          </RadioGroup>
        )

      case 'multiple': {
        const selectedValues = (value as string[]) || []
        return (
          <div className="space-y-2">
            <div className="overflow-hidden rounded-[16px] border border-border/35 bg-secondary/45">
              {question.options?.map((option) => (
                <Label
                  key={option.id}
                  htmlFor={`${question.id}-${option.id}`}
                  className="ios-touch flex min-h-[52px] cursor-pointer items-center gap-3 border-b border-border/35 px-3.5 py-2.5 text-[15px] font-normal leading-5 last:border-b-0 hover:bg-accent/45"
                >
                  <Checkbox
                    id={`${question.id}-${option.id}`}
                    checked={selectedValues.includes(option.value)}
                    disabled={
                      isDisabled ||
                      (question.maxSelections !== undefined &&
                        selectedValues.length >= question.maxSelections &&
                        !selectedValues.includes(option.value))
                    }
                    onCheckedChange={(checked) => {
                      if (checked) {
                        onChange([...selectedValues, option.value])
                      } else {
                        onChange(selectedValues.filter((v) => v !== option.value))
                      }
                    }}
                  />
                  <span className="min-w-0 flex-1">{option.label}</span>
                </Label>
              ))}
            </div>
            {question.maxSelections && (
              <p className="px-1 text-[12px] leading-4 text-muted-foreground">
                最多选择 {question.maxSelections} 项
              </p>
            )}
          </div>
        )
      }

      case 'text':
        return (
          <Input
            value={(value as string) || ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={question.placeholder || '请输入...'}
            disabled={isDisabled}
            readOnly={question.readOnly}
            maxLength={question.maxLength}
            className={cn(
              'min-h-12 rounded-[16px] bg-secondary/45 px-4 text-[15px]',
              question.readOnly && 'cursor-not-allowed bg-muted/55'
            )}
          />
        )

      case 'textarea':
        return (
          <div className="space-y-1">
            <Textarea
              value={(value as string) || ''}
              onChange={(e) => onChange(e.target.value)}
              placeholder={question.placeholder || '请输入...'}
              disabled={isDisabled}
              readOnly={question.readOnly}
              maxLength={question.maxLength}
              rows={4}
              className={cn(
                'min-h-28 rounded-[16px] bg-secondary/45 px-4 text-[15px] leading-6',
                question.readOnly && 'cursor-not-allowed bg-muted/55'
              )}
            />
            {question.maxLength && (
              <p className="px-1 text-right text-[12px] leading-4 text-muted-foreground">
                {((value as string) || '').length} / {question.maxLength}
              </p>
            )}
          </div>
        )

      case 'rating': {
        const ratingValue = (value as number) || 0
        const displayRating = hoverRating !== null ? hoverRating : ratingValue
        return (
          <div className="flex items-center gap-1.5">
            {[1, 2, 3, 4, 5].map((star) => (
              <button
                key={star}
                type="button"
                disabled={isDisabled}
                className={cn(
                  'ios-touch rounded-full p-1 transition-colors focus:outline-none focus:ring-2 focus:ring-ring',
                  isDisabled && 'cursor-not-allowed opacity-50'
                )}
                onMouseEnter={() => !isDisabled && setHoverRating(star)}
                onMouseLeave={() => setHoverRating(null)}
                onClick={() => !isDisabled && onChange(star)}
              >
                <Star
                  className={cn(
                    'h-6 w-6 transition-colors',
                    star <= displayRating ? starActiveClass : starInactiveClass
                  )}
                />
              </button>
            ))}
            {ratingValue > 0 && (
              <span className="ml-2 text-sm text-muted-foreground">{ratingValue} / 5</span>
            )}
          </div>
        )
      }

      case 'scale': {
        const min = question.min ?? 1
        const max = question.max ?? 10
        const step = question.step ?? 1
        const scaleValue = (value as number) ?? min
        return (
          <div className="space-y-4">
            <Slider
              value={[scaleValue]}
              onValueChange={([val]) => onChange(val)}
              min={min}
              max={max}
              step={step}
              disabled={isDisabled}
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>{question.minLabel || min}</span>
              <span className="font-medium text-foreground">{scaleValue}</span>
              <span>{question.maxLabel || max}</span>
            </div>
          </div>
        )
      }

      case 'dropdown':
        return (
          <Select value={(value as string) || ''} onValueChange={onChange} disabled={isDisabled}>
            <SelectTrigger className="min-h-12 rounded-[16px] bg-secondary/45 px-4 text-[15px]">
              <SelectValue placeholder={question.placeholder || '请选择...'} />
            </SelectTrigger>
            <SelectContent>
              {question.options?.map((option) => (
                <SelectItem key={option.id} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )

      default:
        return <div className="text-muted-foreground">不支持的问题类型</div>
    }
  }

  return (
    <div className="w-full space-y-3">
      <div className="flex items-start gap-3">
        {indexLabel && (
          <span className="mt-0.5 shrink-0 rounded-full bg-secondary px-2.5 py-0.5 text-[12px] font-medium leading-5 text-muted-foreground">
            {indexLabel}
            {question.required && <span className="text-destructive ml-0.5">*</span>}
          </span>
        )}
        <div className="min-w-0 flex-1 space-y-1">
          <Label className="text-[16px] font-medium leading-[1.42]">
            {question.title}
            {question.required && !indexLabel && <span className="text-destructive ml-1">*</span>}
          </Label>
          {question.description && (
            <p className="text-[13px] leading-5 text-muted-foreground">{question.description}</p>
          )}
        </div>
      </div>

      {renderQuestion()}

      {error && <p className="text-destructive text-[13px] leading-5">{error}</p>}
    </div>
  )
}
