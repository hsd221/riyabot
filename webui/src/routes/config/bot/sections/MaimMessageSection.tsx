import React, { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Plus, Trash2 } from 'lucide-react'
import type { MaimMessageConfig } from '../types'

interface MaimMessageSectionProps {
  config: MaimMessageConfig
  onChange: (config: MaimMessageConfig) => void
}

export const MaimMessageSection = React.memo(function MaimMessageSection({ config, onChange }: MaimMessageSectionProps) {
  const [newToken, setNewToken] = useState('')
  const [newApiKey, setNewApiKey] = useState('')

  const authTokens = config.auth_token ?? []
  const allowedApiKeys = config.api_server_allowed_api_keys ?? []

  const addToken = () => {
    const token = newToken.trim()
    if (token && !authTokens.includes(token)) {
      onChange({ ...config, auth_token: [...authTokens, token] })
      setNewToken('')
    }
  }

  const removeToken = (index: number) => {
    onChange({
      ...config,
      auth_token: authTokens.filter((_, i) => i !== index),
    })
  }

  const addApiKey = () => {
    const apiKey = newApiKey.trim()
    if (apiKey && !allowedApiKeys.includes(apiKey)) {
      onChange({ ...config, api_server_allowed_api_keys: [...allowedApiKeys, apiKey] })
      setNewApiKey('')
    }
  }

  const removeApiKey = (index: number) => {
    onChange({
      ...config,
      api_server_allowed_api_keys: allowedApiKeys.filter((_, i) => i !== index),
    })
  }

  return (
    <div className="ios-group p-4 sm:p-6 space-y-6">
      <div>
        <h3 className="text-lg font-semibold mb-4">MaimMessage 配置</h3>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>启用额外新版 API Server</Label>
              <p className="text-sm text-muted-foreground">
                额外监听一个新版 MaimMessage API Server 端口
              </p>
            </div>
            <Switch
              checked={config.enable_api_server}
              onCheckedChange={(checked) => onChange({ ...config, enable_api_server: checked })}
            />
          </div>

          {config.enable_api_server && (
            <div className="space-y-4 rounded-[16px] border border-border/45 bg-muted/35 p-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="api_server_host">主机地址</Label>
                  <Input
                    id="api_server_host"
                    value={config.api_server_host}
                    onChange={(e) => onChange({ ...config, api_server_host: e.target.value })}
                    placeholder="0.0.0.0"
                    className="font-mono text-sm"
                  />
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="api_server_port">端口号</Label>
                  <Input
                    id="api_server_port"
                    type="number"
                    min="1"
                    max="65535"
                    value={config.api_server_port}
                    onChange={(e) => onChange({ ...config, api_server_port: parseInt(e.target.value) })}
                    placeholder="8090"
                  />
                </div>
              </div>

              <div className="flex items-center space-x-2">
                <Switch
                  id="api_server_use_wss"
                  checked={config.api_server_use_wss}
                  onCheckedChange={(checked) => onChange({ ...config, api_server_use_wss: checked })}
                />
                <Label htmlFor="api_server_use_wss" className="cursor-pointer">
                  启用 WSS
                </Label>
              </div>

              {config.api_server_use_wss && (
                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="api_server_cert_file">SSL 证书文件路径</Label>
                    <Input
                      id="api_server_cert_file"
                      value={config.api_server_cert_file}
                      onChange={(e) => onChange({ ...config, api_server_cert_file: e.target.value })}
                      placeholder="cert.pem"
                      className="font-mono text-sm"
                    />
                  </div>

                  <div className="grid gap-2">
                    <Label htmlFor="api_server_key_file">SSL 密钥文件路径</Label>
                    <Input
                      id="api_server_key_file"
                      value={config.api_server_key_file}
                      onChange={(e) => onChange({ ...config, api_server_key_file: e.target.value })}
                      placeholder="key.pem"
                      className="font-mono text-sm"
                    />
                  </div>
                </div>
              )}

              <div>
                <Label className="mb-2 block">允许的 API Key</Label>
                <p className="text-sm text-muted-foreground mb-2">为空时允许所有连接</p>
                <div className="flex gap-2 mb-2">
                  <Input
                    value={newApiKey}
                    onChange={(e) => setNewApiKey(e.target.value)}
                    placeholder="输入 API Key"
                    className="font-mono text-sm"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addApiKey()
                      }
                    }}
                  />
                  <Button onClick={addApiKey} size="sm">
                    <Plus className="h-4 w-4" strokeWidth={2} fill="none" />
                  </Button>
                </div>
                <div className="space-y-2">
                  {allowedApiKeys.map((apiKey, index) => (
                    <div
                      key={index}
                      className="flex items-center justify-between bg-secondary px-3 py-2 rounded-md"
                    >
                      <span className="text-sm font-mono break-all">{apiKey}</span>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 w-6 p-0"
                        onClick={() => removeApiKey(index)}
                      >
                        <Trash2 className="h-3 w-3" strokeWidth={2} fill="none" />
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div>
        <Label className="mb-2 block">旧版 API 认证令牌</Label>
        <p className="text-sm text-muted-foreground mb-2">用于旧版 API 验证，为空则不启用验证</p>
        <div className="flex gap-2 mb-2">
          <Input
            value={newToken}
            onChange={(e) => setNewToken(e.target.value)}
            placeholder="输入认证令牌"
            className="font-mono text-sm"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                addToken()
              }
            }}
          />
          <Button onClick={addToken} size="sm">
            <Plus className="h-4 w-4" strokeWidth={2} fill="none" />
          </Button>
        </div>
        <div className="space-y-2">
          {authTokens.map((token, index) => (
            <div
              key={index}
              className="flex items-center justify-between bg-secondary px-3 py-2 rounded-md"
            >
              <span className="text-sm font-mono break-all">{token}</span>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0"
                onClick={() => removeToken(index)}
              >
                <Trash2 className="h-3 w-3" strokeWidth={2} fill="none" />
              </Button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
})
