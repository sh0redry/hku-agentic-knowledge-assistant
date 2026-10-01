import assert from 'node:assert/strict'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { once } from 'node:events'
import http from 'node:http'
import test from 'node:test'
import { readLocalIntegrationToken } from '../lib/local_credentials.js'
import { HKUAgentsClient } from '../lib/client.js'

test('credential reader binds origin, reloads rotation, and rejects malformed files', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'hku-credential-test-'))
  const path = join(directory, 'connection.json')
  const origin = 'http://127.0.0.1:7860'
  const decrypt = async ciphertext => JSON.stringify({ base_url: origin, token: ciphertext === 'AAAA' ? 'a'.repeat(40) : 'b'.repeat(40) })
  try {
    assert.equal(await readLocalIntegrationToken(origin, { path, decrypt }), null)
    await writeFile(path, JSON.stringify({ version: 1, integration: 'AAAA' }))
    assert.equal(await readLocalIntegrationToken(origin, { path, decrypt }), 'a'.repeat(40))
    assert.equal(await readLocalIntegrationToken('http://127.0.0.1:9999', { path, decrypt }), null)
    await writeFile(path, JSON.stringify({ version: 1, integration: 'BBBB' }))
    assert.equal(await readLocalIntegrationToken(origin, { path, decrypt }), 'b'.repeat(40))
    await writeFile(path, JSON.stringify({ version: 1, integration: 'bad!' }))
    await assert.rejects(readLocalIntegrationToken(origin, { path, decrypt }))
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test('Windows Core publication authenticates a Host call without an environment token', { skip: process.platform !== 'win32' }, async () => {
  const directory = await mkdtemp(join(tmpdir(), 'hku-dpapi-test-'))
  const previousProfile = process.env.USERPROFILE
  const previousToken = process.env.INTEGRATION_API_TOKEN
  const token = 'synthetic-test-integration-' + 'x'.repeat(32)
  const server = http.createServer((request, response) => {
    assert.equal(request.headers.authorization, `Bearer ${token}`)
    assert.equal(request.url, '/api/v1/integration/connection/connect')
    response.setHeader('content-type', 'application/json')
    response.end(JSON.stringify({ api_version: 'v1', ok: true, read_only: true, correlation_id: 'test-id', result: { read_only: true }, task: null, error: null }))
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  try {
    process.env.USERPROFILE = directory
    delete process.env.INTEGRATION_API_TOKEN
    const origin = `http://127.0.0.1:${server.address().port}`
    const python = fileURLToPath(new URL('../../../.venv/Scripts/python.exe', import.meta.url))
    const project = fileURLToPath(new URL('../../../project', import.meta.url))
    const script = 'import sys; sys.path.insert(0,sys.argv[1]); from services.local_credentials import publish_tokens; publish_tokens(sys.argv[2],sys.argv[3],"synthetic-test-pairing-"+"y"*32)'
    const published = spawnSync(python, ['-c', script, project, origin, token], { windowsHide: true, encoding: 'utf8' })
    assert.equal(published.status, 0, 'Core DPAPI publication must succeed')
    const client = new HKUAgentsClient({ baseUrl: origin, tokenEnv: 'INTEGRATION_API_TOKEN', timeoutMs: 5000 })
    assert.equal((await client.connectHku()).ok, true)
  } finally {
    if (previousProfile === undefined) delete process.env.USERPROFILE; else process.env.USERPROFILE = previousProfile
    if (previousToken === undefined) delete process.env.INTEGRATION_API_TOKEN; else process.env.INTEGRATION_API_TOKEN = previousToken
    server.close(); await once(server, 'close')
    await rm(directory, { recursive: true, force: true })
  }
})
