import { app, BrowserWindow, desktopCapturer, dialog, ipcMain, Menu, nativeImage, shell, systemPreferences } from 'electron'
import { join } from 'node:path'
import { env as processEnv } from 'node:process'
import { spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import { appendFileSync, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { execFile } from 'node:child_process'
import { apiRetryDelayMs, brainStatusReason, probeExistingApi, probeReadyApi, reclaimApiPort, resolveApiLaunchPaths, verifyApiToken, waitForReadyApi } from './apiProcess'

const isDev = !app.isPackaged

let desktopLogPath = ''
const originalConsole = {
  log: console.log.bind(console),
  warn: console.warn.bind(console),
  error: console.error.bind(console),
}

function desktopLogFilePath(): string {
  if (!desktopLogPath) {
    const logDir = join(app.getPath('userData'), 'logs')
    mkdirSync(logDir, { recursive: true })
    desktopLogPath = join(logDir, 'desktop-main.log')
  }
  return desktopLogPath
}

function formatLogValue(value: unknown): string {
  if (value instanceof Error) return value.stack || value.message
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function appendDesktopLog(level: string, values: unknown[]): void {
  try {
    const line = values.map(formatLogValue).join(' ')
    appendFileSync(desktopLogFilePath(), `[${new Date().toISOString()}] [${level}] ${line}\n`, 'utf8')
  } catch {
    // Logging must never become the reason Archer fails to start.
  }
}

function installDesktopFileLogging(): void {
  console.log = (...values: unknown[]) => {
    appendDesktopLog('info', values)
    originalConsole.log(...values)
  }
  console.warn = (...values: unknown[]) => {
    appendDesktopLog('warn', values)
    originalConsole.warn(...values)
  }
  console.error = (...values: unknown[]) => {
    appendDesktopLog('error', values)
    originalConsole.error(...values)
  }
}

installDesktopFileLogging()

// Prevent main process crash on unhandled promise rejections or exceptions.
process.on('unhandledRejection', (reason) => {
  console.error('[archer_main] Unhandled rejection:', reason)
})
process.on('uncaughtException', (err) => {
  console.error('[archer_main] Uncaught exception:', err)
})

process.on('warning', (warning) => {
  console.warn('[archer_main] Process warning:', warning)
})

// Archer project root — can be overridden for local development or packaging smoke.
const API_PATHS = resolveApiLaunchPaths(processEnv)
const ARCHER_ROOT = API_PATHS.archerRoot
const PYTHON_BIN = API_PATHS.pythonBin
const API_SCRIPT = API_PATHS.apiScript

let apiProcess: ChildProcess | null = null
let desktopApiToken = ''
let ensureApiPromise: Promise<{ ok: boolean; reason: string }> | null = null
let apiWatchTimer: ReturnType<typeof setInterval> | null = null
let apiRestartTimer: ReturnType<typeof setTimeout> | null = null
let apiRestartAttempt = 0

// L0.4: 上次启动时的崩溃信息 (从 /active-context 读)
type CrashInfo = {
  isCrash: boolean
  reason: string
  crashCount: number
  lastTraceId: string | null
  startedAt: string | null
}
let lastStartupCrashInfo: CrashInfo | null = null

type ApiEnsureResult = { ok: boolean; reason: string }
const API_WATCHDOG_INTERVAL_MS = 5_000

const PREVIEWABLE_IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tiff', '.tif', '.heic'])
const READABLE_TEXT_EXTENSIONS = new Set(['.md', '.txt', '.json', '.toml', '.yaml', '.yml', '.py', '.ts', '.tsx', '.js', '.jsx', '.css', '.html', '.csv', '.log'])
const FILE_REFERENCE_LIMIT = 6000

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

function readableFileReference(ref: { path?: unknown; name?: unknown; size?: unknown }) {
  const path = String(ref.path || '').trim()
  if (!path) return null
  const name = String(ref.name || '').trim() || path.split(/[\\/]/).pop() || path
  const suffix = path.slice(path.lastIndexOf('.')).toLowerCase()
  try {
    const stat = statSync(path)
    const size = stat.size
    if (!stat.isFile()) {
      return { path, name, size, ok: false, error: '不是可读取文件' }
    }
    if (suffix && !READABLE_TEXT_EXTENSIONS.has(suffix)) {
      return { path, name, size, ok: false, error: '暂不支持预读非文本附件' }
    }
    const raw = readFileSync(path, 'utf8')
    if (raw.slice(0, 2048).includes('\x00')) {
      return { path, name, size, ok: false, error: '疑似二进制文件' }
    }
    const content = raw.slice(0, FILE_REFERENCE_LIMIT)
    return {
      path,
      name,
      size,
      ok: true,
      content,
      contentChars: content.length,
      truncated: raw.length > content.length
    }
  } catch (error) {
    return {
      path,
      name,
      size: typeof ref.size === 'number' ? ref.size : 0,
      ok: false,
      error: error instanceof Error ? error.message : '读取失败'
    }
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
  child.stdout?.on('data', (chunk: Buffer) => {
    console.log('[archer_api:stdout]', chunk.toString('utf8').trimEnd().slice(0, 4000))
  })

  child.stderr?.on('data', (chunk: Buffer) => {
    console.error('[archer_api:stderr]', chunk.toString('utf8').trimEnd().slice(0, 4000))
  })

  child.on('exit', (code, signal) => {
    console.log(`[archer_api] Process exited with code ${code ?? 'null'} signal ${signal ?? 'null'}`)
    if (apiProcess === child) apiProcess = null
    scheduleApiEnsure('process_exit')
  })

  child.on('error', (err) => {
    console.error('[archer_api] Failed to start:', err.message)
    if (apiProcess === child) apiProcess = null
    // spawn 失败也要调度重启，否则 API 永远不会恢复
    scheduleApiEnsure('process_error')
  })
}

function clearScheduledApiRestart() {
  if (apiRestartTimer) {
    clearTimeout(apiRestartTimer)
    apiRestartTimer = null
  }
}

function shouldRetryApiEnsure(reason: string): boolean {
  return reason !== 'missing_python' && reason !== 'missing_script'
}

function scheduleApiEnsure(reason: string) {
  if (apiRestartTimer) return
  const delayMs = apiRetryDelayMs(apiRestartAttempt)
  console.log(`[archer_api] Scheduling API ensure in ${delayMs}ms (${reason})`)
  apiRestartTimer = setTimeout(() => {
    apiRestartTimer = null
    void ensureApiProcess().then((result) => {
      if (result.ok) {
        apiRestartAttempt = 0
        return
      }
      if (!shouldRetryApiEnsure(result.reason)) return
      apiRestartAttempt += 1
      scheduleApiEnsure(result.reason)
    }).catch((err) => {
      console.error('[archer_api] ensureApiProcess rejected:', err)
    })
  }, delayMs)
}

function apiChildEnv(): NodeJS.ProcessEnv {
  const pathParts = [
    '/opt/homebrew/bin',
    '/opt/homebrew/sbin',
    '/usr/local/bin',
    processEnv.PATH || '',
  ]
  return {
    ...processEnv,
    PATH: pathParts.filter(Boolean).join(':'),
    ARCHER_ROOT: ARCHER_ROOT,
    ARCHER_DESKTOP_PID: String(process.pid),
  }
}

function spawnApiProcess(): ChildProcess | null {
  desktopApiToken = desktopApiToken || getOrCreateDesktopApiToken()
  const child = spawn(PYTHON_BIN, [API_SCRIPT, '--port', '8765', '--token', desktopApiToken], {
    cwd: ARCHER_ROOT,
    env: apiChildEnv(),
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: false,
  })
  attachApiProcessHandlers(child)
  console.log('[archer_api] Started, pid:', child.pid)
  return child
}

/** L0.4: 从 /active-context 读崩溃信息, 存到 lastStartupCrashInfo. */
async function fetchActiveContext(): Promise<void> {
  if (!desktopApiToken) return
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 2000)
  try {
    const response = await fetch('http://127.0.0.1:8765/active-context', {
      signal: controller.signal,
      headers: { Authorization: `Bearer ${desktopApiToken}` },
    })
    if (!response.ok) return
    const data = await response.json() as {
      ok?: boolean
      is_crash?: boolean
      crash_reason?: string
      crash_count?: number
      active_context?: { last_trace_id?: string | null; started_at?: string | null }
    }
    if (!data.ok) return
    lastStartupCrashInfo = {
      isCrash: Boolean(data.is_crash),
      reason: String(data.crash_reason || 'unknown'),
      crashCount: Number(data.crash_count || 0),
      lastTraceId: data.active_context?.last_trace_id ?? null,
      startedAt: data.active_context?.started_at ?? null,
    }
    if (lastStartupCrashInfo.isCrash) {
      console.warn(
        `[archer_api] Crash detected: reason=${lastStartupCrashInfo.reason} count=${lastStartupCrashInfo.crashCount}`
      )
    }
  } catch (err) {
    console.warn('[archer_api] fetchActiveContext failed:', err)
  } finally {
    clearTimeout(timeout)
  }
}

async function ensureApiProcess(): Promise<ApiEnsureResult> {
  if (ensureApiPromise) return ensureApiPromise

  ensureApiPromise = (async () => {
    if (!existsSync(PYTHON_BIN)) {
      console.log('[archer_api] Python not found, cannot auto-start')
      return { ok: false, reason: 'missing_python' }
    }
    if (!existsSync(API_SCRIPT)) {
      console.log('[archer_api] API script not found, cannot auto-start')
      return { ok: false, reason: 'missing_script' }
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
      console.warn('[archer_api] Port 8765 token mismatch — reclaiming port and restarting')
      if (apiProcess && apiProcess.pid && !apiProcess.killed) {
        apiProcess.kill('SIGTERM')
        apiProcess = null
      }
      await reclaimApiPort(8765)
    }

    apiProcess = spawnApiProcess()
    if (!apiProcess) {
      return { ok: false, reason: 'spawn_failed' }
    }

    const ready = await waitForReadyApi(fetch, 'http://127.0.0.1:8765', 15000, 300)
    if (!ready) {
      console.error('[archer_api] API did not become ready in time')
      return { ok: false, reason: 'spawn_failed' }
    }

    if (!(await verifyApiToken(fetch, desktopApiToken))) {
      return { ok: false, reason: 'token_mismatch' }
    }

    return { ok: true, reason: 'started' }
  })()

  try {
    const result = await ensureApiPromise
    if (result.ok) {
      apiRestartAttempt = 0
      clearScheduledApiRestart()
      // L0.4: API 就绪后读 active_context 崩溃信息
      void fetchActiveContext()
    }
    return result
  } finally {
    ensureApiPromise = null
  }
}

function startApiWatchdog() {
  if (apiWatchTimer) return
  apiWatchTimer = setInterval(() => {
    void probeReadyApi(fetch, 'http://127.0.0.1:8765', 800).then((ready) => {
      if (ready) {
        apiRestartAttempt = 0
        return
      }
      scheduleApiEnsure('heartbeat_not_ready')
    })
  }, API_WATCHDOG_INTERVAL_MS)
}

function stopApiProcess() {
  if (apiProcess) {
    apiProcess.kill()
    apiProcess = null
  }
}

async function restartApiProcess(): Promise<ApiEnsureResult> {
  clearScheduledApiRestart()
  apiRestartAttempt = 0
  stopApiProcess()
  await reclaimApiPort(8765)
  return ensureApiProcess()
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
  let reloadedAfterRendererGone = false

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

  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    console.error('[archer_renderer] render-process-gone:', details)
    if (mainWindow.isDestroyed() || reloadedAfterRendererGone) return
    reloadedAfterRendererGone = true
    setTimeout(() => {
      if (!mainWindow.isDestroyed()) mainWindow.reload()
    }, 500)
  })

  mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    console.error('[archer_renderer] did-fail-load:', { errorCode, errorDescription, validatedURL })
  })

  mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    if (level >= 2) {
      console.warn('[archer_renderer:console]', { level, message, line, sourceId })
    }
  })

  mainWindow.on('unresponsive', () => {
    console.error('[archer_window] unresponsive')
  })

  mainWindow.on('responsive', () => {
    console.log('[archer_window] responsive')
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

ipcMain.handle('archer:read-file-references', async (_event, refs: Array<{ path?: unknown; name?: unknown; size?: unknown }>) => {
  if (!Array.isArray(refs)) return []
  return refs.slice(0, 5).map((ref) => readableFileReference(ref)).filter(Boolean)
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

ipcMain.handle('archer:restart-api', async () => restartApiProcess())

ipcMain.handle('archer:get-brain-status', async () => {
  desktopApiToken = desktopApiToken || getOrCreateDesktopApiToken()
  const pythonOk = existsSync(PYTHON_BIN)
  const scriptOk = existsSync(API_SCRIPT)
  const portOk = await probeExistingApi()
  const readyOk = portOk ? await probeReadyApi(fetch) : false
  const tokenOk = portOk && readyOk ? await verifyApiToken(fetch, desktopApiToken) : false
  const owned = Boolean(apiProcess && apiProcess.pid && !apiProcess.killed)
  const reason = brainStatusReason({ pythonOk, scriptOk, portOk, readyOk, tokenOk, owned })
  return { pythonOk, scriptOk, portOk, readyOk, tokenOk, owned, reason }
})

ipcMain.handle('archer:get-crash-info', async () => {
  return lastStartupCrashInfo
})

// Single instance lock — prevents two Desktop instances from fighting over the Python API port.
// When a new instance launches (e.g. after DMG update), it focuses the existing window and quits itself.
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const windows = BrowserWindow.getAllWindows()
    if (windows.length > 0) {
      const win = windows[0]
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })

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
}
