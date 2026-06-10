import { contextBridge } from 'electron'
import { ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('archerDesktop', {
  version: '1.0.13',
  platform: process.platform,
  pickFiles: () => ipcRenderer.invoke('archer:pick-files'),
  captureScreenshot: () => ipcRenderer.invoke('archer:capture-screenshot'),
  captureWindowScreenshot: () => ipcRenderer.invoke('archer:capture-window-screenshot'),
  listCaptureSources: () => ipcRenderer.invoke('archer:list-capture-sources'),
  captureSource: (sourceId: string) => ipcRenderer.invoke('archer:capture-source', sourceId),
  getApiToken: () => ipcRenderer.invoke('archer:get-api-token'),
  ensureApi: () => ipcRenderer.invoke('archer:ensure-api') as Promise<{ ok: boolean; reason: string }>
})
