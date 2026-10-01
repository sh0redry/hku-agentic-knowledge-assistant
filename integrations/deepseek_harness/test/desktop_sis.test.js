import assert from 'node:assert/strict'
import test from 'node:test'

import { DESKTOP_SIS_SYNC_PATH, DESKTOP_SIS_PREFLIGHT_PATH, desktopSISSyncRoute, desktopSISPreflightRoute } from '../lib/desktop_sis.js'

const rpcId = '12345678-1234-4123-8123-123456789abc'
const course = { course_code: 'COMP1234', section: '1A', class_number: '12345' }
const input = { term_label: '2026-27 Sem 1', expected_courses: [{ course_code: 'COMP1234', section: '1A' }] }

function request(path, method, payload) {
  return new Request(`http://desktop.local${path}`, {
    method: 'POST',
    body: JSON.stringify({ type: 'client-request', rpcId, method, payload }),
  })
}

test('SIS sync projects only bounded separate cart and schedule rows', async () => {
  let calls = 0
  const route = desktopSISSyncRoute({ async syncCourseLists() {
    calls++
    return { correlation_id: 'safe-id', result: {
      bound: true, origin: 'https://sis-main.hku.hk', logged_in: true, page_kind: 'cart',
      term_label: '2026-27 Sem 1', temporary_course_count: 1, schedule_course_count: 1,
      temporary_courses: [{ ...course, private_note: 'secret' }], schedule_courses: [course],
      diagnostics: { parser_version: '1.2.3', temporary_candidate_count: 1, schedule_candidate_count: 1, unclassified_candidate_count: 0, unclassified_courses: [{ secret: 'hidden' }] },
      path: '/private/page',
    } }
  } })
  assert.equal(route.path, DESKTOP_SIS_SYNC_PATH)
  const response = await route.fetch(request(route.path, 'hku-agents/admin/sis/sync', {}))
  const body = await response.json()
  assert.equal(body.result.value.ok, true)
  assert.equal(body.result.value.sis_write_requests_sent, 0)
  assert.deepEqual(body.result.value.temporary_courses, [course])
  assert.equal(calls, 1)
  assert.equal(response.headers.get('cache-control'), 'no-store')
  assert.doesNotMatch(JSON.stringify(body), /secret|hidden|private\/page/)
})

test('SIS preflight sends only exact validated intent and projects verdict, not raw snapshot', async () => {
  let seen
  const route = desktopSISPreflightRoute({ async preflight(value) {
    seen = value
    return { correlation_id: 'safe-id', task: { id: 'task-id' }, result: {
      ok: false, ready: false, read_only: true, simulated: false, sis_write_requests_sent: 0,
      page_kind: 'cart', requested_term_label: '2026-27 Sem 1', term_label: '2026-27 Sem 1', term_match: true,
      matched_courses: [], missing_courses: [{ course_code: 'COMP1234', section: '1A' }], unexpected_courses: [course],
      issues: ['Expected course/section entries are missing from the cart.'],
      visible_courses: [{ private_note: 'secret' }],
    } }
  } })
  assert.equal(route.path, DESKTOP_SIS_PREFLIGHT_PATH)
  const body = await (await route.fetch(request(route.path, 'hku-agents/admin/sis/preflight', input))).json()
  assert.deepEqual(seen, input)
  assert.equal(body.result.value.ready, false)
  assert.equal(body.result.value.task_id, 'task-id')
  assert.deepEqual(body.result.value.missing_courses, input.expected_courses)
  assert.doesNotMatch(JSON.stringify(body), /private_note|secret/)
})

test('SIS routes reject other methods, unexpected fields, malformed terms and duplicate intent before Core call', async () => {
  let calls = 0
  const client = { async syncCourseLists() { calls++ }, async preflight() { calls++ } }
  const sync = desktopSISSyncRoute(client)
  const preflight = desktopSISPreflightRoute(client)
  assert.equal((await sync.fetch(request(sync.path, 'hku-agents/admin/sis/sync', { navigate: true }))).status, 400)
  assert.equal((await preflight.fetch(request(preflight.path, 'hku-agents/admin/sis/preflight', { ...input, url: 'https://example.com' }))).status, 400)
  assert.equal((await preflight.fetch(request(preflight.path, 'hku-agents/admin/sis/preflight', { ...input, term_label: 'tomorrow' }))).status, 400)
  assert.equal((await preflight.fetch(request(preflight.path, 'hku-agents/admin/sis/preflight', { ...input, expected_courses: [input.expected_courses[0], input.expected_courses[0]] }))).status, 400)
  assert.equal((await preflight.fetch(request(preflight.path, 'hku-agents/admin/sis/book', input))).status, 400)
  assert.equal((await sync.fetch(new Request(`http://desktop.local${sync.path}`, { method: 'GET' }))).status, 405)
  assert.equal(calls, 0)
})

test('SIS sync fails closed on unclassified rows or unexpected booking-state response', async () => {
  const route = desktopSISSyncRoute({ async syncCourseLists() {
    return { result: { bound: true, origin: 'https://sis-main.hku.hk', logged_in: true, page_kind: 'cart',
      temporary_course_count: 0, schedule_course_count: 0, temporary_courses: [], schedule_courses: [],
      diagnostics: { unclassified_candidate_count: 1 },
    } }
  } })
  const body = await (await route.fetch(request(route.path, 'hku-agents/admin/sis/sync', {}))).json()
  assert.equal(body.result.value.ok, false)
  assert.equal(body.result.value.error.code, 'INVALID_SIS_SYNC_RESPONSE')
})
