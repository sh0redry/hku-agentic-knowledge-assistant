import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import test from 'node:test'

const packageRoot = new URL('../', import.meta.url)
const manifest = JSON.parse(readFileSync(new URL('package.json', packageRoot), 'utf8'))
const source = readFileSync(new URL('browser-client.js', packageRoot), 'utf8')

function loadBrowserHalf() {
  let registration
  const requestedModules = []
  const effects = []
  let state
  const ref = { current: null }
  const react = {
    createElement: (type, props, ...children) => ({ type, props: props ?? {}, children }),
    useState(initial) {
      if (state === undefined) state = initial
      return [state, next => { state = next }]
    },
    useRef: () => ref,
    useEffect: effect => { effects.push(effect) },
  }
  runInNewContext(source, {
    window: {
      __ModuleLoader__: {
        load(value) { registration = value },
      },
    },
    fetch() { throw new Error('Browser half must not call Core directly') },
    localStorage: new Proxy({}, { get() { throw new Error('Browser half must not store credentials') } }),
    AbortController,
  })
  assert.equal(registration.id, manifest.name)
  const plugin = registration.factory(name => {
    requestedModules.push(name)
    assert.equal(name, 'react')
    return react
  })
  return { plugin, requestedModules, effects }
}

test('Desktop package declares client bundle and platform dependencies', () => {
  assert.equal(manifest.exports['./client'].default, './browser-client.js')
  assert.equal(manifest.dsh.client.platform, 'web')
  assert.deepEqual(manifest.dsh.client.inject, [
    '@deepseek-ai/dsh-client-connection',
    '@deepseek-ai/dsh-client-ui-layout',
    '@deepseek-ai/dsh-client-ui-sidebar',
  ])
})

test('browser half contributes separate business and Admin panels', () => {
  const { plugin, requestedModules } = loadBrowserHalf()
  assert.deepEqual(Array.from(plugin.inject), ['slots', 'layout', 'connection'])
  const entries = []
  const ctx = {
    connection: { rpc: { call() { throw new Error('not mounted') } }, state: {} },
    slots: {
      inject(name, install) {
        entries.push({ waitedFor: name, registration: install() })
      },
      register(options, component) {
        return { options, component }
      },
    },
  }
  plugin.apply(ctx)
  assert.deepEqual(entries.map(entry => entry.waitedFor), ['main', 'sidebar.panellist', 'main', 'sidebar.panellist'])
  const [panel, sidebar, adminPanel, adminSidebar] = entries.map(entry => entry.registration)
  assert.equal(panel.options.key, 'hku-agents')
  assert.equal(sidebar.options.id, 'hku-agents')
  assert.equal(sidebar.options.label(), 'HKU AGENTS')
  assert.equal(adminPanel.options.key, 'hku-agents-admin')
  assert.equal(adminSidebar.options.id, 'hku-agents-admin')
  assert.equal(adminSidebar.options.label(), 'HKU Admin')
  assert.deepEqual(requestedModules, ['react'])

  const root = panel.component()
  const tree = root.type(root.props)
  const text = JSON.stringify(tree)
  assert.match(text, /Checking local service/)
  assert.match(text, /cannot select a slot, submit a booking, or authorize F4/)
  assert.doesNotMatch(text, /INTEGRATION_API_TOKEN|BROWSER_PAIRING_TOKEN/)
})

test('browser panel reads only Host-mediated redacted status', async () => {
  const { plugin, effects } = loadBrowserHalf()
  let panel
  const calls = []
  const ctx = {
    connection: {
      rpc: {
        async call(channel, endpoint, payload) {
          assert.match(channel, /^\/[A-Za-z0-9._~-]+$/)
          assert.equal(endpoint.split('/').every(segment => /^[A-Za-z0-9_$.-]+$/.test(segment)), true)
          calls.push({ channel, endpoint, payload })
          return { ok: true, value: {
            read_only: true,
            core: { state: 'connected', version: 'test' },
            connections: [{ id: 'sis_browser', status: 'connected', lifecycle_state: 'paired' }],
            correlation_id: 'test-correlation',
          } }
        },
      },
      state: { subscribe() { return () => {} }, getSnapshot() { return 'connected' } },
    },
    slots: {
      inject(name, install) { if (name === 'main' && !panel) panel = install() },
      register(options, component) { return { options, component } },
    },
  }
  plugin.apply(ctx)
  const root = panel.component()
  root.type(root.props)
  const dispose = effects[0]()
  await Promise.resolve()
  const refreshed = root.type(root.props)
  const text = JSON.stringify(refreshed)
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{ channel: '/api', endpoint: 'hku-agents/status', payload: {} }])
  assert.match(text, /Core connected/)
  assert.match(text, /Chrome Bridge: connected \(paired\)/)
  assert.match(text, /test-correlation/)
  dispose()
})

test('browser panel distinguishes invalid Desktop RPC target from Host outage', async () => {
  const { plugin, effects } = loadBrowserHalf()
  let panel
  const ctx = {
    connection: {
      rpc: { async call() { throw new Error('connection: invalid RPC target /api/hku-agents/status') } },
      state: { subscribe() { return () => {} }, getSnapshot() { return 'connected' } },
    },
    slots: {
      inject(name, install) { if (name === 'main' && !panel) panel = install() },
      register(options, component) { return { options, component } },
    },
  }
  plugin.apply(ctx)
  const root = panel.component()
  root.type(root.props)
  effects[0]()
  await new Promise(resolve => setImmediate(resolve))
  const text = JSON.stringify(root.type(root.props))
  assert.match(text, /INVALID_RPC_TARGET/)
  assert.doesNotMatch(text, /HOST_DISCONNECTED/)
})

test('Admin panel runs only the fixed read-only facility catalog operation', async () => {
  const { plugin } = loadBrowserHalf()
  let adminPanel
  const calls = []
  const ctx = {
    connection: { rpc: { async call(channel, endpoint, payload) {
      calls.push({ channel, endpoint, payload })
      return { ok: true, value: {
        ok: true, read_only: true, booking_writes_performed: 0,
        facility_count: 1, availability_target_count: 1,
        facilities: [{ facility_type: 'discussion_room', name: 'Discussion Rooms', location: 'Main Library' }],
        availability_targets: [{ facility_type: 'discussion_room', booking_facility_type: 'Discussion Room', location: 'Main Library', booking_preview_supported: true, supervised_booking_supported: true }],
        policy_verified_on: '2026-09-24', correlation_id: 'safe-id',
      } }
    } } },
    slots: {
      inject(name, install) { if (name === 'main') adminPanel = install() },
      register(options, component) { return { options, component } },
    },
  }
  plugin.apply(ctx)
  const root = adminPanel.component()
  const findButton = node => {
    if (!node || typeof node !== 'object') return null
    if (node.type === 'button') return node
    for (const child of node.children ?? []) {
      const found = findButton(child)
      if (found) return found
    }
    return null
  }
  const button = findButton(root.type(root.props))
  assert.equal(button.children[0], 'Run read-only catalog test')
  button.props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{ channel: '/api', endpoint: 'hku-agents/admin/facilities', payload: {} }])
  const text = JSON.stringify(root.type(root.props))
  assert.match(text, /Passed: 1 policy summaries and 1 availability targets/)
  assert.match(text, /safe-id/)
  assert.doesNotMatch(text, /INTEGRATION_API_TOKEN|BROWSER_PAIRING_TOKEN/)
})
