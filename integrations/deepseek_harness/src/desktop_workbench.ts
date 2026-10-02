import type { Context } from '@deepseek-ai/cordis'
import { HKUAgentsAPIError, type HKUAgentsClient } from './client.js'
import { readDesktopStatus } from './desktop_status.js'
import { readDesktopFacilities } from './desktop_admin.js'
import { testHistory, type TestHistory } from './history.js'

export const RELEASE = '0.19.2'
export const REQUIRED_EXTENSION = '0.17.25'
type Client = Pick<HKUAgentsClient, 'status' | 'listLibraryFacilities' | 'libraryOperator'>
type Route = { path: string; methods: string[]; requestBody: 'buffered'; fetch(request: Request): Promise<Response> }
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const text = (v: unknown, limit = 120) => typeof v === 'string' && v.length <= limit ? v.replace(/[<>\r\n]/g, ' ') : null
const code = (e: unknown) => e instanceof HKUAgentsAPIError && /^[A-Z0-9_]{1,64}$/.test(e.code) ? e.code : 'LOCAL_CHECK_FAILED'
const count = (v: unknown) => typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= 100000 ? v : null
export function compatibleExtension(value: unknown): boolean | null {
  if (typeof value !== 'string' || !/^\d+\.\d+\.\d+$/.test(value)) return null
  const actual = value.split('.').map(Number), required = REQUIRED_EXTENSION.split('.').map(Number)
  if (!actual.every(Number.isSafeInteger)) return null
  for (let i = 0; i < 3; i++) { if (actual[i]! !== required[i]!) return actual[i]! > required[i]! }
  return true
}

async function operator(client: Client, operation: string, signal?: AbortSignal) {
  const value = await client.libraryOperator(operation, {}, signal)
  if (value.ok !== true || value.operation !== operation || !object(value.result)) throw new Error('Invalid response')
  return value.result
}

// These checks never call connect, navigate, inspect a live HKU page, mutate a
// gate or create a task. A healthy local installation is not live acceptance.
export async function localChecks(client: Client, signal?: AbortSignal) {
  const checks: Array<Record<string, unknown>> = []
  const status = await readDesktopStatus(client, signal)
  const bridge = status.connections.find(v => v.id === 'sis_browser')
  checks.push({ id: 'core', state: status.core.state === 'connected' ? 'pass' : 'fail',
    observed_version: 'version' in status.core ? status.core.version : null,
    error_code: 'error_code' in status.core ? status.core.error_code : null })
  const extension = compatibleExtension(bridge?.extension_version)
  checks.push({ id: 'chrome_bridge', state: bridge?.status === 'connected' ? 'pass' : 'needs_review' })
  checks.push({ id: 'extension_version', state: extension === true ? 'pass' : extension === false ? 'fail' : 'needs_review',
    observed_version: text(bridge?.extension_version), required_version: REQUIRED_EXTENSION })
  if (signal?.aborted) throw new Error('Cancelled')
  const facilities = await readDesktopFacilities(client, signal)
  checks.push({ id: 'local_catalog', state: facilities.ok ? 'pass' : 'fail',
    facility_count: facilities.ok ? facilities.facility_count : null,
    error_code: facilities.ok ? null : facilities.error?.code || 'CATALOG_READ_FAILED' })
  for (const [id, operation, fields] of [
    ['f2_gate', 'booking_gate_status', ['external_submission_enabled']],
    ['f3_scheduler', 'shadow_status', ['scheduler_running', 'enabled', 'shadow_only']],
    ['f4_runtime', 'f4_executor_status', ['execution_enabled', 'dry_run', 'scheduler_running']],
  ] as const) {
    if (signal?.aborted) throw new Error('Cancelled')
    try {
      const value = await operator(client, operation, signal)
      const flags = Object.fromEntries(fields.map(key => [key, typeof value[key] === 'boolean' ? value[key] : null]))
      const liveEnabled = flags.external_submission_enabled === true || flags.execution_enabled === true && flags.dry_run === false
      checks.push({ id, state: liveEnabled || Object.values(flags).some(v => v === null) ? 'needs_review' : 'pass', ...flags })
    } catch (error) { checks.push({ id, state: 'fail', error_code: code(error) }) }
  }
  return { ok: true, local_only: true, browser_interactions_performed: false, domain_writes_performed: 0,
    plugin_version: RELEASE, host_runtime: process.version, observed_at: new Date().toISOString(), checks,
    live_acceptance: 'not_tested', connection: status }
}

// Separate UI-only snapshot. No action/arming digest, record reference, private
// payload, or candidate data is exposed; polling cannot authorize any operation.
export function taskRow(value: unknown, kind: string, ruleContext?: unknown) {
  if (!object(value)) return null
  const id = text(value.id, 64)
  if (!id || !/^[a-zA-Z0-9-]+$/.test(id)) return null
  const context = object(ruleContext) && ruleContext.id === value.rule_id && object(ruleContext.rule) ? ruleContext.rule : null
  const target = object(value.exact_target) ? value.exact_target : object(value.rule) ? value.rule : context || value
  const candidates = value.outcome === 'suggestion_ready' && typeof value.suggested_candidate_id === 'string' &&
    /^[a-zA-Z0-9-]{1,64}$/.test(value.suggested_candidate_id) && Array.isArray(value.candidates)
    ? value.candidates.filter(v => object(v) && v.candidate_id === value.suggested_candidate_id) : []
  const candidate = candidates.length === 1 && object(candidates[0]) && text(candidates[0].room, 80) &&
    /^\d{2}:\d{2}$/.test(String(candidates[0].start_time)) && /^\d{2}:\d{2}$/.test(String(candidates[0].end_time)) ? candidates[0] : null
  const room = candidate || (Array.isArray(target.room_preference_order) && object(target.room_preference_order[0]) ? target.room_preference_order[0] : target)
  const session = candidate || (Array.isArray(target.session_preference_order) && object(target.session_preference_order[0]) ? target.session_preference_order[0] : target)
  return { kind, id, rule_id: text(value.rule_id, 64), state: text(value.state || value.outcome, 64),
    phase: text(value.phase, 64), error_code: text(value.error_code, 64),
    next_run_at: text(value.next_run_at || value.next_check_at, 40),
    scheduled_at: text(target.execution_at || value.scheduled_at_local || value.scheduled_at, 40),
    scheduled_time_basis: target.execution_at ? 'checking_start' : kind === 'F3 runs' ? 'preparation_or_legacy_schedule' : 'legacy_schedule',
    started_at: text(value.started_at, 40),
    prepare_at: text(target.prepare_at, 40), stop_at: text(target.stop_at, 40), date_check_count: count(value.date_check_count),
    completed_at: text(value.completed_at, 40), armed: typeof value.armed === 'boolean' ? value.armed : null,
    dry_run: typeof value.dry_run === 'boolean' ? value.dry_run : null,
    attempt_count: count(value.attempt_count), success_count: count(value.success_count),
    read_only: kind === 'F3 rules' ? value.shadow_only === true : kind === 'F3 runs' ? value.read_only === true : null,
    run_count: count(value.run_count), max_runs: count(value.max_runs),
    booking_writes_performed: count(value.booking_writes_performed) ?? (value.booking_writes_performed === 'unknown' ? 'unknown' : null),
    target: { date: text(value.target_date || target.date || target.target_date, 10), facility_type: text(target.facility_type, 64),
      room: text(room.room, 80), start_time: text(session.start_time, 5), end_time: text(session.end_time, 5),
      preference_summary_only: !candidate && (Array.isArray(target.room_preference_order) || Array.isArray(target.session_preference_order)),
      suggested_candidate_verified: !!candidate } }
}

export async function taskSnapshot(client: Client, signal?: AbortSignal) {
  const groups = []
  const rules = new Map<string, unknown>()
  for (const [kind, operation, key] of [
    ['F3 rules', 'shadow_rules', 'rules'], ['F3 runs', 'shadow_runs', 'runs'],
    ['F4 authorizations', 'f4_authorizations', 'authorizations'],
  ]) {
    if (signal?.aborted) throw new Error('Cancelled')
    try {
      const value = await operator(client, operation!, signal)
      if (!Array.isArray(value[key!])) throw new Error('Invalid list')
      const raw = (value[key!] as unknown[]).slice(0, 100)
      if (kind === 'F3 rules') for (const row of raw) if (object(row) && typeof row.id === 'string') rules.set(row.id, row)
      const rows = raw.map(v => taskRow(v, kind!, object(v) && typeof v.rule_id === 'string' ? rules.get(v.rule_id) : null)).filter(v => v !== null)
      groups.push({ kind, ok: true, rows, returned_count: rows.length, bounded_snapshot: true })
    } catch (error) { groups.push({ kind, ok: false, rows: [], error_code: code(error) }) }
  }
  return { ok: true, read_only: true, observed_at: new Date().toISOString(), groups,
    scope: 'bounded_current_core_snapshot_not_all_history', changes_performed: false }
}

export async function acceptanceReport(client: Client, history: Pick<TestHistory, 'list'>, signal?: AbortSignal) {
  const diagnostics = await localChecks(client, signal)
  let records: Array<Record<string, unknown>> = [], history_error: string | null = null
  try {
    records = (await history.list()).slice(0, 100).map(r => ({ operation: r.operation,
      recorded_at: r.recorded_at, plugin_version: r.plugin_version, outcome: r.outcome,
      verdict: r.verdict, error_code: r.error_code, domain_writes: r.domain_writes,
      task_id: r.task_id, correlation_id: r.correlation_id }))
  } catch { history_error = 'HISTORY_UNAVAILABLE' }
  return { schema_version: 1, generated_at: new Date().toISOString(), plugin_version: RELEASE,
    local_only: true, browser_interactions_performed: false, domain_writes_performed: 0,
    checks: diagnostics.checks, history_error, records,
    review_totals: Object.fromEntries(['pending', 'pass', 'fail', 'needs_review'].map(v => [v, records.filter(r => r.verdict === v).length])),
    limitations: ['Latest 100 local Admin calls only; Chat calls omitted.',
      'Request completion is not human acceptance or booking success.',
      'No targets, inputs, credentials, account data, DOM or course rows included.',
      'Real F2/F4 reservation and midnight release acceptance require user verification.'] }
}

export function workbenchRoute(action: 'checks' | 'tasks' | 'report', client: Client, history: Pick<TestHistory, 'list'> = testHistory): Route {
  const method = `hku-agents/admin/workbench/${action}`
  const respond = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } })
  return { path: `/api/${method}`, methods: ['POST'], requestBody: 'buffered', async fetch(request) {
    if (request.method !== 'POST') return respond({ error: 'method_not_allowed' }, 405)
    if (Number(request.headers.get('content-length') || 0) > 2048) return respond({ error: 'invalid_request' }, 400)
    const raw = await request.text()
    if (Buffer.byteLength(raw) > 2048) return respond({ error: 'invalid_request' }, 400)
    let b: unknown
    try { b = JSON.parse(raw) } catch { return respond({ error: 'invalid_request' }, 400) }
    if (!object(b) || Object.keys(b).sort().join(',') !== 'method,payload,rpcId,type' || b.type !== 'client-request' ||
      b.method !== method || typeof b.rpcId !== 'string' || !/^[0-9a-f-]{36}$/i.test(b.rpcId) || !object(b.payload) ||
      Object.keys(b.payload).length) return respond({ error: 'invalid_request' }, 400)
    let value: unknown
    const signal = AbortSignal.any([request.signal, AbortSignal.timeout(30000)])
    try { value = action === 'checks' ? await localChecks(client, signal)
      : action === 'tasks' ? await taskSnapshot(client, signal)
      : { ok: true, report: await acceptanceReport(client, history, signal) } }
    catch (error) { value = { ok: false, error: { code: code(error) } } }
    return respond({ type: 'server-response', rpcId: b.rpcId, result: { ok: true, value } })
  } }
}

export function installDesktopWorkbench(ctx: Context, client: Client): void {
  ctx.inject(['connection'], scope => {
    const host = scope as unknown as { connection: { fetch: { register(route: Route): () => void } } }
    for (const action of ['checks', 'tasks', 'report'] as const) scope.effect(() => host.connection.fetch.register(workbenchRoute(action, client)))
  })
}
