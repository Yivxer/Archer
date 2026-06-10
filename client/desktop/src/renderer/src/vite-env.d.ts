/// <reference types="vite/client" />

interface Window {
  archerDesktop?: {
    version: string
    platform: NodeJS.Platform
    pickFiles: () => Promise<Array<{ path: string; name: string; size: number; previewDataUrl?: string }>>
    captureScreenshot: () => Promise<{ path: string; name: string; size: number; previewDataUrl?: string } | null>
    captureWindowScreenshot: () => Promise<{ path: string; name: string; size: number; previewDataUrl?: string } | null>
    listCaptureSources: () => Promise<Array<{ id: string; name: string; kind: 'screen' | 'window'; thumbnailEmpty?: boolean; screenStatus?: string }>>
    captureSource: (sourceId: string) => Promise<{ path: string; name: string; size: number; previewDataUrl?: string } | null>
    getApiToken: () => Promise<string>
    ensureApi: () => Promise<{ ok: boolean; reason: string }>
  }
}
