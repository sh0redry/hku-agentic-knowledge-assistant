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
      return [state, next => { state = typeof next === 'function' ? next(state) : next }]
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
    setTimeout,
  })
  assert.equal(registration.id, manifest.name)
  const plugin = registration.factory(name => {
    requestedModules.push(name)
    assert.equal(name, 'react')
    return react
  })
  return { plugin, requestedModules, effects, resetState() { state = undefined } }
}

function findNode(node, predicate) {
  if (!node || typeof node !== 'object') return null
  if (predicate(node)) return node
  for (const child of node.children ?? []) {
    const found = findNode(child, predicate)
    if (found) return found
  }
  return null
}

test('Desktop package declares client bundle and platform dependencies', () => {
  assert.equal(manifest.exports['./client'].default, './browser-client.js')
  assert.equal(manifest.dsh.client.platform, 'web')
  assert.deepEqual(manifest.dsh.client.inject, [
    '@deepseek-ai/dsh-client-connection',
    '@deepseek-ai/dsh-client-ui-layout',
    '@deepseek-ai/dsh-client-ui-sidebar',
    '@deepseek-ai/dsh-client-ui-tool',
  ])
})

test('rc.2 keyed toolviews cover every HKU tool and render only safe metadata, with original inspection', () => {
  const { plugin } = loadBrowserHalf()
  const registered = []
  const ctx = { slots: {
    inject(name, install) { if (name === 'tool.call.toolview') [...install()] },
    register(options, component) { registered.push({ options, component }); return () => {} },
  } }
  plugin.apply(ctx)
  const names = [...readFileSync(new URL('src/index.ts', packageRoot), 'utf8').matchAll(/name: '(hku_[^']+)'/g)].map(match => match[1])
  assert.equal(names.length, 23)
  assert.deepEqual(registered.map(row => row.options.key), names)
  assert.ok(registered.every(row => row.options.name === 'tool.call.toolview'))
  const render = registered.find(row => row.options.key === 'hku_library_space_dates').component
  let inspected = 0
  const props = { toolName: 'hku_library_space_dates', phase: 'result', inspect() { inspected++ }, block: {
    kind: 'tool-result', isError: false, call: { argsRaw: 'PRIVATE_INPUT' },
    content: [{ type: 'text', text: 'PRIVATE_ORIGINAL_JSON' }],
    meta: { state: 'Read completed — not a booking', date_option_count: 2,
      offered_dates: '2026-10-02, 2026-10-03', domain_writes: '0', task_id: 'task-id',
      correlation_id: 'safe-id', private_rows: 'PRIVATE_ROWS', course_name: 'PRIVATE_COURSE' }
  } }
  const tree = render(props)
  const text = JSON.stringify(tree)
  assert.match(text, /Read completed/)
  assert.match(text, /2026-10-02/)
  assert.match(text, /task-id/)
  assert.doesNotMatch(text, /PRIVATE_|argsRaw|course_name/)
  findNode(tree, node => node.type === 'button').props.onClick()
  assert.equal(inspected, 1)
  assert.match(JSON.stringify(render({ ...props, phase: 'preparing', block: {} })), /Preparing read/)
  assert.match(JSON.stringify(render({ ...props, phase: 'start', block: {} })), /Reading/)
  const failed = JSON.stringify(render({ ...props, block: { ...props.block, isError: true, error: { code: 'API_UNAVAILABLE' } } }))
  assert.match(failed, /Read failed/); assert.doesNotMatch(failed, /Read completed|2026-10-02/)
  const missing = JSON.stringify(render({ ...props, block: { kind: 'tool-result', isError: false } }))
  assert.match(missing, /Result not verified/); assert.doesNotMatch(missing, /Read completed/)
  assert.match(JSON.stringify(render({ ...props, block: { isError: true, error: { code: 'interrupted' } } })), /Read interrupted/)
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
  assert.deepEqual(entries.map(entry => entry.waitedFor), ['tool.call.toolview', 'main', 'sidebar.panellist', 'main', 'sidebar.panellist'])
  const [panel, sidebar, adminPanel, adminSidebar] = entries.slice(1).map(entry => entry.registration)
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
  findNode(refreshed, node => node.type === 'button' && node.children[0] === 'Connect HKU').props.onClick()
  await Promise.resolve()
  assert.equal(calls[1].endpoint, 'hku-agents/connect')
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1].payload)), {})
  await new Promise(resolve => setImmediate(resolve))
  const startButton = findNode(root.type(root.props), node => node.type === 'button' && node.children[0] === 'Start and connect HKU')
  startButton.props.onClick()
  assert.equal(findNode(root.type(root.props), node => node.type === 'button' && node.children[0] === 'Start and connect HKU').props.disabled, true)
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls[2].endpoint, 'hku-agents/start')
  assert.equal(calls[3].endpoint, 'hku-agents/connect')
  assert.deepEqual(JSON.parse(JSON.stringify(calls[2].payload)), {})
  assert.match(source, /attempt < 40/)
  assert.match(source, /Waiting for Chrome Bridge/)
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

test('SIS Admin section invokes fixed read-only sync and validated preflight routes', async () => {
  const { plugin, resetState } = loadBrowserHalf()
  let adminPanel
  const calls = []
  const ctx = {
    connection: { rpc: { async call(channel, endpoint, payload) {
      calls.push({ channel, endpoint, payload })
      if (endpoint.endsWith('/sync')) return { ok: true, value: {
        ok: true, read_only: true, sis_write_requests_sent: 0,
        temporary_courses: [], schedule_courses: [], term_label: '2026-27 Sem 1',
        diagnostics: { parser_version: '1.2.3' }, correlation_id: 'safe-id',
      } }
      return { ok: true, value: {
        ok: true, read_only: true, sis_write_requests_sent: 0,
        ready: true, term_match: true, matched_courses: [], missing_courses: [], unexpected_courses: [],
        issues: [], requested_term_label: '2026-27 Sem 1', observed_term_label: '2026-27 Sem 1',
        task_id: 'task-id', correlation_id: 'safe-id',
      } }
    } } },
    slots: {
      inject(name, install) { if (name === 'main') adminPanel = install() },
      register(options, component) { return { options, component } },
    },
  }
  plugin.apply(ctx)
  const root = adminPanel.component()
  const section = findNode(root.type(root.props), node => node.type?.name === 'SISAdminSection')
  assert.ok(section)
  resetState()
  const tree = () => section.type(section.props)
  const button = label => findNode(tree(), node => node.type === 'button' && node.children[0] === label)
  button('Sync course lists (read-only)').props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls[0].endpoint, 'hku-agents/admin/sis/sync')
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0].payload)), {})
  assert.match(JSON.stringify(tree()), /Temporary Course List/)
  const input = findNode(tree(), node => node.type === 'input')
  const textarea = findNode(tree(), node => node.type === 'textarea')
  input.props.onChange({ target: { value: '2026-27 Sem 1' } })
  textarea.props.onChange({ target: { value: 'COMP1234 | 1A' } })
  button('Run exact live preflight (read-only)').props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls[1].endpoint, 'hku-agents/admin/sis/preflight')
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1].payload)), {
    term_label: '2026-27 Sem 1', expected_courses: [{ course_code: 'COMP1234', section: '1A' }],
  })
  assert.match(JSON.stringify(tree()), /Verdict: ready/)
  assert.doesNotMatch(JSON.stringify(tree()), /INTEGRATION_API_TOKEN|BROWSER_PAIRING_TOKEN/)
})

test('read-only Admin groups call fixed routes and carry live Date options into the date field', async () => {
  const { plugin, resetState } = loadBrowserHalf()
  let adminPanel
  const calls = []
  const ctx = {
    connection: { rpc: { async call(channel, endpoint, payload) {
      calls.push({ channel, endpoint, payload })
      return { ok: true, value: {
        ok: true, read_only: true, domain_writes_performed: 0,
        operation: 'library_dates', summary: { offered_dates: ['2026-10-02'], date_option_count: 1 },
        task_id: 'task-id', correlation_id: 'correlation-id',
      } }
    } } },
    slots: {
      inject(name, install) { if (name === 'main') adminPanel = install() },
      register(options, component) { return { options, component } },
    },
  }
  plugin.apply(ctx)
  const root = adminPanel.component()
  const section = findNode(root.type(root.props), node => node.type?.name === 'ReadOnlyAdminSection')
  assert.ok(section)
  resetState()
  const tree = () => section.type(section.props)
  const button = findNode(tree(), node => node.type === 'button' && node.children[0] === 'Read live Date options')
  button.props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{ channel: '/api', endpoint: 'hku-agents/admin/read/library_dates', payload: { facility_type: 'discussion_room' } }])
  const dateInput = findNode(tree(), node => node.type === 'input' && node.props.maxLength === 10)
  assert.equal(dateInput.props.value, '2026-10-02')
  assert.match(JSON.stringify(tree()), /Domain writes: 0/)
  const rendered = JSON.stringify(tree())
  assert.equal((rendered.match(/task-id/g) || []).length, 1)
  assert.equal((rendered.match(/correlation-id/g) || []).length, 1)
})

test('business quick checks stay narrow and history reviews use only fixed local RPCs', async () => {
  const { plugin, resetState } = loadBrowserHalf()
  const panels = []; const calls = []
  const historyRecord = { id: '12345678-1234-4123-8123-123456789abc', operation: 'moodle_assignments',
    outcome: 'completed', verdict: 'pending', plugin_version: '0.18.10', recorded_at: '2026-10-01T10:00:00.000Z', domain_writes: '0', diagnostics: { parser_version: '0.4.2' } }
  const ctx = { connection: { rpc: { async call(channel, endpoint, payload) {
    calls.push({ channel, endpoint, payload })
    return { ok: true, value: { ok: true, local_only: true, records: [{ ...historyRecord, verdict: payload.verdict || 'pending' }] } }
  } } }, slots: {
    inject(name, install) { if (name === 'main') panels.push(install()) },
    register(options, component) { return { options, component } }
  } }
  plugin.apply(ctx)
  const root = panels[0].component()
  const quick = findNode(root.type(root.props), n => n.type?.name === 'ReadOnlyAdminSection')
  assert.equal(quick.props.business, true)
  resetState()
  const quickText = JSON.stringify(quick.type(quick.props))
  assert.match(quickText, /Refresh assignment count/)
  assert.doesNotMatch(quickText, /Count available slots|Library research keywords|Sync weekly timetable/)
  resetState()
  const adminRoot = panels[1].component()
  const history = findNode(adminRoot.type(adminRoot.props), n => n.type?.name === 'HistorySection')
  resetState()
  const tree = () => history.type(history.props)
  findNode(tree(), n => n.type === 'button' && n.children[0] === 'Refresh test history').props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls[0].endpoint, 'hku-agents/admin/history/list')
  assert.match(JSON.stringify(tree()), /review: pending/)
  findNode(tree(), n => n.type === 'button' && n.children[0] === 'Mark pass').props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls[1].endpoint, 'hku-agents/admin/history/review')
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1].payload)), { id: historyRecord.id, verdict: 'pass' })
  assert.match(JSON.stringify(tree()), /review: pass/)
})
