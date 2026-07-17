/** 将后端保存的梦境摘要转换成适合界面展示的阶段与结果。 */
export type DreamPhaseCode = 'N2' | 'N3' | 'REM'

export interface DreamRunPhase {
  code: DreamPhaseCode
  title: string
  description: string
  actions: string[]
}

export interface DreamRunActivity {
  label: string
  details: string[]
}

export interface ParsedDreamRunSummary {
  phases: DreamRunPhase[]
  activities: DreamRunActivity[]
}

const PHASE_ORDER: DreamPhaseCode[] = ['N2', 'N3', 'REM']

const PHASE_META: Record<DreamPhaseCode, Pick<DreamRunPhase, 'title' | 'description'>> = {
  N2: {
    title: '筛选与校准',
    description: '先判断哪些信息值得继续整理',
  },
  N3: {
    title: '深度巩固',
    description: '处理冲突、权重、隐私与遗忘',
  },
  REM: {
    title: '联想与提炼',
    description: '连接信息并回收噪声、生成洞见',
  },
}

const DEFAULT_PHASE_ACTIONS: Partial<Record<string, Record<DreamPhaseCode, string[]>>> = {
  daily: {
    N2: ['原始分诊', '评分重估'],
    N3: ['冲突扫描', '模式提炼', '隐私重评', '记忆巩固', '遗忘维护'],
    REM: ['情绪重演', '噪声沉淀'],
  },
  weekly: {
    N2: ['冲突仲裁', '评分重估'],
    N3: ['隐私重评', '全量巩固', '软上限合并', '图谱构建'],
    REM: ['跨日模式', '洞见编织', '噪声回收'],
  },
  monthly: {
    N2: ['全量审计', '健康诊断'],
    N3: ['画像审计', '隐私重评', '软上限合并', '关系重建', '遗忘维护'],
    REM: ['跨域洞察', '噪声回收', '月度报告'],
  },
}

const DREAM_RUN_TYPE_LABELS: Record<string, string> = {
  daily: '每日整理',
  weekly: '每周整理',
  monthly: '每月整理',
}

const DREAM_RUN_STATUS_LABELS: Record<string, string> = {
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  pending: '等待中',
}

export function getDreamRunTypeLabel(runType: string): string {
  return DREAM_RUN_TYPE_LABELS[runType] ?? runType
}

export function getDreamRunStatusLabel(status: string): string {
  return DREAM_RUN_STATUS_LABELS[status] ?? status
}

export function formatDreamRunDuration(
  startTime: string | null | undefined,
  endTime: string | null | undefined,
  status?: string
): string {
  if (!startTime) return '-'
  if (!endTime) return status && status !== 'running' ? '-' : '进行中'

  const elapsedMilliseconds = new Date(endTime).getTime() - new Date(startTime).getTime()
  if (!Number.isFinite(elapsedMilliseconds) || elapsedMilliseconds < 0) return '-'

  const totalSeconds = Math.max(1, Math.round(elapsedMilliseconds / 1000))
  const days = Math.floor(totalSeconds / 86_400)
  const hours = Math.floor((totalSeconds % 86_400) / 3_600)
  const minutes = Math.floor((totalSeconds % 3_600) / 60)
  const seconds = totalSeconds % 60

  if (days > 0) return hours > 0 ? `${days}天 ${hours}小时` : `${days}天`
  if (hours > 0) return minutes > 0 ? `${hours}小时 ${minutes}分` : `${hours}小时`
  if (minutes > 0) return seconds > 0 ? `${minutes}分 ${seconds}秒` : `${minutes}分`
  return `${seconds}秒`
}

function buildPhases(
  runType: string,
  parsedActions: Partial<Record<DreamPhaseCode, string[]>> = {}
): DreamRunPhase[] {
  const fallback = DEFAULT_PHASE_ACTIONS[runType]

  return PHASE_ORDER.flatMap((code) => {
    const actions = parsedActions[code] ?? fallback?.[code]
    if (!actions?.length) return []

    return [
      {
        code,
        ...PHASE_META[code],
        actions: [...actions],
      },
    ]
  })
}

function parsePhasePrefix(summary: string): {
  phases: Partial<Record<DreamPhaseCode, string[]>>
  remainder: string
} {
  if (!/^睡眠阶段\s*[:：]/.test(summary)) {
    return { phases: {}, remainder: summary }
  }

  const separatorIndex = summary.indexOf('，')
  const phaseText = separatorIndex >= 0 ? summary.slice(0, separatorIndex) : summary
  const remainder = separatorIndex >= 0 ? summary.slice(separatorIndex + 1).trim() : ''
  const phases: Partial<Record<DreamPhaseCode, string[]>> = {}

  for (const match of phaseText.matchAll(/\b(N2|N3|REM)\s*\(([^)]*)\)/g)) {
    const code = match[1] as DreamPhaseCode
    phases[code] = match[2]
      .split('+')
      .map((action) => action.trim())
      .filter(Boolean)
  }

  if (Object.keys(phases).length === 0) {
    return { phases: {}, remainder: summary }
  }

  return { phases, remainder }
}

function parseActivity(segment: string): DreamRunActivity {
  if (segment === '无操作') {
    return { label: '本轮没有需要变更的数据', details: [] }
  }

  const colonMatch = segment.match(/^([^:：]+)\s*[:：]\s*(.+)$/)
  if (colonMatch) {
    return {
      label: colonMatch[1].trim(),
      details: colonMatch[2]
        .split('/')
        .map((detail) => detail.trim())
        .filter(Boolean),
    }
  }

  const parentheticalMatch = segment.match(/^(.+?)\s*\(([^()]*)\)$/)
  if (parentheticalMatch) {
    return {
      label: parentheticalMatch[1].trim(),
      details: parentheticalMatch[2]
        .split('/')
        .map((detail) => detail.trim())
        .filter(Boolean),
    }
  }

  return { label: segment, details: [] }
}

export function parseDreamRunSummary(
  summary: string | null | undefined,
  runType: string
): ParsedDreamRunSummary {
  const normalizedSummary = summary?.trim() ?? ''
  const { phases: parsedPhases, remainder } = parsePhasePrefix(normalizedSummary)
  const activities = remainder
    .split(/\s*[，,]\s*/)
    .map((segment) => segment.trim())
    .filter(Boolean)
    .map(parseActivity)

  return {
    phases: buildPhases(runType, parsedPhases),
    activities,
  }
}
