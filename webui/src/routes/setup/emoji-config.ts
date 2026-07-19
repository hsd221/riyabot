import type { EmojiConfig } from './types'

export const DEFAULT_EMOJI_CONFIG: EmojiConfig = {
  emoji_chance: 0.4,
  max_reg_num: 40,
  do_replace: true,
  check_interval: 10,
  steal_emoji: true,
  content_filtration: false,
  filtration_prompt: '符合公序良俗',
  usage_scene_enabled: true,
  usage_scene_context_messages: 8,
  usage_scene_max_scenes: 8,
  usage_scene_weight: 0.6,
  selection_candidate_count: 8,
}

export function normalizeEmojiConfig(config: Partial<EmojiConfig>): EmojiConfig {
  return {
    emoji_chance: config.emoji_chance ?? DEFAULT_EMOJI_CONFIG.emoji_chance,
    max_reg_num: config.max_reg_num ?? DEFAULT_EMOJI_CONFIG.max_reg_num,
    do_replace: config.do_replace ?? DEFAULT_EMOJI_CONFIG.do_replace,
    check_interval: config.check_interval ?? DEFAULT_EMOJI_CONFIG.check_interval,
    steal_emoji: config.steal_emoji ?? DEFAULT_EMOJI_CONFIG.steal_emoji,
    content_filtration: config.content_filtration ?? DEFAULT_EMOJI_CONFIG.content_filtration,
    filtration_prompt: config.filtration_prompt ?? DEFAULT_EMOJI_CONFIG.filtration_prompt,
    usage_scene_enabled: config.usage_scene_enabled ?? DEFAULT_EMOJI_CONFIG.usage_scene_enabled,
    usage_scene_context_messages:
      config.usage_scene_context_messages ?? DEFAULT_EMOJI_CONFIG.usage_scene_context_messages,
    usage_scene_max_scenes:
      config.usage_scene_max_scenes ?? DEFAULT_EMOJI_CONFIG.usage_scene_max_scenes,
    usage_scene_weight: config.usage_scene_weight ?? DEFAULT_EMOJI_CONFIG.usage_scene_weight,
    selection_candidate_count:
      config.selection_candidate_count ?? DEFAULT_EMOJI_CONFIG.selection_candidate_count,
  }
}
