import { app, BrowserWindow, desktopCapturer, dialog, ipcMain, Menu, nativeImage, shell, systemPreferences } from 'electron'
import { join } from 'node:path'
import { spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { execFile } from 'node:child_process'
import { probeExistingApi, verifyApiToken, waitForHealthyApi } from './apiProcess'

const isDev = !app.isPackaged

// Archer project root — where archer_api.py lives
const ARCHER_ROOT = '/Users/Yivxer/Projects/Archer'
const PYTHON_BIN = join(ARCHER_ROOT, '.venv', 'bin', 'python3')
const API_SCRIPT = join(ARCHER_ROOT, 'archer_api.py')

let apiProcess: ChildProcess | null = null
let desktopApiToken = ''
let ensureApiPromise: Promise<{ ok: boolean; reason: string }> | null = null
let apiWatchTimer: ReturnType<typeof setInterval> | null = null

type ApiEnsureResult = { ok: boolean; reason: string }

const PREVIEWABLE_IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tiff', '.tif', '.heic'])

function screenshotFilePath(prefix: string): string {
  const screenshotDir = join(app.getPath('userData'), 'screenshots')
  mkdirSync(screenshotDir, { recursive: true })
  return join(screenshotDir, `${prefix}-${new Date().toISOString().replace(/[:.]/g, '-')}.png`)
}

function imagePreviewDataUrl(path: string): string | undefined {
  const ext = path.slice(path.lastIndexOf('.')).toLowerCase()
  if (!PREVIEWABLE_IMAGE_EXTENSIONS.has(ext)) return undefined
  const image = nativeImage.createFromPath(path)
  if (image.isEmpty()) return undefined
  const size = image.getSize()
  const longestEdge = Math.max(size.width, size.height)
  const scale = longestEdge > 320 ? 320 / longestEdge : 1
  const preview = scale < 1
    ? image.resize({
      width: Math.max(1, Math.round(size.width * scale)),
      height: Math.max(1, Math.round(size.height * scale)),
      quality: 'good'
    })
    : image
  return preview.toDataURL()
}

function fileRefFromPath(path: string) {
  const size = statSync(path).size
  if (size === 0) return null
  return {
    path,
    name: path.split(/[\\/]/).pop() || 'screenshot.png',
    size,
    previewDataUrl: imagePreviewDataUrl(path)
  }
}

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

function attachApiProcessHandlers(child: ChildProcess) {
  child.on('exit', (code) => {
    console.log(`[archer_api] Process exited with code ${code}`)
    if (apiProcess === child) apiProcess = null
    setTimeout(() => {
      void ensureApiProcess()
    }, 1500)
  })

  child.on('error', (err) => {
    console.error('[archer_api] Failed to start:', err.message)
    if (apiProcess === child) apiProcess = null
  })
}

function spawnApiProcess(): ChildProcess | null {
  desktopApiToken = desktopApiToken || getOrCreateDesktopApiToken()
  const child = spawn(PYTHON_BIN, [API_SCRIPT, '--token', desktopApiToken], {
    cwd: ARCHER_ROOT,
    stdio: 'ignore',
    detached: false,
  })
  attachApiProcessHandlers(child)
  console.log('[archer_api] Started, pid:', child.pid)
  return child
}

async function ensureApiProcess(): Promise<ApiEnsureResult> {
  if (ensureApiPromise) return ensureApiPromise

  ensureApiPromise = (async () => {
    if (!existsSync(PYTHON_BIN) || !existsSync(API_SCRIPT)) {
      console.log('[archer_api] Python or script not found, cannot auto-start')
      return { ok: false, reason: 'missing_python' }
    }

    desktopApiToken = desktopApiToken || getOrCreateDesktopApiToken()

    if (apiProcess && apiProcess.pid && !apiProcess.killed) {
      if (await verifyApiToken(fetch, desktopApiToken)) {
        return { ok: true, reason: 'owned' }
      }
    }

    if (await probeExistingApi()) {
      if (await verifyApiToken(fetch, desktopApiToken)) {
        console.log('[archer_api] Reusing healthy API on 127.0.0.1:8765')
        return { ok: true, reason: 'reused' }
      }
      console.warn('[archer_api] Port 8765 is up but token mismatch; starting a fresh API is not attempted while port is busy')
      return { ok: false, reason: 'token_mismatch' }
    }

    apiProcess = spawnApiProcess()
    if (!apiProcess) {
      return { ok: false, reason: 'spawn_failed' }
    }

    const healthy = await waitForHealthyApi(fetch)
    if (!healthy) {
      console.error('[archer_api] API did not become healthy in time')
      return { ok: false, reason: 'spawn_failed' }
    }

    if (!(await verifyApiToken(fetch, desktopApiToken))) {
      return { ok: false, reason: 'token_mismatch' }
    }

    return { ok: true, reason: 'started' }
  })()

  try {
    return await ensureApiPromise
  } finally {
    ensureApiPromise = null
  }
}

function startApiWatchdog() {
  if (apiWatchTimer) return
  apiWatchTimer = setInterval(() => {
    void ensureApiProcess()
  }, 45_000)
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

type WindowOptions = {
  width?: number
  height?: number
}

function createWindow(options: WindowOptions = {}): BrowserWindow {
  const mainWindow = new BrowserWindow({
    width: options.width ?? 1280,
    height: options.height ?? 820,
    minWidth: 360,
    minHeight: 640,
    title: 'Archer Desktop',
    backgroundColor: '#0d1219',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 14 },
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

  return mainWindow
}

function buildAppMenu(): void {
  const isMac = process.platform === 'darwin'
  const template: Electron.MenuItemConstructorOptions[] = [
    ...(isMac
      ? [{
          label: app.name,
          submenu: [
            { role: 'about' as const },
            { type: 'separator' as const },
            { role: 'services' as const },
            { type: 'separator' as const },
            { role: 'hide' as const },
            { role: 'hideOthers' as const },
            { role: 'unhide' as const },
            { type: 'separator' as const },
            { role: 'quit' as const }
          ]
        }]
      : []),
    {
      label: '文件',
      submenu: [
        {
          label: '新建窗口',
          accelerator: 'CmdOrCtrl+Shift+N',
          click: () => {
            createWindow({ width: 405, height: 720 })
          }
        },
        { type: 'separator' },
        isMac ? { role: 'close' } : { role: 'quit' }
      ]
    },
    {
      label: '编辑',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' }
      ]
    },
    {
      label: '视图',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      label: '窗口',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        { type: 'separator' },
        { role: 'front' }
      ]
    }
  ]

  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
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
    let previewDataUrl: string | undefined
    try {
      size = statSync(path).size
      previewDataUrl = imagePreviewDataUrl(path)
    } catch {
      size = 0
    }
    return {
      path,
      name: path.split(/[\\/]/).pop() || path,
      size,
      previewDataUrl
    }
  })
})

ipcMain.handle('archer:capture-screenshot', async () => {
  const screenshotPath = screenshotFilePath('archer-screenshot')

  await new Promise<void>((resolve, reject) => {
    execFile('/usr/sbin/screencapture', ['-i', screenshotPath], (error) => {
      if (error) {
        reject(error)
        return
      }
      resolve()
    })
  })

  if (!existsSync(screenshotPath)) return null
  return fileRefFromPath(screenshotPath)
})

ipcMain.handle('archer:capture-window-screenshot', async () => {
  const screenshotPath = screenshotFilePath('archer-window')

  await new Promise<void>((resolve, reject) => {
    execFile('/usr/sbin/screencapture', ['-i', '-w', screenshotPath], (error) => {
      if (error) {
        reject(error)
        return
      }
      resolve()
    })
  })

  if (!existsSync(screenshotPath)) return null
  return fileRefFromPath(screenshotPath)
})

ipcMain.handle('archer:list-capture-sources', async () => {
  const screenStatus = systemPreferences.getMediaAccessStatus('screen')
  const sources = await desktopCapturer.getSources({
    types: ['screen', 'window'],
    thumbnailSize: { width: 320, height: 200 },
    fetchWindowIcons: true
  })
  return sources
    .filter((source) => !source.name.toLowerCase().includes('archer'))
    .slice(0, 12)
    .map((source) => ({
      id: source.id,
      name: source.name,
      kind: source.id.startsWith('screen') ? 'screen' : 'window',
      thumbnailEmpty: source.thumbnail.isEmpty(),
      screenStatus
    }))
})

ipcMain.handle('archer:capture-source', async (_event, sourceId: string) => {
  const screenStatus = systemPreferences.getMediaAccessStatus('screen')
  if (screenStatus !== 'granted') {
    throw new Error(`screen:${screenStatus}`)
  }
  const sources = await desktopCapturer.getSources({
    types: ['screen', 'window'],
    thumbnailSize: { width: 1920, height: 1200 },
    fetchWindowIcons: false
  })
  const source = sources.find((item) => item.id === sourceId)
  if (!source || source.thumbnail.isEmpty()) return null

  const screenshotPath = screenshotFilePath(source.id.startsWith('screen') ? 'archer-screen' : 'archer-window')
  writeFileSync(screenshotPath, source.thumbnail.toPNG())
  return fileRefFromPath(screenshotPath)
})

ipcMain.handle('archer:get-api-token', async () => {
  desktopApiToken = desktopApiToken || getOrCreateDesktopApiToken()
  return desktopApiToken
})

ipcMain.handle('archer:ensure-api', async () => ensureApiProcess())

app.whenReady().then(async () => {
  app.setName('Archer Desktop')
  buildAppMenu()
  desktopApiToken = getOrCreateDesktopApiToken()
  await ensureApiProcess()
  startApiWatchdog()
  createWindow()

  app.on('activate', () => {
    void ensureApiProcess()
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('before-quit', () => {
  stopApiProcess()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
