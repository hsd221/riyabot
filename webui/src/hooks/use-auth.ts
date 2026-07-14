import { useEffect, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { checkAuthStatus, getAuthStatus } from '@/lib/fetch-with-auth'

export function useAuthGuard() {
  const navigate = useNavigate()
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    let cancelled = false

    const verifyAuth = async () => {
      try {
        const authStatus = await getAuthStatus()
        if (!cancelled && !authStatus.passwordConfigured) {
          navigate({ to: '/setup' })
          return
        }

        if (!cancelled && !authStatus.authenticated) {
          navigate({ to: '/auth' })
          return
        }

        if (!cancelled && authStatus.authenticated) {
          const needsSetup = await checkFirstSetup()
          const setupAllowedPaths = [
            '/setup',
            '/config/bot',
            '/config/modelProvider',
            '/config/model',
          ]
          if (needsSetup && !setupAllowedPaths.includes(window.location.pathname)) {
            navigate({ to: '/setup' })
          }
        }
      } catch {
        // 发生错误时也跳转到登录页
        if (!cancelled) {
          navigate({ to: '/auth' })
        }
      } finally {
        if (!cancelled) {
          setChecking(false)
        }
      }
    }

    verifyAuth()

    return () => {
      cancelled = true
    }
  }, [navigate])

  return { checking }
}

/**
 * 检查是否已认证（异步）
 */
export async function checkAuth(): Promise<boolean> {
  return await checkAuthStatus()
}

/**
 * 检查是否需要首次配置
 */
export async function checkFirstSetup(): Promise<boolean> {
  try {
    const response = await fetch('/api/webui/setup/status', {
      method: 'GET',
      credentials: 'include',
    })

    const data = await response.json()

    if (response.ok) {
      return data.is_first_setup
    }

    return false
  } catch (error) {
    console.error('检查首次配置状态失败:', error)
    return false
  }
}
