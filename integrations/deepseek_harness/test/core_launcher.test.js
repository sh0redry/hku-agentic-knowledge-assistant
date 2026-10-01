import assert from 'node:assert/strict'
import test from 'node:test'
import { mkdtemp, mkdir, writeFile, rm, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { createCoreLauncher } from '../lib/core_launcher.js'

const baseUrl = 'http://127.0.0.1:7860'
test('launcher reuses Core, refuses unrelated listener and unsupported configurations', async () => {
  for (const [probe, code] of [['core', 'CORE_ALREADY_RUNNING'], ['occupied', 'CORE_PORT_OCCUPIED']]) {
    const launcher = createCoreLauncher(baseUrl, { platform: 'win32', probe: async () => probe,
      launch: async () => { throw new Error('must not spawn') } })
    assert.equal((await launcher.ensureStarted()).code, code)
  }
  assert.equal((await createCoreLauncher('http://127.0.0.1:9999', { platform: 'win32' }).ensureStarted()).code,
    'LAUNCH_CONFIGURATION_UNSUPPORTED')
})

test('registered fixed paths launch once, concurrent clicks coalesce; lock blocks other Hosts', async () => {
  const root = await mkdtemp(join(tmpdir(), 'hku-launch-test-'))
  try {
    await mkdir(join(root, 'project')); await mkdir(join(root, '.venv', 'Scripts'), { recursive: true })
    await writeFile(join(root, 'project', 'app.py'), '# synthetic fixture')
    await writeFile(join(root, '.venv', 'Scripts', 'pythonw.exe'), 'synthetic fixture')
    const descriptor = join(root, 'launch.json')
    await writeFile(descriptor, JSON.stringify({ version: 1, root }))
    let calls = 0; let running = false
    const options = { platform: 'win32', descriptor, wait: async () => {}, attempts: 2,
      probe: async () => running ? 'core' : 'absent',
      launch: async (python, app, cwd) => {
        calls++; assert.equal(python, join(root, '.venv', 'Scripts', 'pythonw.exe'))
        assert.equal(app, join(root, 'project', 'app.py')); assert.equal(cwd, root); running = true
      } }
    const launcher = createCoreLauncher(baseUrl, options)
    const results = await Promise.all([launcher.ensureStarted(), launcher.ensureStarted()])
    assert.equal(calls, 1); assert.equal(results[0].code, 'CORE_STARTED')
    assert.equal((await launcher.ensureStarted()).started, false)
    running = false
    await writeFile(`${descriptor}.lock`, 'another Host')
    assert.equal((await launcher.ensureStarted()).code, 'CORE_START_IN_PROGRESS')
    assert.equal(await readFile(`${descriptor}.lock`, 'utf8'), 'another Host')
    await rm(`${descriptor}.lock`)
    const timeout = createCoreLauncher(baseUrl, { ...options, launch: async () => {}, probe: async () => 'absent' })
    assert.equal((await timeout.ensureStarted()).code, 'CORE_START_TIMEOUT')
    await writeFile(descriptor, JSON.stringify({ version: 1, root, args: ['arbitrary'] }))
    assert.equal((await launcher.ensureStarted()).code, 'CORE_INSTALLATION_NOT_REGISTERED')
  } finally { await rm(root, { recursive: true, force: true }) }
})
