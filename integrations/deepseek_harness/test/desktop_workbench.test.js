import assert from 'node:assert/strict'
import test from 'node:test'
import { acceptanceReport, compatibleExtension, localChecks, taskSnapshot, taskRow, workbenchRoute } from '../lib/desktop_workbench.js'
import { HKUAgentsAPIError } from '../lib/client.js'

function fixture() {
  const calls = []
  const client = {
    async status() { calls.push('status'); return { result: { service_version: '0.1.0',
      connections: [{ id: 'sis_browser', status: 'connected', extension_version: '0.17.25' }], token: 'SECRET' }, correlation_id: 'safe' } },
    async listLibraryFacilities() { calls.push('catalog'); return { result: { read_only: true,
      browser_interactions_performed: false, domain_writes_performed: 0, library_writes_performed: 0,
      booking_writes_performed: 0, slot_selection_performed: false, booking_form_opened: false,
      facilities: [], availability_targets: [], facility_count: 0, availability_target_count: 0 }, correlation_id: 'safe' } },
    async libraryOperator(operation, input) {
      calls.push(operation); assert.deepEqual(input, {})
      const results = { booking_gate_status: { external_submission_enabled: false },
        shadow_status: { enabled: true, shadow_only: true, scheduler_running: true },
        f4_executor_status: { execution_enabled: false, dry_run: true, scheduler_running: true },
        shadow_rules: { rules: [{ id: 'rule-id', state: 'active', rule: { target_date: '2026-10-03',
          room_preference_order: [{ room: 'Study Room 2' }], session_preference_order: [{ start_time: '09:00', end_time: '10:00' }] } }] },
        shadow_runs: { runs: [{ id: 'run-id', outcome: 'read_failed', error_code: 'BROWSER_NOT_CONNECTED' }] },
        f4_authorizations: { authorizations: [{ id: 'auth-id', state: 'outcome_unknown', attempt_count: 1,
          booking_writes_performed: 'unknown', arming_digest: 'SECRET', booking_reference: 'PRIVATE',
          exact_target: { room: 'Discussion Room 2', target_date: '2026-10-03', execution_at: '2026-10-02T16:00:00Z' } }] } }
      return { ok: true, operation, result: results[operation] }
    },
  }
  return { client, calls }
}

test('local diagnostics call only fixed non-navigating reads and report versions', async () => {
  const { client, calls } = fixture()
  const result = await localChecks(client)
  assert.equal(result.local_only, true); assert.equal(result.live_acceptance, 'not_tested')
  assert.equal(result.domain_writes_performed, 0)
  assert.deepEqual(calls, ['status', 'catalog', 'booking_gate_status', 'shadow_status', 'f4_executor_status'])
  assert.equal(result.checks.every(c => c.state === 'pass'), true)
  assert.doesNotMatch(JSON.stringify(result), /SECRET/)
})

test('missing and stale extension version are not reported as accepted', () => {
  assert.equal(compatibleExtension('0.17.23'), false)
  assert.equal(compatibleExtension('0.17.24'), false)
  assert.equal(compatibleExtension('0.17.25'), true)
  assert.equal(compatibleExtension('0.18.0'), true)
  assert.equal(compatibleExtension('0.17.24-rc.1'), null)
  assert.equal(compatibleExtension(null), null)
})

test('enabled live gates require review and are never automatically changed', async () => {
  const { client, calls } = fixture()
  client.libraryOperator = async operation => { calls.push(operation); return { ok: true, operation,
    result: operation === 'booking_gate_status' ? { external_submission_enabled: true }
      : operation === 'f4_executor_status' ? { execution_enabled: true, dry_run: false, scheduler_running: true }
      : { enabled: true, shadow_only: true, scheduler_running: true } } }
  const value = await localChecks(client)
  assert.equal(value.checks.find(c => c.id === 'f2_gate').state, 'needs_review')
  assert.equal(value.checks.find(c => c.id === 'f4_runtime').state, 'needs_review')
  assert.equal(calls.some(v => /configure|arm|create|connect/.test(v)), false)
})

test('a failed local read is explicit and exception text is not exposed', async () => {
  const { client } = fixture()
  client.libraryOperator = async operation => { throw new HKUAgentsAPIError('API_UNAVAILABLE', 'SECRET-cookie') }
  const value = await localChecks(client)
  assert.equal(value.checks.find(c => c.id === 'f4_runtime').state, 'fail')
  assert.doesNotMatch(JSON.stringify(value), /SECRET-cookie/)
})

test('task snapshot is bounded and cannot arm or expose action digests/record references', async () => {
  const { client, calls } = fixture()
  const result = await taskSnapshot(client)
  assert.deepEqual(calls, ['shadow_rules', 'shadow_runs', 'f4_authorizations'])
  assert.equal(result.changes_performed, false)
  const row = result.groups[2].rows[0]
  assert.equal(row.booking_writes_performed, 'unknown'); assert.equal(row.attempt_count, 1)
  assert.equal(result.groups[0].rows[0].target.room, 'Study Room 2')
  assert.equal(result.groups[0].rows[0].target.preference_summary_only, true)
  assert.doesNotMatch(JSON.stringify(result), /SECRET|PRIVATE|arming_digest|booking_reference/)
  assert.equal(taskRow({ id: '<invalid>' }, 'F3'), null)
})

test('partial task failure is not presented as an empty successful group', async () => {
  const { client } = fixture(); const original = client.libraryOperator
  client.libraryOperator = async (...args) => { if (args[0] === 'shadow_runs') throw new Error('secret'); return original(...args) }
  const result = await taskSnapshot(client)
  assert.equal(result.groups[0].ok, true); assert.equal(result.groups[1].ok, false)
  assert.equal(result.groups[1].error_code, 'LOCAL_CHECK_FAILED')
})

test('F3 run uses matching rule checking time and verified suggested candidate, not preparation or arbitrary candidate', () => {
  const rule = { id: 'rule-id', shadow_only: true, rule: { target_date: '2026-10-02', facility_type: 'discussion_room',
    prepare_at: '2026-10-02T13:59:00+08:00', execution_at: '2026-10-02T14:01:00+08:00', stop_at: '2026-10-02T14:04:00+08:00',
    room_preference_order: [{ room: 'Discussion Room 1' }], session_preference_order: [{ start_time: '19:00', end_time: '20:00' }] } }
  const run = { id: 'run-id', rule_id: 'rule-id', read_only: true, target_date: '2026-10-02', outcome: 'suggestion_ready',
    scheduled_at: '2026-10-02T05:59:00Z', suggested_candidate_id: 'candidate-id',
    candidates: [{ candidate_id: 'candidate-id', room: 'Discussion Room 2', start_time: '20:00', end_time: '21:00' }] }
  const row = taskRow(run, 'F3 runs', rule)
  assert.equal(row.scheduled_at, rule.rule.execution_at); assert.equal(row.scheduled_time_basis, 'checking_start')
  assert.equal(row.prepare_at, rule.rule.prepare_at); assert.equal(row.read_only, true)
  assert.equal(row.target.room, 'Discussion Room 2'); assert.equal(row.target.start_time, '20:00')
  assert.equal(row.target.suggested_candidate_verified, true); assert.equal(row.target.preference_summary_only, false)
  const unmatched = taskRow(run, 'F3 runs', { ...rule, id: 'wrong-rule' })
  assert.equal(unmatched.scheduled_time_basis, 'preparation_or_legacy_schedule')
  assert.equal(unmatched.target.facility_type, null)
  assert.equal(taskRow({ ...run, suggested_candidate_id: 'missing-id' }, 'F3 runs', rule).target.suggested_candidate_verified, false)
  assert.equal(taskRow({ ...run, suggested_candidate_id: undefined, candidates: [{}] }, 'F3 runs', rule).target.suggested_candidate_verified, false)
})

test('report omits targets, diagnostics, inputs, account content and keeps human verdict separate', async () => {
  const { client } = fixture()
  const report = await acceptanceReport(client, { async list() { return [{ operation: 'moodle_assignments',
    recorded_at: '2026-10-02T00:00:00.000Z', plugin_version: '0.19.0', outcome: 'completed', verdict: 'pending',
    error_code: null, domain_writes: '0', task_id: 'id', correlation_id: 'id', target: 'PRIVATE',
    diagnostics: { raw_dom: 'PRIVATE' }, input: 'SECRET' }] } })
  assert.equal(report.review_totals.pending, 1); assert.equal(report.review_totals.pass, 0)
  assert.doesNotMatch(JSON.stringify(report), /PRIVATE|SECRET|target_date|raw_dom/)
  assert.equal(report.plugin_version, '0.19.2')
})

test('unreadable history remains an explicit report error, not an empty accepted history', async () => {
  const { client } = fixture()
  const report = await acceptanceReport(client, { async list() { throw new Error('PRIVATE-path') } })
  assert.equal(report.history_error, 'HISTORY_UNAVAILABLE')
  assert.doesNotMatch(JSON.stringify(report), /PRIVATE-path/)
})

function request(action, payload = {}, extra = {}) {
  return new Request(`http://localhost/api/hku-agents/admin/workbench/${action}`, { method: 'POST',
    body: JSON.stringify({ type: 'client-request', rpcId: '12345678-1234-1234-1234-123456789abc',
      method: `hku-agents/admin/workbench/${action}`, payload, ...extra }) })
}
test('fixed workbench RPC rejects arbitrary payloads, malformed calls and oversized requests before reading', async () => {
  const { client, calls } = fixture(); const route = workbenchRoute('checks', client)
  for (const req of [request('checks', { operation: 'booking_execute' }), request('checks', {}, { url: 'https://evil.example' }),
    request('tasks'), request('checks', { huge: 'x'.repeat(3000) })]) assert.equal((await route.fetch(req)).status, 400)
  assert.deepEqual(calls, [])
})

test('workbench uses rc.2 server-response and no-store for all three routes', async () => {
  for (const action of ['checks', 'tasks', 'report']) {
    const { client } = fixture()
    const response = await workbenchRoute(action, client, { async list() { return [] } }).fetch(request(action))
    assert.equal(response.headers.get('cache-control'), 'no-store')
    const body = await response.json(); assert.equal(body.type, 'server-response'); assert.equal(body.result.value.ok, true)
  }
})

test('cancellation stops subsequent stages without any mutating call', async () => {
  const { client, calls } = fixture(); const controller = new AbortController()
  controller.abort(); await assert.rejects(localChecks(client, controller.signal), /Cancelled/)
  assert.deepEqual(calls, ['status'])
})
