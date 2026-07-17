import { describe, expect, it } from 'bun:test'

import {
  formatDreamRunDuration,
  getDreamRunStatusLabel,
  getDreamRunTypeLabel,
  parseDreamRunSummary,
} from '../src/components/memory/dream-run-summary'

describe('dream run summary parsing', () => {
  it('separates sleep phases from concrete run results', () => {
    const parsed = parseDreamRunSummary(
      '睡眠阶段: N2(原始分诊+评分重估) | N3(冲突扫描+记忆巩固) | REM(情绪重演+噪声沉淀)，分诊3条原始消息(高1/中1/低1)，巩固2条记忆，隐私重评: 上锁1条/解锁0条',
      'daily'
    )

    expect(parsed.phases.map((phase) => phase.code)).toEqual(['N2', 'N3', 'REM'])
    expect(parsed.phases[0].actions).toEqual(['原始分诊', '评分重估'])
    expect(parsed.activities).toEqual([
      { label: '分诊3条原始消息', details: ['高1', '中1', '低1'] },
      { label: '巩固2条记忆', details: [] },
      { label: '隐私重评', details: ['上锁1条', '解锁0条'] },
    ])
  })

  it('splits monthly comma-delimited outcomes into scannable activities', () => {
    const parsed = parseDreamRunSummary(
      '睡眠阶段: N2(全量审计+健康诊断) | N3(画像审计+关系重建) | REM(跨域洞察+月度报告)，审计42原子, 2个问题, 3条洞察',
      'monthly'
    )

    expect(parsed.activities.map((activity) => activity.label)).toEqual([
      '审计42原子',
      '2个问题',
      '3条洞察',
    ])
  })

  it('uses the cycle definition for legacy summaries without phase metadata', () => {
    const parsed = parseDreamRunSummary('回收2条噪声并生成1条洞见', 'weekly')

    expect(parsed.phases).toHaveLength(3)
    expect(parsed.phases[0]).toMatchObject({
      code: 'N2',
      actions: ['冲突仲裁', '评分重估'],
    })
    expect(parsed.activities).toEqual([{ label: '回收2条噪声并生成1条洞见', details: [] }])
  })

  it('does not discard a legacy phase sentence that does not match the current grammar', () => {
    const parsed = parseDreamRunSummary('睡眠阶段: 完成旧版记忆整理', 'daily')

    expect(parsed.activities).toEqual([{ label: '睡眠阶段', details: ['完成旧版记忆整理'] }])
  })

  it('keeps the workflow visible when a run made no data changes', () => {
    const parsed = parseDreamRunSummary('无操作', 'daily')

    expect(parsed.phases).toHaveLength(3)
    expect(parsed.activities).toEqual([{ label: '本轮没有需要变更的数据', details: [] }])
  })

  it('returns an empty result list while a summary is not available yet', () => {
    const parsed = parseDreamRunSummary(null, 'daily')

    expect(parsed.phases).toHaveLength(3)
    expect(parsed.activities).toEqual([])
  })

  it('formats cycle names, statuses, and elapsed time for people rather than internal values', () => {
    expect(getDreamRunTypeLabel('daily')).toBe('每日整理')
    expect(getDreamRunTypeLabel('weekly')).toBe('每周整理')
    expect(getDreamRunStatusLabel('completed')).toBe('已完成')
    expect(getDreamRunStatusLabel('running')).toBe('运行中')
    expect(formatDreamRunDuration('2026-07-17T10:00:00', '2026-07-17T10:01:05')).toBe('1分 5秒')
    expect(formatDreamRunDuration('2026-07-17T10:00:00', null)).toBe('进行中')
    expect(formatDreamRunDuration('2026-07-17T10:00:00', null, 'failed')).toBe('-')
  })
})
