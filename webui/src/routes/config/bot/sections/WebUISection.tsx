import React from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { WebUIConfig } from '../types'

interface WebUISectionProps {
  config: WebUIConfig
  onChange: (config: WebUIConfig) => void
}

export const WebUISection = React.memo(function WebUISection({ config, onChange }: WebUISectionProps) {
  return (
    <div className="rounded-lg border bg-card p-4 sm:p-6 space-y-4">
      <div>
        <h3 className="text-lg font-semibold mb-4">WebUI 服务配置</h3>
        <div className="grid gap-4">
          <div className="flex items-center space-x-2">
            <Switch
              id="webui_enabled"
              checked={config.enabled}
              onCheckedChange={(checked) => onChange({ ...config, enabled: checked })}
            />
            <Label htmlFor="webui_enabled" className="cursor-pointer">
              启用 WebUI
            </Label>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="webui_mode">运行模式</Label>
              <Select
                value={config.mode}
                onValueChange={(value) => onChange({ ...config, mode: value as 'development' | 'production' })}
              >
                <SelectTrigger id="webui_mode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="development">development</SelectItem>
                  <SelectItem value="production">production</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="anti_crawler_mode">防爬虫模式</Label>
              <Select
                value={config.anti_crawler_mode}
                onValueChange={(value) =>
                  onChange({ ...config, anti_crawler_mode: value as WebUIConfig['anti_crawler_mode'] })
                }
              >
                <SelectTrigger id="anti_crawler_mode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="false">禁用</SelectItem>
                  <SelectItem value="basic">基础</SelectItem>
                  <SelectItem value="loose">宽松</SelectItem>
                  <SelectItem value="strict">严格</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="allowed_ips">IP 白名单</Label>
            <Input
              id="allowed_ips"
              value={config.allowed_ips}
              onChange={(e) => onChange({ ...config, allowed_ips: e.target.value })}
              placeholder="127.0.0.1,192.168.1.0/24"
              className="font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">逗号分隔，支持精确 IP、CIDR 和通配符</p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="trusted_proxies">可信代理 IP</Label>
            <Input
              id="trusted_proxies"
              value={config.trusted_proxies}
              onChange={(e) => onChange({ ...config, trusted_proxies: e.target.value })}
              placeholder="127.0.0.1,172.17.0.1"
              className="font-mono text-sm"
            />
          </div>

          <div className="flex items-center space-x-2">
            <Switch
              id="trust_xff"
              checked={config.trust_xff}
              onCheckedChange={(checked) => onChange({ ...config, trust_xff: checked })}
            />
            <Label htmlFor="trust_xff" className="cursor-pointer">
              信任 X-Forwarded-For
            </Label>
          </div>

          <div className="flex items-center space-x-2">
            <Switch
              id="secure_cookie"
              checked={config.secure_cookie}
              onCheckedChange={(checked) => onChange({ ...config, secure_cookie: checked })}
            />
            <Label htmlFor="secure_cookie" className="cursor-pointer">
              启用安全 Cookie
            </Label>
          </div>
        </div>
      </div>
    </div>
  )
})
