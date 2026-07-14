import { fetchWithAuth } from '@/lib/fetch-with-auth'
import type { StatisticsReport } from '@/types/statistics'

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string }
    return body.detail || `请求失败 (${response.status})`
  } catch {
    return `请求失败 (${response.status})`
  }
}

export async function fetchStatisticsReport(
  hours: number,
  signal?: AbortSignal
): Promise<StatisticsReport> {
  const searchParams = new URLSearchParams({
    hours: String(hours),
    recent_limit: '30',
  })
  const response = await fetchWithAuth(`/api/webui/statistics/report?${searchParams}`, { signal })

  if (!response.ok) {
    throw new Error(await getErrorMessage(response))
  }

  return (await response.json()) as StatisticsReport
}
