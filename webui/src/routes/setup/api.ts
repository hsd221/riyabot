// 设置向导API调用函数

import { fetchWithAuth, getAuthHeaders } from '@/lib/fetch-with-auth'
import type {
  AgreementStatus,
  BotBasicConfig,
  PersonalityConfig,
  EmojiConfig,
  OtherBasicConfig,
} from './types'

// ===== 协议确认 =====

export async function loadAgreementStatus(): Promise<AgreementStatus> {
  const response = await fetchWithAuth('/api/webui/setup/agreement', {
    method: 'GET',
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    throw new Error('读取协议状态失败')
  }

  return await response.json()
}

export async function confirmAgreement(
  eulaHash: string,
  privacyHash: string
): Promise<AgreementStatus> {
  const response = await fetchWithAuth('/api/webui/setup/agreement/confirm', {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({
      eula_hash: eulaHash,
      privacy_hash: privacyHash,
    }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '确认协议失败')
  }

  const data = await response.json()
  return data.agreement
}

// ===== 读取配置 =====

// 读取Bot基础配置
export async function loadBotBasicConfig(): Promise<BotBasicConfig> {
  const response = await fetchWithAuth('/api/webui/config/bot', {
    method: 'GET',
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    throw new Error('读取Bot配置失败')
  }

  const data = await response.json()
  const botConfig = data.config.bot || {}

  return {
    qq_account: botConfig.qq_account || 0,
    nickname: botConfig.nickname || '',
    alias_names: botConfig.alias_names || [],
  }
}

// 读取人格配置
export async function loadPersonalityConfig(): Promise<PersonalityConfig> {
  const response = await fetchWithAuth('/api/webui/config/bot', {
    method: 'GET',
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    throw new Error('读取人格配置失败')
  }

  const data = await response.json()
  const personalityConfig = data.config.personality || {}

  return {
    personality: personalityConfig.personality || '',
    reply_style: personalityConfig.reply_style || '',
    plan_style: personalityConfig.plan_style || '',
  }
}

// 读取表情包配置
export async function loadEmojiConfig(): Promise<EmojiConfig> {
  const response = await fetchWithAuth('/api/webui/config/bot', {
    method: 'GET',
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    throw new Error('读取表情包配置失败')
  }

  const data = await response.json()
  const emojiConfig = data.config.emoji || {}

  return {
    emoji_chance: emojiConfig.emoji_chance ?? 0.4,
    max_reg_num: emojiConfig.max_reg_num ?? 40,
    do_replace: emojiConfig.do_replace ?? true,
    check_interval: emojiConfig.check_interval ?? 10,
    steal_emoji: emojiConfig.steal_emoji ?? true,
    content_filtration: emojiConfig.content_filtration ?? false,
    filtration_prompt: emojiConfig.filtration_prompt || '',
  }
}

// 读取其他基础配置
export async function loadOtherBasicConfig(): Promise<OtherBasicConfig> {
  const response = await fetchWithAuth('/api/webui/config/bot', {
    method: 'GET',
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    throw new Error('读取其他配置失败')
  }

  const data = await response.json()
  const config = data.config

  const toolConfig = config.tool || {}
  const expressionConfig = config.expression || {}

  return {
    enable_tool: toolConfig.enable_tool ?? true,
    all_global_jargon: expressionConfig.all_global_jargon ?? true,
  }
}

// ===== 保存配置 =====

// 保存Bot基础配置
export async function saveBotBasicConfig(config: BotBasicConfig) {
  const response = await fetchWithAuth('/api/webui/config/bot/section/bot', {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(config),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '保存Bot基础配置失败')
  }

  return await response.json()
}

// 保存人格配置
export async function savePersonalityConfig(config: PersonalityConfig) {
  const response = await fetchWithAuth('/api/webui/config/bot/section/personality', {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(config),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '保存人格配置失败')
  }

  return await response.json()
}

// 保存表情包配置
export async function saveEmojiConfig(config: EmojiConfig) {
  const response = await fetchWithAuth('/api/webui/config/bot/section/emoji', {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(config),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '保存表情包配置失败')
  }

  return await response.json()
}

// 保存其他基础配置（工具、黑话）
export async function saveOtherBasicConfig(config: OtherBasicConfig) {
  // 需要分别保存到不同的section
  const promises = []

  // 保存tool配置
  promises.push(
    fetchWithAuth('/api/webui/config/bot/section/tool', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ enable_tool: config.enable_tool }),
    })
  )

  // 保存expression中的全局黑话配置
  promises.push(
    fetchWithAuth('/api/webui/config/bot/section/expression', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ all_global_jargon: config.all_global_jargon }),
    })
  )

  const results = await Promise.all(promises)

  // 检查所有请求是否成功
  for (const response of results) {
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || '保存其他配置失败')
    }
  }

  return { success: true }
}

// 标记设置完成
export async function completeSetup() {
  const response = await fetchWithAuth('/api/webui/setup/complete', {
    method: 'POST',
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.message || '标记配置完成失败')
  }

  return await response.json()
}
