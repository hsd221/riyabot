import { useEffect, useState } from 'react'
import { ToastAction } from '@/components/ui/toast'
import { useToast } from '@/hooks/use-toast'
import { getUpdateStatus, type UpdateStatus } from '@/lib/update-api'

function updateDescription(status: UpdateStatus): string {
  if (status.channel === 'stable') {
    return status.target
      ? `${status.target.ref} 已可用，当前跟踪正式版频道。`
      : '正式版频道有可用更新。'
  }

  const revision = status.target?.revision.slice(0, 7)
  return revision ? `dev 分支有新提交 ${revision}。` : 'dev 分支有新提交。'
}

export function useDashboardUpdateCheck(): UpdateStatus | null {
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null)
  const { toast } = useToast()

  useEffect(() => {
    let active = true

    const checkForUpdates = async () => {
      try {
        const status = await getUpdateStatus()
        if (!active) return

        setUpdateStatus(status)
        if (!status.update_available) return

        toast({
          title: '发现新版本',
          description: updateDescription(status),
          action: (
            <ToastAction altText="打开系统更新" asChild>
              <a href="/settings?tab=about">查看更新</a>
            </ToastAction>
          ),
        })
      } catch {
        return
      }
    }

    void checkForUpdates()
    return () => {
      active = false
    }
  }, [toast])

  return updateStatus
}
