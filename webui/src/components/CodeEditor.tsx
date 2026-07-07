import { useEffect, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { json, jsonParseLinter } from '@codemirror/lang-json'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'
import { StreamLanguage } from '@codemirror/language'
import { toml as tomlMode } from '@codemirror/legacy-modes/mode/toml'

export type Language = 'python' | 'json' | 'toml' | 'text'

interface CodeEditorProps {
  value: string
  onChange?: (value: string) => void
  language?: Language
  readOnly?: boolean
  height?: string
  minHeight?: string
  maxHeight?: string
  placeholder?: string
  theme?: 'light' | 'dark'
  className?: string
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const languageExtensions: Record<Language, any[]> = {
  python: [python()],
  json: [json(), jsonParseLinter()],
  toml: [StreamLanguage.define(tomlMode)],
  text: [],
}

const iosEditorTheme = EditorView.theme({
  '&': {
    backgroundColor: 'transparent',
    fontSize: '13px',
  },
  '&.cm-focused': {
    outline: 'none',
  },
  '.cm-scroller': {
    fontFamily:
      'ui-monospace, SFMono-Regular, SF Mono, Menlo, Monaco, Consolas, Liberation Mono, monospace',
    lineHeight: '1.62',
  },
  '.cm-content': {
    padding: '14px 0',
  },
  '.cm-line': {
    padding: '0 14px',
  },
  '.cm-gutters': {
    borderRight: '1px solid rgb(120 120 128 / 0.16)',
    backgroundColor: 'rgb(120 120 128 / 0.08)',
  },
  '.cm-lineNumbers .cm-gutterElement': {
    minWidth: '42px',
    padding: '0 10px 0 12px',
    color: 'rgb(142 142 147 / 0.86)',
  },
  '.cm-activeLine': {
    backgroundColor: 'rgb(120 120 128 / 0.11)',
  },
  '.cm-activeLineGutter': {
    backgroundColor: 'rgb(120 120 128 / 0.12)',
    color: 'rgb(174 174 178)',
  },
})

export function CodeEditor({
  value,
  onChange,
  language = 'text',
  readOnly = false,
  height = '400px',
  minHeight,
  maxHeight,
  placeholder,
  theme = 'dark',
  className = '',
}: CodeEditorProps) {
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  if (!mounted) {
    return (
      <div
        className={`animate-pulse rounded-[18px] border border-black/[0.035] bg-muted/65 shadow-[0_1px_0_rgba(255,255,255,0.58)_inset] ${className}`}
        style={{ height, minHeight, maxHeight }}
      />
    )
  }

  const extensions = [
    ...(languageExtensions[language] || []),
    EditorView.lineWrapping,
    iosEditorTheme,
  ]

  if (readOnly) {
    extensions.push(EditorView.editable.of(false))
  }

  return (
    <div
      className={`overflow-hidden rounded-[18px] border border-black/[0.035] bg-white/[0.78] shadow-[0_1px_0_rgba(255,255,255,0.68)_inset,0_10px_28px_rgba(31,41,55,0.052)] backdrop-blur-2xl dark:border-white/10 dark:bg-white/[0.08] ${className}`}
    >
      <CodeMirror
        value={value}
        height={height}
        minHeight={minHeight}
        maxHeight={maxHeight}
        theme={theme === 'dark' ? oneDark : undefined}
        extensions={extensions}
        onChange={onChange}
        placeholder={placeholder}
        basicSetup={{
          lineNumbers: true,
          highlightActiveLineGutter: true,
          highlightSpecialChars: true,
          history: true,
          foldGutter: true,
          drawSelection: true,
          dropCursor: true,
          allowMultipleSelections: true,
          indentOnInput: true,
          syntaxHighlighting: true,
          bracketMatching: true,
          closeBrackets: true,
          autocompletion: true,
          rectangularSelection: true,
          crosshairCursor: true,
          highlightActiveLine: true,
          highlightSelectionMatches: true,
          closeBracketsKeymap: true,
          defaultKeymap: true,
          searchKeymap: true,
          historyKeymap: true,
          foldKeymap: true,
          completionKeymap: true,
          lintKeymap: true,
        }}
      />
    </div>
  )
}

export default CodeEditor
