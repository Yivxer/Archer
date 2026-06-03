import { contextBridge } from 'electron'
import { ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('archerDesktop', {
  version: '1.0.13',
  platform: process.platform,
  pickFiles: () => ipcRenderer.invoke('archer:pick-files'),
  getApiToken: () => ipcRenderer.invoke('archer:get-api-token')
})
