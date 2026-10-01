import { spawn } from 'node:child_process'
import { lstat, readFile, realpath, open, unlink, mkdir } from 'node:fs/promises'
import type { FileHandle } from 'node:fs/promises'
import { isAbsolute, join } from 'node:path'
import { createConnection } from 'node:net'

type Probe = 'core' | 'absent' | 'occupied'
export interface LaunchResult { state: 'ready' | 'failed'; code: string; started: boolean }

export async function probeCore(baseUrl: string): Promise<Probe> {
  const url = new URL(baseUrl)
  // Launcher supports only the fixed local installation, never arbitrary hosts/ports.
  if (url.origin !== 'http://127.0.0.1:7860' || url.pathname !== '/') return 'occupied'
  const listening = await new Promise<boolean>(resolve => {
    const socket = createConnection({ host: '127.0.0.1', port: 7860 })
    const done = (value: boolean) => { socket.destroy(); resolve(value) }
    socket.setTimeout(500, () => done(false))
    socket.once('connect', () => done(true)); socket.once('error', () => done(false))
  })
  if (!listening) return 'absent'
  try {
    const response = await fetch(`${url.origin}/api/v1/health`, { signal: AbortSignal.timeout(1500), redirect: 'error' })
    if (!response.ok || Number(response.headers.get('content-length') || 0) > 4096) return 'occupied'
    const reader = response.body?.getReader()
    if (!reader) return 'occupied'
    let text = ''; let size = 0
    try {
      for (;;) {
        const { value, done } = await reader.read(); if (done) break
        size += value.byteLength; if (size > 4096) return 'occupied'
        text += new TextDecoder().decode(value)
      }
    } finally { await reader.cancel() }
    const value = JSON.parse(text)
    return value.service === 'hku-agents' && value.status === 'ok' && value.mode === 'local-first' ? 'core' : 'occupied'
  } catch { return 'occupied' }
}

// No renderer input reaches these options; injection is only for deterministic tests.
export function createCoreLauncher(baseUrl: string, options: {
  descriptor?: string; platform?: string; probe?: () => Promise<Probe>;
  launch?: (python: string, app: string, root: string) => Promise<void>;
  wait?: () => Promise<void>; attempts?: number;
} = {}) {
  let pending: Promise<LaunchResult> | undefined
  let childExited = false
  const descriptor = options.descriptor || join(process.env.USERPROFILE || '', '.hku-agents', 'core-launch-v1.json')
  const probe = options.probe || (() => probeCore(baseUrl))
  const wait = options.wait || (() => new Promise<void>(resolve => setTimeout(resolve, 1000)))
  const launch = options.launch || (async (python, app, root) => {
    // Windows console-less Python may expose None streams for ignored stdio;
    // Uvicorn's logging initialization needs real stdout/stderr handles.
    const logDir = join(root, '.cache', 'desktop-core')
    await mkdir(logDir, { recursive: true })
    if ((await lstat(logDir)).isSymbolicLink()) throw new Error('Invalid local log directory')
    const handles: FileHandle[] = []
    try {
      for (const name of ['stdout.log', 'stderr.log']) {
        const target = join(logDir, name)
        const item = await lstat(target).catch(error => { if (error.code === 'ENOENT') return null; throw error })
        if (item && (!item.isFile() || item.isSymbolicLink())) throw new Error('Invalid local log file')
        handles.push(await open(target, 'w', 0o600))
      }
      await new Promise<void>((resolve, reject) => {
    const child = spawn(python, [app], { cwd: root, windowsHide: true, detached: false, stdio: ['ignore', handles[0]!.fd, handles[1]!.fd],
      env: { ...process.env, APP_HOST: '127.0.0.1', APP_PORT: '7860', API_BASE_URL: baseUrl,
        LIBRARY_BOOKING_WRITES_ENABLED: 'false', PYTHONUNBUFFERED: '1' } })
    child.once('exit', () => { childExited = true })
    child.once('error', reject); child.once('spawn', () => { child.unref(); resolve() })
      })
    } finally { for (const handle of handles) await handle.close() }
  })
  async function start(): Promise<LaunchResult> {
    if ((options.platform || process.platform) !== 'win32' || baseUrl !== 'http://127.0.0.1:7860')
      return { state: 'failed', code: 'LAUNCH_CONFIGURATION_UNSUPPORTED', started: false }
    const before = await probe()
    if (before === 'core') return { state: 'ready', code: 'CORE_ALREADY_RUNNING', started: false }
    if (before === 'occupied') return { state: 'failed', code: 'CORE_PORT_OCCUPIED', started: false }
    let root: string
    try {
      const stat = await lstat(descriptor)
      if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 4096) throw new Error()
      const saved = JSON.parse(await readFile(descriptor, 'utf8'))
      if (saved.version !== 1 || Object.keys(saved).sort().join(',') !== 'root,version' ||
          typeof saved.root !== 'string' || !isAbsolute(saved.root)) throw new Error()
      root = await realpath(saved.root)
      for (const target of [join(root, 'project', 'app.py'), join(root, '.venv', 'Scripts', 'pythonw.exe')]) {
        const item = await lstat(target)
        if (!item.isFile() || item.isSymbolicLink()) throw new Error()
      }
    } catch { return { state: 'failed', code: 'CORE_INSTALLATION_NOT_REGISTERED', started: false } }
    let lock
    const lockPath = `${descriptor}.lock`
    try { lock = await open(lockPath, 'wx', 0o600) }
    catch { return { state: 'failed', code: 'CORE_START_IN_PROGRESS', started: false } }
    let started = false
    try {
      // Recheck under the shared lock, before creating any process.
      const again = await probe()
      if (again === 'core') return { state: 'ready', code: 'CORE_ALREADY_RUNNING', started: false }
      if (again === 'occupied') return { state: 'failed', code: 'CORE_PORT_OCCUPIED', started: false }
      childExited = false
      await launch(join(root, '.venv', 'Scripts', 'pythonw.exe'), join(root, 'project', 'app.py'), root)
      started = true
      for (let attempt = 0; attempt < (options.attempts ?? 40); attempt++) {
        await wait()
        if (await probe() === 'core') return { state: 'ready', code: 'CORE_STARTED', started: true }
        if (childExited) return { state: 'failed', code: 'CORE_START_FAILED', started }
      }
      return { state: 'failed', code: 'CORE_START_TIMEOUT', started }
    } catch { return { state: 'failed', code: 'CORE_START_FAILED', started } }
    finally { await lock.close(); await unlink(lockPath).catch(() => {}) }
  }
  return { ensureStarted(): Promise<LaunchResult> {
    pending ||= start().finally(() => { pending = undefined })
    return pending
  } }
}
