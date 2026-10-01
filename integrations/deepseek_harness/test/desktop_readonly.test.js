import assert from 'node:assert/strict'
import test from 'node:test'

import { ADMIN_READ_OPERATIONS, desktopReadRoute } from '../lib/desktop_readonly.js'
import { HKUAgentsAPIError } from '../lib/client.js'

const rpcId = '12345678-1234-4123-8123-123456789abc'
function request(route, payload = {}) {
  return new Request(`http://desktop.local${route.path}`, {
    method: 'POST',
    body: JSON.stringify({ type: 'client-request', rpcId, method: route.path.slice('/api/'.length), payload }),
  })
}
function envelope(result) { return { correlation_id: 'safe-id', task: { id: 'task-id' }, result: { read_only: true, domain_writes_performed: 0, ...result } } }

const samples = {
  timetable_sync: ['syncWeeklyTimetable', { term_label: '2026-27 Sem 1' }, { timetable: { term_label: '2026-27 Sem 1', meeting_count: 7, cache_scope: 'process_memory_only', meetings: [{ private: 'secret' }] }, schedule_writes_performed: 0 }],
  next_class: ['nextClass', { term_label: '2026-27 Sem 1' }, { term_label: '2026-27 Sem 1', derived_locally: true, browser_interactions_performed: false, next_class: { starts_at: '2026-10-01T10:00:00+08:00', course_code: 'PRIVATE' } }],
  moodle_dashboard: ['inspectMoodleDashboard', {}, { moodle_writes_performed: 0, course_data_read: false, assignment_data_read: false }],
  moodle_courses: ['listMoodleCourses', {}, { moodle_writes_performed: 0, course_list: { course_count: 2, courses: [{ name: 'PRIVATE' }] } }],
  moodle_assignments: ['listUpcomingMoodleAssignments', { days_ahead: 14 }, { moodle_writes_performed: 0, assignment_list: { assignment_count: 3, assignments: [{ title: 'PRIVATE' }] } }],
  portal_notices: ['listPortalNotices', {}, { portal_writes_performed: 0, navigation_interactions_performed: false, notice_list: { notice_count: 1, notices: [{ title: 'PRIVATE' }] } }],
  briefing: ['dailyBriefing', {}, { derived_locally: true, browser_interactions_performed: false, complete: false, source_status: { timetable: { status: 'ready' }, moodle_assignments: { status: 'missing' }, portal_notices: { status: 'stale' } }, upcoming_assignments: [{ title: 'PRIVATE' }] }],
  library_hours: ['libraryHoursAndLocations', {}, { library_writes_performed: 0, hours_available: true, location_count: 5, locations: [{ name: 'PRIVATE' }] }],
  library_dates: ['listLibrarySpaceDates', { facility_type: 'discussion_room' }, { library_writes_performed: 0, booking_writes_performed: 0, availability_search_submitted: false, slot_selection_performed: false, facility_type: 'discussion_room', offered_dates: ['2026-10-01', '2026-10-02'], date_option_count: 2 }],
  library_availability: ['searchLibrarySpaceAvailability', { facility_type: 'discussion_room', date: '2026-10-01' }, { library_writes_performed: 0, booking_writes_performed: 0, slot_selection_performed: false, booking_form_opened: false, result_set_complete: true, facility_type: 'discussion_room', date: '2026-10-01', available_slot_count: 3, result_pages_read: 1, available_slots: [{ room: 'PRIVATE' }] }],
  library_research: ['searchLibraryResearch', { query: 'research' }, { library_writes_performed: 0, result_count: 2, results: [{ title: 'PRIVATE' }] }],
}

test('all fixed Admin read operations return bounded redacted summaries', async () => {
  assert.equal(ADMIN_READ_OPERATIONS.length, Object.keys(samples).length)
  for (const operation of ADMIN_READ_OPERATIONS) {
    const [method, payload, result] = samples[operation]
    let seen
    const route = desktopReadRoute({ async [method](input) { seen = input; return envelope(result) } }, operation)
    const response = await route.fetch(request(route, payload))
    const body = await response.json()
    assert.equal(response.status, 200)
    assert.equal(response.headers.get('cache-control'), 'no-store')
    assert.equal(body.result.value.ok, true, operation)
    assert.equal(body.result.value.operation, operation)
    assert.equal(body.result.value.domain_writes_performed, 0)
    assert.equal(body.result.value.correlation_id, 'safe-id')
    assert.doesNotMatch(JSON.stringify(body), /PRIVATE|secret/)
    if (Object.keys(payload).length) assert.deepEqual(JSON.parse(JSON.stringify(seen)), payload)
  }
})

test('Admin read routes reject unknown fields, invalid dates, and wrong RPC method before Core call', async () => {
  let calls = 0
  const client = { async listMoodleCourses() { calls++ }, async searchLibrarySpaceAvailability() { calls++ } }
  const courses = desktopReadRoute(client, 'moodle_courses')
  const availability = desktopReadRoute(client, 'library_availability')
  assert.equal((await courses.fetch(request(courses, { url: 'https://example.com' }))).status, 400)
  assert.equal((await availability.fetch(request(availability, { facility_type: 'discussion_room', date: 'tomorrow' }))).status, 400)
  assert.equal((await availability.fetch(request(availability, { facility_type: 'unknown', date: '2026-10-01' }))).status, 400)
  const wrong = new Request(`http://desktop.local${courses.path}`, { method: 'POST', body: JSON.stringify({ type: 'client-request', rpcId, method: 'hku-agents/admin/book', payload: {} }) })
  assert.equal((await courses.fetch(wrong)).status, 400)
  assert.equal(calls, 0)
})

test('Admin read projection rejects writes and incomplete responses', async () => {
  const route = desktopReadRoute({ async listMoodleCourses() { return envelope({ moodle_writes_performed: 1, course_list: { course_count: 2 } }) } }, 'moodle_courses')
  const body = await (await route.fetch(request(route))).json()
  assert.equal(body.result.value.ok, false)
  assert.equal(body.result.value.error.code, 'INVALID_READ_RESPONSE')
  const incomplete = desktopReadRoute({ async listMoodleCourses() { return envelope({ moodle_writes_performed: 0, course_list: {} }) } }, 'moodle_courses')
  const other = await (await incomplete.fetch(request(incomplete))).json()
  assert.equal(other.result.value.ok, false)
})

test('failed reads preserve task identifiers and only safe diagnostic counters', async () => {
  const route = desktopReadRoute({ async listMoodleCourses() {
    throw new HKUAgentsAPIError('MOODLE_COURSE_PARSE_INCOMPLETE', 'PRIVATE', { taskId: 'task-id', correlationId: 'correlation-id',
      diagnostics: { parser_version: '0.4.2', unparsed_course_candidate_count: 2, raw_dom: 'PRIVATE' } })
  } }, 'moodle_courses')
  const body = await (await route.fetch(request(route))).json()
  assert.equal(body.result.value.task_id, 'task-id')
  assert.equal(body.result.value.correlation_id, 'correlation-id')
  assert.deepEqual(body.result.value.diagnostics, { parser_version: '0.4.2', unparsed_course_candidate_count: 2 })
  assert.doesNotMatch(JSON.stringify(body), /PRIVATE|raw_dom/)
})
