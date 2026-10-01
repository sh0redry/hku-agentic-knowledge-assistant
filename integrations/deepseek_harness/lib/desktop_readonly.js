import { HKUAgentsAPIError } from './client.js';
const FACILITIES = new Set([
    'single_study_room', 'av_group_viewing_room', 'communal_virtual_pc', 'computer',
    'computer_in_lic', 'engraving_cutting_computer', 'concept_and_creation_room',
    'discussion_room', 'microform_scanner', 'overhead_scanner', 'research_desk',
    'studio_editing_room', 'study_table', 'study_table_deep_quiet', 'study_room',
]);
export const ADMIN_READ_OPERATIONS = [
    'timetable_sync', 'next_class', 'moodle_dashboard', 'moodle_courses',
    'moodle_assignments', 'portal_notices', 'briefing', 'library_hours',
    'library_dates', 'library_availability', 'library_research',
];
function record(value) {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function str(value, max = 120) {
    return typeof value === 'string' && value.length <= max ? value : null;
}
function count(value, max = 1000) {
    return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= max ? value : null;
}
function term(value) {
    return typeof value === 'string' && /^\d{4}-\d{2} Sem [12]$/.test(value);
}
function validateInput(operation, value) {
    if (!record(value))
        return null;
    const keys = Object.keys(value).sort().join(',');
    switch (operation) {
        case 'timetable_sync':
        case 'next_class':
            return keys === 'term_label' && term(value.term_label) ? { term_label: value.term_label } : null;
        case 'moodle_assignments':
            return keys === 'days_ahead' && typeof value.days_ahead === 'number' && Number.isInteger(value.days_ahead) && value.days_ahead >= 1 && value.days_ahead <= 90
                ? { days_ahead: value.days_ahead } : null;
        case 'library_dates':
            return keys === 'facility_type' && FACILITIES.has(value.facility_type)
                ? { facility_type: value.facility_type } : null;
        case 'library_availability':
            return keys === 'date,facility_type' && FACILITIES.has(value.facility_type) &&
                typeof value.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value.date)
                ? { facility_type: value.facility_type, date: value.date } : null;
        case 'library_research':
            return keys === 'query' && typeof value.query === 'string' && value.query.trim().length >= 2 && value.query.trim().length <= 200
                ? { query: value.query.trim() } : null;
        default:
            return keys === '' ? {} : null;
    }
}
function parseRequest(text, operation) {
    if (Buffer.byteLength(text, 'utf8') > 4096)
        return null;
    let value;
    try {
        value = JSON.parse(text);
    }
    catch {
        return null;
    }
    if (!record(value) || Object.keys(value).sort().join(',') !== 'method,payload,rpcId,type' ||
        value.type !== 'client-request' || value.method !== `hku-agents/admin/read/${operation}` ||
        typeof value.rpcId !== 'string' || !/^[0-9a-f-]{36}$/i.test(value.rpcId))
        return null;
    const payload = validateInput(operation, value.payload);
    return payload === null ? null : { rpcId: value.rpcId, payload };
}
function safeResult(value) {
    if (!record(value) || value.read_only !== true || value.domain_writes_performed !== 0)
        return false;
    for (const key of ['sis_write_requests_sent', 'enrollment_writes_performed', 'schedule_writes_performed',
        'moodle_writes_performed', 'portal_writes_performed', 'library_writes_performed', 'booking_writes_performed']) {
        if (value[key] !== undefined && value[key] !== 0)
            return false;
    }
    if (value.slot_selection_performed !== undefined && value.slot_selection_performed !== false)
        return false;
    if (value.booking_form_opened !== undefined && value.booking_form_opened !== false)
        return false;
    return true;
}
function summary(operation, result) {
    switch (operation) {
        case 'timetable_sync': {
            const timetable = result.timetable;
            if (!record(timetable) || !term(timetable.term_label))
                return null;
            const meeting_count = count(timetable.meeting_count);
            return meeting_count === null ? null : { term_label: timetable.term_label, meeting_count, cache_scope: str(timetable.cache_scope, 40) };
        }
        case 'next_class': {
            if (result.derived_locally !== true || result.browser_interactions_performed !== false || !term(result.term_label))
                return null;
            const next = result.next_class;
            if (next !== null && !record(next))
                return null;
            return { term_label: result.term_label, next_class_found: next !== null, next_class_starts_at: record(next) ? str(next.starts_at, 40) : null,
                source_fetched_at: str(result.source_fetched_at, 40), projection_warning: 'Weekly recurrence only; holidays and teaching weeks are not verified.' };
        }
        case 'moodle_dashboard':
            return result.course_data_read === false && result.assignment_data_read === false
                ? { dashboard_ready: true, navigation_interactions_performed: result.navigation_interactions_performed === true } : null;
        case 'moodle_courses': {
            const list = result.course_list;
            const course_count = record(list) ? count(list.course_count, 200) : null;
            return course_count === null ? null : { course_count, private_rows_omitted: true };
        }
        case 'moodle_assignments': {
            const list = result.assignment_list;
            const assignment_count = record(list) ? count(list.assignment_count) : null;
            return assignment_count === null ? null : { assignment_count, private_rows_omitted: true };
        }
        case 'portal_notices': {
            if (result.navigation_interactions_performed !== false)
                return null;
            const list = result.notice_list;
            const notice_count = record(list) ? count(list.notice_count, 500) : null;
            return notice_count === null ? null : { notice_count, private_rows_omitted: true };
        }
        case 'briefing': {
            if (result.derived_locally !== true || result.browser_interactions_performed !== false || typeof result.complete !== 'boolean')
                return null;
            const sources = result.source_status;
            if (!record(sources))
                return null;
            const names = ['timetable', 'moodle_assignments', 'portal_notices'];
            const status = {};
            for (const name of names) {
                const item = sources[name];
                if (!record(item) || typeof item.status !== 'string' || !['ready', 'missing', 'stale', 'term_mismatch', 'insufficient_coverage'].includes(item.status))
                    return null;
                status[name] = item.status;
            }
            return { complete: result.complete, source_status: status, private_rows_omitted: true };
        }
        case 'library_hours': {
            if (typeof result.hours_available !== 'boolean')
                return null;
            const location_count = count(result.location_count, 200);
            return location_count === null ? null : { hours_available: result.hours_available, location_count, period_rows_omitted: true };
        }
        case 'library_dates': {
            if (result.booking_writes_performed !== 0 || result.availability_search_submitted !== false || result.slot_selection_performed !== false)
                return null;
            const dates = result.offered_dates;
            if (!Array.isArray(dates) || dates.length > 31 || dates.some(item => typeof item !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(item)))
                return null;
            const date_option_count = count(result.date_option_count, 31);
            return date_option_count === dates.length ? { facility_type: str(result.facility_type, 64), offered_dates: dates, date_option_count } : null;
        }
        case 'library_availability': {
            if (result.booking_writes_performed !== 0 || result.slot_selection_performed !== false || result.booking_form_opened !== false || result.result_set_complete !== true)
                return null;
            const available_slot_count = count(result.available_slot_count);
            return available_slot_count === null ? null : { facility_type: str(result.facility_type, 64), date: str(result.date, 10), available_slot_count,
                result_pages_read: count(result.result_pages_read, 10), exact_slots_omitted: true };
        }
        case 'library_research': {
            const result_count = count(result.result_count, 20);
            return result_count === null ? null : { result_count, bibliographic_rows_omitted: true };
        }
    }
}
async function execute(client, operation, payload, signal) {
    switch (operation) {
        case 'timetable_sync': return client.syncWeeklyTimetable(payload, signal);
        case 'next_class': return client.nextClass(payload, signal);
        case 'moodle_dashboard': return client.inspectMoodleDashboard(signal);
        case 'moodle_courses': return client.listMoodleCourses(signal);
        case 'moodle_assignments': return client.listUpcomingMoodleAssignments(payload, signal);
        case 'portal_notices': return client.listPortalNotices(signal);
        case 'briefing': return client.dailyBriefing({}, signal);
        case 'library_hours': return client.libraryHoursAndLocations(signal);
        case 'library_dates': return client.listLibrarySpaceDates(payload, signal);
        case 'library_availability': return client.searchLibrarySpaceAvailability(payload, signal);
        case 'library_research': return client.searchLibraryResearch(payload, signal);
    }
}
function failure(error) {
    const raw = error instanceof HKUAgentsAPIError ? error.code : 'INVALID_READ_RESPONSE';
    const code = /^[A-Z][A-Z0-9_]{0,63}$/.test(raw) ? raw : 'READ_FAILED';
    return { ok: false, read_only: true, error: { code,
            recovery: code === 'TOKEN_NOT_CONFIGURED' ? 'Restart the updated HKU AGENTS service once to initialize automatic connection.'
                : 'Check Core, Chrome Bridge, the relevant HKU login and exact input, then retry this read-only test.' }, correlation_id: null };
}
export async function readDesktopOperation(client, operation, payload, signal) {
    try {
        const envelope = await execute(client, operation, payload, signal);
        if (!safeResult(envelope.result))
            throw new Error('Unexpected read-only result');
        const projected = summary(operation, envelope.result);
        if (!projected)
            throw new Error('Incomplete read-only projection');
        return { ok: true, read_only: true, domain_writes_performed: 0, operation, summary: projected,
            task_id: record(envelope.task) ? str(envelope.task.id, 64) : null,
            correlation_id: str(envelope.correlation_id, 64) };
    }
    catch (error) {
        return failure(error);
    }
}
function jsonResponse(value, status = 200) {
    return new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });
}
export function desktopReadRoute(client, operation) {
    const path = `/api/hku-agents/admin/read/${operation}`;
    return { path, methods: ['POST'], requestBody: 'buffered', async fetch(request) {
            if (request.method !== 'POST')
                return jsonResponse({ error: 'method_not_allowed' }, 405);
            const declaredLength = Number(request.headers.get('content-length') ?? '0');
            if (Number.isFinite(declaredLength) && declaredLength > 4096)
                return jsonResponse({ error: 'invalid_request' }, 400);
            const parsed = parseRequest(await request.text(), operation);
            if (!parsed)
                return jsonResponse({ error: 'invalid_request' }, 400);
            const value = await readDesktopOperation(client, operation, parsed.payload, request.signal);
            return jsonResponse({ type: 'server-response', rpcId: parsed.rpcId, result: { ok: true, value } });
        } };
}
export function installDesktopReadBridge(ctx, client) {
    ctx.inject(['connection'], connectionContext => {
        const connection = connectionContext.connection;
        const disposers = ADMIN_READ_OPERATIONS.map(operation => connection.fetch.register(desktopReadRoute(client, operation)));
        return () => { for (const dispose of disposers.reverse())
            dispose(); };
    });
}
//# sourceMappingURL=desktop_readonly.js.map