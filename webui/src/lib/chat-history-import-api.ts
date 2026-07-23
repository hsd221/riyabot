import { fetchWithAuth } from '@/lib/fetch-with-auth'
import type {
  ChatHistoryImportDeleteResponse,
  ChatHistoryImportListResponse,
  ChatHistoryImportStartRequest,
  ChatHistoryImportTask,
} from '@/types/chat-history-import'

const API_BASE = '/api/webui/chat-history-imports'

async function parseError(response: Response, fallback: string): Promise<Error> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string' && body.detail) {
      return new Error(body.detail)
    }
  } catch {
    // Fall through to the stable client-side message.
  }
  return new Error(fallback)
}

export async function uploadChatHistory(file: File): Promise<ChatHistoryImportTask> {
  const formData = new FormData()
  formData.append('file', file, file.name)
  const response = await fetchWithAuth(API_BASE, {
    method: 'POST',
    body: formData,
  })
  if (!response.ok) {
    throw await parseError(response, '上传并分析聊天记录失败')
  }
  return response.json()
}

export async function listChatHistoryImports(
  signal?: AbortSignal
): Promise<ChatHistoryImportListResponse> {
  const response = await fetchWithAuth(API_BASE, { signal, cache: 'no-store' })
  if (!response.ok) {
    throw await parseError(response, '获取聊天记录导入任务失败')
  }
  return response.json()
}

export async function getChatHistoryImport(
  importId: string,
  signal?: AbortSignal
): Promise<ChatHistoryImportTask> {
  const response = await fetchWithAuth(`${API_BASE}/${encodeURIComponent(importId)}`, {
    signal,
    cache: 'no-store',
  })
  if (!response.ok) {
    throw await parseError(response, '获取导入任务详情失败')
  }
  return response.json()
}

export async function startChatHistoryImport(
  importId: string,
  request: ChatHistoryImportStartRequest
): Promise<ChatHistoryImportTask> {
  const response = await fetchWithAuth(`${API_BASE}/${encodeURIComponent(importId)}/start`, {
    method: 'POST',
    body: JSON.stringify(request),
  })
  if (!response.ok) {
    throw await parseError(response, '启动聊天记录学习失败')
  }
  return response.json()
}

export async function deleteChatHistoryImport(
  importId: string
): Promise<ChatHistoryImportDeleteResponse> {
  const response = await fetchWithAuth(`${API_BASE}/${encodeURIComponent(importId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw await parseError(response, '删除聊天记录导入任务失败')
  }
  return response.json()
}
