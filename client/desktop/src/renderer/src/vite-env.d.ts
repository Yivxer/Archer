/// <reference types="vite/client" />

interface Window {
  archerDesktop?: {
    version: string
    platform: NodeJS.Platform
    pickFiles: () => Promise<Array<{ path: string; name: string; size: number }>>
    getApiToken: () => Promise<string>
  }
}
