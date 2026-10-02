import type { Context } from '@deepseek-ai/cordis'
import { HKUAgentsAPIError, type HKUAgentsClient, type JsonValue } from './client.js'
import { testHistory, type TestHistory } from './history.js'

const operations = new Set(['dates', 'availability', 'preview', 'booking_prepare', 'booking_execute', 'booking_result',
  'shadow_status', 'shadow_preview', 'shadow_create', 'shadow_rules', 'shadow_action', 'shadow_runs', 'shadow_feedback',
  'f4_draft_preview', 'f4_draft_create', 'f4_drafts', 'f4_draft_revoke', 'f4_authorization_preview',
  'f4_authorization_create', 'f4_authorizations', 'f4_authorization_action',
  'f4_executor_status', 'f4_executor_configure', 'f4_authorization_arm', 'booking_gate_status', 'booking_gate_configure'])
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
// Project only named business fields. Tokens, raw DOM, generic capability
// manifests, and arbitrary exception messages never enter this operator panel.
const fields = new Set(['id', 'state', 'phase', 'ready', 'reason', 'date', 'target_date', 'floor', 'room',
  'armed', 'arming_digest', 'dry_run',
  'target', 'policy', 'booking_policy', 'policy_basis', 'policy_sources', 'equipment', 'eligible_categories',
  'draft', 'current_hong_kong_time', 'seconds_until_execution', 'next_preparation_at', 'prepare_at_local',
  'session_duration_minutes', 'maximum_minutes_per_day', 'minimum_patron_count', 'advance_booking',
  'check_in_required', 'release_after_minutes', 'session_windows', 'day_group', 'windows', 'seasonal_notes',
  'available_session_windows_per_weekday', 'available_session_windows_per_weekend_or_holiday', 'maximum_active_sessions',
  'checks_start_at_local', 'stop_at_local', 'maximum_date_checks', 'maximum_active_rules', 'maximum_lifetime_days',
  'eligibility', 'category', 'supported_by_published_policy', 'basis', 'eligibility_basis',
  'effect', 'discussion_room_rules_attestation', 'external_submission_enabled', 'discussion_room_rules_acknowledged',
  'facility_rules_acknowledged', 'policy_acceptance_acknowledged', 'capability_version',
  'start_time', 'end_time', 'facility_type', 'location', 'booking_facility_type', 'eligibility_category',
  'preview_digest', 'rule_preview_digest', 'preview_expires_at', 'preview', 'exact_target', 'pilot_scope',
  'policy_digest', 'facility_policy_digest', 'policy_verified_on', 'policy_verified_on', 'warnings', 'unmet_gates',
  'enabled', 'scheduler_running', 'shadow_only', 'booking_authority', 'execution_enabled', 'next_run_at',
  'next_scheduled_check_at', 'next_scheduled_check_at_local', 'next_check_at', 'created_at', 'updated_at',
  'expires_at', 'execution_at', 'prepare_at', 'stop_at', 'poll_interval_seconds', 'max_date_checks',
  'rule_count', 'rules', 'rule', 'run_count', 'runs', 'run_id', 'rule_id', 'scheduled_at', 'scheduled_at_local',
  'started_at', 'completed_at', 'outcome', 'error_code', 'candidate_count', 'candidates', 'candidate_id',
  'suggested_candidate_id', 'feedback_state', 'choice_agreement', 'date_check_count', 'last_offered_dates',
  'preparation_completed', 'task_id', 'correlation_id', 'result', 'booking_writes_performed',
  'booking_success_verified', 'submission_requested', 'booking_result_verified', 'booking_record',
  'booking_reference', 'booking_id', 'status', 'submission_outcome', 'offered_dates', 'date_option_count',
  'available_slots', 'available_slot_count', 'availability_observed_at', 'preview_expires_at', 'max_runs',
  'room_preference_order', 'session_preference_order', 'allow_room_fallback', 'allow_time_fallback',
  'maximum_successful_bookings', 'attempt_count', 'success_count', 'authorizations', 'authorization_count',
  'drafts', 'draft_count', 'standing_authorization_created', 'unattended_submission_enabled',
  'domain_writes_performed', 'read_only', 'stop_at_hong_kong', 'prepare_at_hong_kong', 'checks_start_at_hong_kong',
  'submit_clicks_dispatched', 'confirmation_source', 'booking_success_notice_verified',
  'exact_target_verified_in_booking_form', 'exact_target_verified_in_booking_record', 'record_match_count',
  'duration_minutes', 'max_sessions_per_day', 'max_minutes_per_day', 'minimum_group_size', 'interleaving_rule',
  'advance_days', 'maximum_duration_minutes', 'maximum_sessions_per_day', 'minimum_patrons', 'policy_acceptance_required'])

export function projectLibrary(value: unknown, depth = 0): unknown {
  if (depth > 7) return null
  if (value === null || typeof value === 'boolean') return value
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string') return value.replace(/[<>\r\n]/g, ' ').slice(0, 400)
  if (Array.isArray(value)) return value.slice(0, 100).map(v => projectLibrary(v, depth + 1))
  if (!object(value)) return null
  return Object.fromEntries(Object.entries(value).filter(([key]) => fields.has(key))
    .map(([key, item]) => [key, projectLibrary(item, depth + 1)]))
}

export function installDesktopLibraryBridge(ctx: Context, client: Pick<HKUAgentsClient, 'libraryOperator'>,
  history: Pick<TestHistory, 'append'> = testHistory): void {
  type Route = { path: string; methods: string[]; requestBody: 'buffered'; fetch(request: Request): Promise<Response> }
  const respond = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } })
  const route: Route = { path: '/api/hku-agents/library/operator', methods: ['POST'], requestBody: 'buffered',
    async fetch(request) {
      if (request.method !== 'POST') return respond({ error: 'method_not_allowed' }, 405)
      const text = await request.text()
      if (Buffer.byteLength(text) > 16384) return respond({ error: 'invalid_request' }, 400)
      let body: unknown
      try { body = JSON.parse(text) } catch { return respond({ error: 'invalid_request' }, 400) }
      if (!object(body) || Object.keys(body).sort().join(',') !== 'method,payload,rpcId,type' ||
          body.type !== 'client-request' || body.method !== 'hku-agents/library/operator' ||
          typeof body.rpcId !== 'string' || !/^[0-9a-f-]{36}$/i.test(body.rpcId) || !object(body.payload) ||
          Object.keys(body.payload).sort().join(',') !== 'input,operation' ||
          typeof body.payload.operation !== 'string' || !operations.has(body.payload.operation) ||
          !object(body.payload.input)) return respond({ error: 'invalid_request' }, 400)
      let value: unknown
      try {
        const result = await client.libraryOperator(body.payload.operation,
          body.payload.input as { [key: string]: JsonValue }, request.signal)
        if (!object(result) || result.ok !== true || result.operation !== body.payload.operation || !object(result.result)) {
          throw new Error('Invalid operator result')
        }
        value = { ok: true, operation: result.operation, result: projectLibrary(result.result),
          task_id: projectLibrary(result.task_id), correlation_id: projectLibrary(result.correlation_id),
          execution_enabled: result.execution_enabled === true }
      } catch (error) {
        const code = error instanceof HKUAgentsAPIError && /^[A-Z0-9_]{1,64}$/.test(error.code)
          ? error.code : 'LIBRARY_OPERATOR_FAILED'
        value = { ok: false, error: { code }, recovery: 'Check Core, policy/gate, exact inputs and preview expiry. Never retry an ambiguous submission.' }
      }
      if (object(value)) {
        const stage = body.payload.operation.startsWith('f4_') ? 'f4' : body.payload.operation.startsWith('shadow_')
          ? 'f3' : body.payload.operation.startsWith('booking_') ? 'f2' : 'f1'
        const result = object(value.result) ? value.result : {}
        try {
          value.history_record_id = await history.append(`library_operator_${stage}`, {
            ok: value.ok, task_id: value.task_id, correlation_id: value.correlation_id, error: value.error,
            domain_writes_performed: result.domain_writes_performed,
          })
        } catch { value.history_warning = 'HISTORY_UNAVAILABLE; operation result remains valid.' }
      }
      return respond({ type: 'server-response', rpcId: body.rpcId, result: { ok: true, value } })
    } }
  ctx.inject(['connection'], scope => {
    const host = scope as unknown as { connection: { fetch: { register(route: Route): () => void } } }
    scope.effect(() => host.connection.fetch.register(route))
  })
}
