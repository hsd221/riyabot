import { describe, expect, it } from 'bun:test'

import { normalizeEmojiConfig } from '../src/routes/setup/emoji-config'

describe('emoji setup configuration', () => {
  it('preserves customized usage-scene settings when setup reloads the emoji section', () => {
    const config = normalizeEmojiConfig({
      usage_scene_enabled: false,
      usage_scene_context_messages: 12,
      usage_scene_max_scenes: 6,
      usage_scene_weight: 0.75,
      selection_candidate_count: 15,
    })

    expect(config.usage_scene_enabled).toBe(false)
    expect(config.usage_scene_context_messages).toBe(12)
    expect(config.usage_scene_max_scenes).toBe(6)
    expect(config.usage_scene_weight).toBe(0.75)
    expect(config.selection_candidate_count).toBe(15)
  })

  it('fills usage-scene defaults when setup reads an older emoji section', () => {
    const config = normalizeEmojiConfig({})

    expect(config.usage_scene_enabled).toBe(true)
    expect(config.usage_scene_context_messages).toBe(8)
    expect(config.usage_scene_max_scenes).toBe(8)
    expect(config.usage_scene_weight).toBe(0.6)
    expect(config.selection_candidate_count).toBe(8)
  })
})
