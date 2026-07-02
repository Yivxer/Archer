import { contextBridge } from 'electron'
import { ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('archerDesktop', {
  version: '1.0.13',
  platform: process.platform,
  pickFiles: () => ipcRenderer.invoke('archer:pick-files'),
  readFileReferences: (refs: Array<{ path: string; name?: string; size?: number }>) => ipcRenderer.invoke('archer:read-file-references', refs),
  captureScreenshot: () => ipcRenderer.invoke('archer:capture-screenshot'),
  captureWindowScreenshot: () => ipcRenderer.invoke('archer:capture-window-screenshot'),
  listCaptureSources: () => ipcRenderer.invoke('archer:list-capture-sources'),
  captureSource: (sourceId: string) => ipcRenderer.invoke('archer:capture-source', sourceId),
  getApiToken: () => ipcRenderer.invoke('archer:get-api-token'),
  ensureApi: () => ipcRenderer.invoke('archer:ensure-api') as Promise<{ ok: boolean; reason: string }>,
  restartApi: () => ipcRenderer.invoke('archer:restart-api') as Promise<{ ok: boolean; reason: string }>,
  getBrainStatus: () => ipcRenderer.invoke('archer:get-brain-status') as Promise<{
    pythonOk: boolean
    scriptOk: boolean
    portOk: boolean
    readyOk: boolean
    tokenOk: boolean
    owned: boolean
    reason: string
  }>,
  getCrashInfo: () => ipcRenderer.invoke('archer:get-crash-info') as Promise<{
    isCrash: boolean
    reason: string
    crashCount: number
    lastTraceId: string | null
    startedAt: string | null
  } | null>
})
