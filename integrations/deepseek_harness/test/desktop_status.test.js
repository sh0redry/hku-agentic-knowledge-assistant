import assert from 'node:assert/strict'
import test from 'node:test'

import { HKUAgentsAPIError } from '../lib/client.js'
import { DESKTOP_STATUS_PATH, desktopStatusRoute, installDesktopStatusBridge, readDesktopStatus } from '../lib/desktop_status.js'

const rpcId = '12345678-1234-4123-8123-123456789abc'
const requestBody = JSON.stringify({ type: 'client-request', rpcId, method: 'hku-agents/status', payload: {} })

function request(body = requestBody, method = 'POST') {
  return new Request(`http://desktop.local${DESKTOP_STATUS_PATH}`, {
    method,
    body: method === 'POST' ? body : undefined,
  })
}

test('exact Desktop route projects only bounded Core and Bridge status', async () => {
  let requests = 0
  const route = desktopStatusRoute({
    async status() {
      requests += 1
      return {
        correlation_id: 'safe-correlation',
        result: {
          service_version: '0.18.3',
          secret: 'must-not-cross-to-renderer',
          connections: [
            {
              id: 'sis_browser', status: 'connected', lifecycle_state: 'paired',
              mode: 'chrome', extension_version: '0.17.1',
              active_url: 'https://private.example/', pairing_token: 'must-not-cross-to-renderer',
            },
            { id: 'bad', status: 'x'.repeat(200), pairing_token: 'secret' },
          ],
        },
      }
    },
  })
  assert.equal(route.path, DESKTOP_STATUS_PATH)
  assert.deepEqual(route.methods, ['POST'])
  assert.equal(route.requestBody, 'buffered')
  const response = await route.fetch(request())
  assert.equal(response.status, 200)
  assert.equal(response.headers.get('cache-control'), 'no-store')
  const body = await response.json()
  assert.equal(body.rpcId, rpcId)
  assert.equal(body.result.ok, true)
  assert.deepEqual(body.result.value, {
    read_only: true,
    core: { state: 'connected', version: '0.18.3' },
    connections: [{ id: 'sis_browser', status: 'connected', lifecycle_state: 'paired', mode: 'chrome', extension_version: '0.17.1' }],
    correlation_id: 'safe-correlation',
  })
  assert.equal(requests, 1)
  assert.doesNotMatch(JSON.stringify(body), /secret|private\.example/)
})

test('invalid Desktop requests cannot cause any Core call', async () => {
  let requests = 0
  const route = desktopStatusRoute({ async status() { requests += 1; throw new Error('unexpected') } })
  const bodies = [
    '{}',
    JSON.stringify({ type: 'client-request', rpcId, method: 'book', payload: {} }),
    JSON.stringify({ type: 'client-request', rpcId, method: 'status', payload: {} }),
    JSON.stringify({ type: 'client-request', rpcId, method: 'hku-agents/status', payload: { token: 'secret' } }),
    JSON.stringify({ type: 'client-request', rpcId, method: 'hku-agents/status', payload: {}, extra: true }),
    'x'.repeat(2049),
  ]
  for (const body of bodies) {
    const response = await route.fetch(request(body))
    assert.equal(response.status, 400)
  }
  assert.equal((await route.fetch(request(undefined, 'GET'))).status, 405)
  assert.equal(requests, 0)
})

test('Core outage is reported without leaking exception messages', async () => {
  const value = await readDesktopStatus({
    async status() { throw new HKUAgentsAPIError('API_UNAVAILABLE', 'Private URL and token in exception') },
  })
  assert.equal(value.core.state, 'unavailable')
  assert.equal(value.core.error_code, 'API_UNAVAILABLE')
  assert.match(value.core.recovery, /Start the local HKU AGENTS service/)
  assert.equal(value.connections.length, 0)
  assert.doesNotMatch(JSON.stringify(value), /Private URL|token in exception/)
})

test('Host registration is scoped to the connection service', () => {
  const routes = []
  const ctx = {
    inject(requirements, install) {
      assert.deepEqual(requirements, ['connection'])
      install({ connection: { fetch: { register(value) { routes.push(value); return () => {} } } } })
    },
  }
  installDesktopStatusBridge(ctx, { async status() { throw new Error('not called') } })
  assert.deepEqual(routes.map(route => route.path), [DESKTOP_STATUS_PATH, '/api/hku-agents/connect'])
})

test('Connect HKU accepts only an empty fixed request and redacts binding data', async () => {
  let calls = 0
  const route = desktopStatusRoute({ async status() {
    calls++
    return { correlation_id: 'connect-id', result: { service_version: 'test', connections: [],
      binding: { state: 'login_required', logged_in: false, page_kind: 'login', token: 'secret' } } }
  } }, true)
  const body = { type: 'client-request', rpcId, method: 'hku-agents/connect', payload: {} }
  const response = await route.fetch(request(JSON.stringify(body)))
  const value = (await response.json()).result.value
  assert.equal(value.core.state, 'connected')
  assert.equal(value.binding.state, 'login_required')
  assert.doesNotMatch(JSON.stringify(value), /secret/)
  assert.equal((await route.fetch(request(JSON.stringify({ ...body, payload: { url: 'https://example.com' } })))).status, 400)
  assert.equal(calls, 1)
})
