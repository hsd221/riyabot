import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import type { ComponentPropsWithoutRef } from 'react'

interface MarkdownRendererProps {
  content: string
  className?: string
}

export function MarkdownRenderer({ content, className = '' }: MarkdownRendererProps) {
  return (
    <div className={`prose prose-sm dark:prose-invert max-w-none ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          // 自定义代码块样式
          code({
            inline,
            className,
            children,
            ...props
          }: ComponentPropsWithoutRef<'code'> & { inline?: boolean }) {
            return inline ? (
              <code
                className="rounded-[7px] border border-black/[0.035] bg-white/[0.58] px-1.5 py-0.5 font-mono text-[0.92em] shadow-[0_1px_0_rgba(255,255,255,0.54)_inset] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.08]"
                {...props}
              >
                {children}
              </code>
            ) : (
              <code
                className={`${className} ios-scrollbar-none block overflow-x-auto rounded-[16px] border border-black/[0.035] bg-white/[0.72] p-4 font-mono text-[13px] leading-6 shadow-[0_1px_0_rgba(255,255,255,0.68)_inset,0_8px_22px_rgba(31,41,55,0.045)] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.08]`}
                {...props}
              >
                {children}
              </code>
            )
          },
          // 自定义表格样式
          table({ children, ...props }) {
            return (
              <div className="ios-scrollbar-none overflow-x-auto rounded-[16px] border border-black/[0.035] bg-white/[0.72] shadow-[0_1px_0_rgba(255,255,255,0.68)_inset,0_8px_22px_rgba(31,41,55,0.045)] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.08]">
                <table className="w-full border-collapse" {...props}>
                  {children}
                </table>
              </div>
            )
          },
          th({ children, ...props }) {
            return (
              <th
                className="border-b border-r border-border/45 bg-[rgb(120_120_128_/_0.055)] px-4 py-2.5 text-left text-[12px] font-medium leading-4 text-muted-foreground last:border-r-0"
                {...props}
              >
                {children}
              </th>
            )
          },
          td({ children, ...props }) {
            return (
              <td
                className="border-b border-r border-border/45 px-4 py-2.5 last:border-r-0"
                {...props}
              >
                {children}
              </td>
            )
          },
          // 自定义链接样式
          a({ children, ...props }) {
            return (
              <a
                className="text-primary hover:underline"
                target="_blank"
                rel="noopener noreferrer"
                {...props}
              >
                {children}
              </a>
            )
          },
          // 自定义引用块样式
          blockquote({ children, ...props }) {
            return (
              <blockquote
                className="relative my-4 rounded-[16px] border border-black/[0.035] bg-white/[0.62] px-5 py-3 text-muted-foreground shadow-[0_1px_0_rgba(255,255,255,0.62)_inset] backdrop-blur-xl before:absolute before:bottom-3 before:left-3 before:top-3 before:w-1 before:rounded-full before:bg-primary/70 before:content-[''] dark:border-white/10 dark:bg-white/[0.08]"
                {...props}
              >
                {children}
              </blockquote>
            )
          },
          // 自定义标题样式
          h1({ children, ...props }) {
            return (
              <h1
                className="mb-4 mt-5 text-2xl font-semibold leading-tight tracking-normal"
                {...props}
              >
                {children}
              </h1>
            )
          },
          h2({ children, ...props }) {
            return (
              <h2
                className="mb-3 mt-5 text-xl font-semibold leading-snug tracking-normal"
                {...props}
              >
                {children}
              </h2>
            )
          },
          h3({ children, ...props }) {
            return (
              <h3
                className="mb-2 mt-4 text-lg font-semibold leading-snug tracking-normal"
                {...props}
              >
                {children}
              </h3>
            )
          },
          h4({ children, ...props }) {
            return (
              <h4
                className="mb-2 mt-3 text-base font-semibold leading-snug tracking-normal"
                {...props}
              >
                {children}
              </h4>
            )
          },
          // 自定义列表样式
          ul({ children, ...props }) {
            return (
              <ul className="my-2 list-inside list-disc space-y-1" {...props}>
                {children}
              </ul>
            )
          },
          ol({ children, ...props }) {
            return (
              <ol className="my-2 list-inside list-decimal space-y-1" {...props}>
                {children}
              </ol>
            )
          },
          // 自定义段落样式
          p({ children, ...props }) {
            return (
              <p className="my-2 leading-relaxed" {...props}>
                {children}
              </p>
            )
          },
          // 自定义分隔线样式
          hr({ ...props }) {
            return <hr className="my-5 border-border/55" {...props} />
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
