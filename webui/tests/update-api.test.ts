import { afterEach, describe, expect, it, mock } from 'bun:test'
import {
  createUpdateTask,
  getUpdateResult,
  getUpdateStatus,
  updateUpdatePreferences,
} from '../src/lib/update-api'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe('update API', () => {
  it('reads the local Runner result without forcing remote discovery', async () => {
    const revision = '2'.repeat(40)
    const fetchMock = mock(async () =>
      Response.json({
        last_result: {
          success: true,
          code: 'updated',
          message: 'updated',
          completed_at: '2026-07-31T12:00:00+00:00',
          target_revision: revision,
        },
      })
    )
    globalThis.fetch = fetchMock as typeof fetch

    const response = await getUpdateResult()

    expect(response.last_result?.target_revision).toBe(revision)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/webui/update-tasks/result',
      expect.objectContaining({ method: 'GET', credentials: 'include' })
    )
  })

  it('requests a forced status refresh', async () => {
    const fetchMock = mock(async () =>
      Response.json({
        channel: 'dev',
        current: {
          version: '1.0.0',
          revision: '1'.repeat(40),
          ref: 'dev',
          installation_mode: 'source',
          dirty: false,
        },
        target: { ref: 'dev', revision: '2'.repeat(40), summary: 'new commit' },
        update_available: true,
        can_apply: true,
        block_code: null,
        block_message: null,
        checked_at: '2026-07-31T12:00:00+00:00',
        update_pending: false,
        last_result: null,
      })
    )
    globalThis.fetch = fetchMock as typeof fetch

    const status = await getUpdateStatus(true)

    expect(status.target?.revision).toBe('2'.repeat(40))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/webui/updates/status?force=true',
      expect.objectContaining({ method: 'GET', credentials: 'include' })
    )
  })

  it('shares concurrent forced status refreshes', async () => {
    const fetchMock = mock(async () =>
      Response.json({
        channel: 'dev',
        current: {
          version: '1.0.0',
          revision: '1'.repeat(40),
          ref: 'dev',
          installation_mode: 'source',
          dirty: false,
        },
        target: { ref: 'dev', revision: '2'.repeat(40), summary: 'new commit' },
        update_available: true,
        can_apply: true,
        block_code: null,
        block_message: null,
        checked_at: '2026-07-31T12:00:00+00:00',
        update_pending: false,
        last_result: null,
      })
    )
    globalThis.fetch = fetchMock as typeof fetch

    const [first, second] = await Promise.all([getUpdateStatus(true), getUpdateStatus(true)])

    expect(first.target?.revision).toBe('2'.repeat(40))
    expect(second.target?.revision).toBe('2'.repeat(40))
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('shares concurrent cached status reads', async () => {
    const fetchMock = mock(async () =>
      Response.json({
        channel: 'stable',
        current: {
          version: '1.0.0',
          revision: '1'.repeat(40),
          ref: 'main',
          installation_mode: 'source',
          dirty: false,
        },
        target: { ref: 'v1.0.0', revision: '1'.repeat(40), summary: 'stable' },
        update_available: false,
        can_apply: false,
        block_code: null,
        block_message: null,
        checked_at: '2026-07-31T12:00:00+00:00',
        update_pending: false,
        last_result: null,
      })
    )
    globalThis.fetch = fetchMock as typeof fetch

    const [first, second] = await Promise.all([getUpdateStatus(), getUpdateStatus()])

    expect(first.channel).toBe('stable')
    expect(second.channel).toBe('stable')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('persists only the selected tracking channel', async () => {
    const fetchMock = mock(async () => Response.json({ channel: 'stable' }))
    globalThis.fetch = fetchMock as typeof fetch

    await updateUpdatePreferences('stable')

    const [, init] = fetchMock.mock.calls[0]
    expect(init?.method).toBe('PATCH')
    expect(init?.body).toBe(JSON.stringify({ channel: 'stable' }))
  })

  it('binds task creation to the revision confirmed by the user', async () => {
    const revision = 'a'.repeat(40)
    const fetchMock = mock(async () =>
      Response.json({ accepted: true, target_revision: revision, message: 'accepted' })
    )
    globalThis.fetch = fetchMock as typeof fetch

    const response = await createUpdateTask(revision)

    expect(response.accepted).toBe(true)
    const [, init] = fetchMock.mock.calls[0]
    expect(init?.method).toBe('POST')
    expect(init?.body).toBe(JSON.stringify({ expected_target_revision: revision }))
  })
})
