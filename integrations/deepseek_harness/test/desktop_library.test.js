import assert from 'node:assert/strict'
import test from 'node:test'
import { installDesktopLibraryBridge, projectLibrary } from '../lib/desktop_library.js'

function routeFor(client) {
  let route
  installDesktopLibraryBridge({ inject(_keys, cb) { cb({ connection: { fetch: { register(value) { route = value; return () => {} } } },
    effect(cb) { cb() } }) } }, client, { async append() { return 'test-history-id' } })
  return route
}
function request(operation, input = {}, extra = {}) {
  return new Request('http://localhost/api/hku-agents/library/operator', { method: 'POST',
    body: JSON.stringify({ type: 'client-request', rpcId: '12345678-1234-1234-1234-123456789abc',
      method: 'hku-agents/library/operator', payload: { operation, input }, ...extra }) })
}
test('fixed operator route rejects generic endpoints and malformed RPC without a Core call', async () => {
  let count = 0
  const route = routeFor({ libraryOperator() { count++; throw new Error('must not call') } })
  for (const req of [request('proxy'), request('shadow_rules', {}, { url: 'https://evil.example' }),
    request('shadow_rules', {}, { method: 'other' })]) assert.equal((await route.fetch(req)).status, 400)
  assert.equal(count, 0)
})
test('operator projects exact target, policy and pending status but never a token or DOM', async () => {
  const result = { exact_target: { room: 'Discussion Room 2', date: '2026-10-03' }, policy: { booking_policy: 'one hour' },
    execution_enabled: false, confirmation_token: 'secret', raw_dom: '<div>private</div>' }
  const route = routeFor({ async libraryOperator(operation, input) {
    assert.deepEqual(input, {}); return { ok: true, operation, result, correlation_id: 'test' }
  } })
  const value = await (await route.fetch(request('f4_authorizations'))).json()
  assert.equal(value.type, 'server-response')
  assert.equal(value.result.ok, true)
  assert.equal(value.result.value.execution_enabled, false)
  assert.equal(value.result.value.result.exact_target.room, 'Discussion Room 2')
  assert.equal(value.result.value.result.policy.booking_policy, 'one hour')
  assert.doesNotMatch(JSON.stringify(value), /secret|raw_dom|confirmation_token/)
  assert.deepEqual(projectLibrary({ result: { cookie: 'secret' } }), { result: {} })
})
test('Host errors are stable and never echo private exception text', async () => {
  const route = routeFor({ async libraryOperator() { throw new Error('token=secret-private') } })
  const value = await (await route.fetch(request('booking_execute', {}))).json()
  assert.equal(value.result.value.ok, false)
  assert.equal(value.result.value.error.code, 'LIBRARY_OPERATOR_FAILED')
  assert.doesNotMatch(JSON.stringify(value), /secret-private/)
})
