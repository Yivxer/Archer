/// <reference types="vite/client" />

interface Window {
  archerDesktop?: {
    version: string
    platform: NodeJS.Platform
    pickFiles: () => Promise<Array<{ path: string; name: string; size: number; previewDataUrl?: string }>>
    readFileReferences: (refs: Array<{ path: string; name?: string; size?: number }>) => Promise<Array<{
      path: string
      name: string
      size: number
      ok: boolean
      content?: string
      contentChars?: number
      truncated?: boolean
      error?: string
    }>>
    captureScreenshot: () => Promise<{ path: string; name: string; size: number; previewDataUrl?: string } | null>
    captureWindowScreenshot: () => Promise<{ path: string; name: string; size: number; previewDataUrl?: string } | null>
    listCaptureSources: () => Promise<Array<{ id: string; name: string; kind: 'screen' | 'window'; thumbnailEmpty?: boolean; screenStatus?: string }>>
    captureSource: (sourceId: string) => Promise<{ path: string; name: string; size: number; previewDataUrl?: string } | null>
    getApiToken: () => Promise<string>
    ensureApi: () => Promise<{ ok: boolean; reason: string }>
    restartApi: () => Promise<{ ok: boolean; reason: string }>
    getBrainStatus: () => Promise<{
      pythonOk: boolean
      scriptOk: boolean
      portOk: boolean
      readyOk: boolean
      tokenOk: boolean
      owned: boolean
      reason: string
    }>
    getCrashInfo: () => Promise<{
      isCrash: boolean
      reason: string
      crashCount: number
      lastTraceId: string | null
      startedAt: string | null
    } | null>
  }
}
