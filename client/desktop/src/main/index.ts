import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import { join } from 'node:path'
import { spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { probeExistingApi } from './apiProcess'

const isDev = !app.isPackaged

// Archer project root — where archer_api.py lives
const ARCHER_ROOT = '/Users/Yivxer/Projects/Archer'
const PYTHON_BIN = join(ARCHER_ROOT, '.venv', 'bin', 'python3')
const API_SCRIPT = join(ARCHER_ROOT, 'archer_api.py')

let apiProcess: ChildProcess | null = null
let desktopApiToken = ''

function getOrCreateDesktopApiToken(): string {
  const tokenDir = join(app.getPath('userData'), 'security')
  const tokenPath = join(tokenDir, 'desktop-api-token')
  try {
    if (existsSync(tokenPath)) {
      const existing = readFileSync(tokenPath, 'utf8').trim()
      if (existing) return existing
    }
    mkdirSync(tokenDir, { recursive: true })
    const token = randomBytes(24).toString('hex')
    writeFileSync(tokenPath, token, { encoding: 'utf8', mode: 0o600 })
    return token
  } catch (error) {
    console.error('[archer_api] Failed to persist desktop token:', error instanceof Error ? error.message : error)
    return randomBytes(24).toString('hex')
  }
}

async function startApiProcess() {
  if (!existsSync(PYTHON_BIN) || !existsSync(API_SCRIPT)) {
    console.log('[archer_api] Python or script not found, skipping auto-start')
    return
  }
  if (apiProcess) return

  desktopApiToken = desktopApiToken || getOrCreateDesktopApiToken()

  if (await probeExistingApi()) {
    console.log('[archer_api] Existing API detected on 127.0.0.1:8765, reusing it')
    return
  }

  apiProcess = spawn(PYTHON_BIN, [API_SCRIPT, '--token', desktopApiToken], {
    cwd: ARCHER_ROOT,
    stdio: 'ignore',
    detached: false
  })

  apiProcess.on('exit', (code) => {
    console.log(`[archer_api] Process exited with code ${code}`)
    apiProcess = null
  })

  apiProcess.on('error', (err) => {
    console.error('[archer_api] Failed to start:', err.message)
    apiProcess = null
  })

  console.log('[archer_api] Started, pid:', apiProcess.pid)
}

function stopApiProcess() {
  if (apiProcess) {
    apiProcess.kill()
    apiProcess = null
  }
}

function isAllowedExternalUrl(rawUrl: string): boolean {
  try {
    const url = new URL(rawUrl)
    return url.protocol === 'https:' || url.protocol === 'mailto:'
  } catch {
    return false
  }
}

function isAllowedAppNavigation(rawUrl: string): boolean {
  try {
    const url = new URL(rawUrl)
    if (url.protocol === 'file:') return true
    if (isDev && process.env.ELECTRON_RENDERER_URL) {
      return url.origin === new URL(process.env.ELECTRON_RENDERER_URL).origin
    }
    return false
  } catch {
    return false
  }
}

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 980,
    minHeight: 680,
    title: 'Archer Desktop',
    backgroundColor: '#0d1219',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 18, y: 18 },
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowedExternalUrl(url)) shell.openExternal(url)
    return { action: 'deny' }
  })

  mainWindow.webContents.on('will-navigate', (event, url) => {
    const currentUrl = mainWindow.webContents.getURL()
    if (url !== currentUrl && !isAllowedAppNavigation(url)) {
      event.preventDefault()
      if (isAllowedExternalUrl(url)) shell.openExternal(url)
    }
  })

  if (isDev && process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

ipcMain.handle('archer:pick-files', async () => {
  const result = await dialog.showOpenDialog({
    title: '引用本地文件',
    properties: ['openFile', 'multiSelections'],
    filters: [
      { name: 'Text files', extensions: ['md', 'txt', 'json', 'toml', 'yaml', 'yml', 'py', 'ts', 'tsx', 'js', 'jsx', 'css', 'html', 'csv', 'log'] },
      { name: 'All files', extensions: ['*'] }
    ]
  })
  if (result.canceled) return []
  const { statSync } = await import('node:fs')
  return result.filePaths.map((path) => {
    let size = 0
    try {
      size = statSync(path).size
    } catch {
      size = 0
    }
    return {
      path,
      name: path.split(/[\\/]/).pop() || path,
      size
    }
  })
})

ipcMain.handle('archer:get-api-token', async () => {
  desktopApiToken = desktopApiToken || getOrCreateDesktopApiToken()
  return desktopApiToken
})

app.whenReady().then(async () => {
  app.setName('Archer Desktop')
  desktopApiToken = getOrCreateDesktopApiToken()
  await startApiProcess()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('before-quit', () => {
  stopApiProcess()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
