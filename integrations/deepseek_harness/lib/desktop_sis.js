import { HKUAgentsAPIError } from './client.js';
export const DESKTOP_SIS_SYNC_PATH = '/api/hku-agents/admin/sis/sync';
export const DESKTOP_SIS_PREFLIGHT_PATH = '/api/hku-agents/admin/sis/preflight';
function record(value) {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function bounded(value, length = 80) {
    return typeof value === 'string' && value.length <= length ? value : null;
}
function count(value) {
    return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 200 ? value : null;
}
function course(value, concrete) {
    if (!record(value) || typeof value.course_code !== 'string' || typeof value.section !== 'string')
        return null;
    if (!/^[A-Z]{2,8}\d{3,5}[A-Z]?$/.test(value.course_code) || !/^[A-Z0-9-]{1,40}$/.test(value.section))
        return null;
    if (concrete) {
        if (typeof value.class_number !== 'string' || !/^\d{3,8}$/.test(value.class_number))
            return null;
        return { course_code: value.course_code, section: value.section, class_number: value.class_number };
    }
    return { course_code: value.course_code, section: value.section };
}
function courses(value, concrete, maximum = 200) {
    if (!Array.isArray(value) || value.length > maximum)
        return null;
    const items = value.map(item => course(item, concrete));
    return items.includes(null) ? null : items;
}
function requestPayload(text, method) {
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
        value.type !== 'client-request' || value.method !== method ||
        typeof value.rpcId !== 'string' || !/^[0-9a-f-]{36}$/i.test(value.rpcId) || !record(value.payload))
        return null;
    return { rpcId: value.rpcId, payload: value.payload };
}
function expected(payload) {
    if (Object.keys(payload).sort().join(',') !== 'expected_courses,term_label' ||
        typeof payload.term_label !== 'string' || !/^\d{4}-\d{2} Sem [12]$/.test(payload.term_label))
        return null;
    const items = courses(payload.expected_courses, false, 20);
    if (!items || items.length < 1)
        return null;
    const keys = items.map(item => `${item.course_code}:${item.section}`);
    if (new Set(keys).size !== keys.length)
        return null;
    return { term_label: payload.term_label, expected_courses: items };
}
function failure(error, fallback) {
    const raw = error instanceof HKUAgentsAPIError ? error.code : fallback;
    const code = /^[A-Z][A-Z0-9_]{0,63}$/.test(raw) ? raw : fallback;
    return {
        ok: false, read_only: true,
        error: {
            code,
            recovery: code === 'TOKEN_NOT_CONFIGURED'
                ? 'Restart the updated HKU AGENTS service once to initialize automatic connection.'
                : code === 'WRONG_SIS_PAGE'
                    ? 'Open the authenticated SIS Temporary Course List in Chrome, then retry.'
                    : 'Check the local Core, Chrome Bridge and SIS login, then retry this read-only test.',
        },
        correlation_id: null,
    };
}
export async function readDesktopSISSync(client, signal) {
    try {
        const envelope = await client.syncCourseLists(signal);
        const result = envelope.result;
        if (!record(result) || result.bound !== true || result.origin !== 'https://sis-main.hku.hk' ||
            result.logged_in !== true || result.page_kind !== 'cart' || result.read_only === false ||
            (result.sis_write_requests_sent !== undefined && result.sis_write_requests_sent !== 0) ||
            (result.enrollment_writes_performed !== undefined && result.enrollment_writes_performed !== 0))
            throw new Error('Unexpected SIS page');
        const temporary_courses = courses(result.temporary_courses, true);
        const schedule_courses = courses(result.schedule_courses, true);
        const diagnostics = result.diagnostics;
        if (!temporary_courses || !schedule_courses || !record(diagnostics) ||
            count(result.temporary_course_count) !== temporary_courses.length ||
            count(result.schedule_course_count) !== schedule_courses.length ||
            count(diagnostics.unclassified_candidate_count) !== 0)
            throw new Error('Incomplete SIS snapshot');
        return {
            ok: true, read_only: true, sis_write_requests_sent: 0,
            term_label: bounded(result.term_label),
            temporary_course_count: temporary_courses.length,
            schedule_course_count: schedule_courses.length,
            temporary_courses, schedule_courses,
            diagnostics: {
                parser_version: bounded(diagnostics.parser_version, 20),
                temporary_candidate_count: count(diagnostics.temporary_candidate_count),
                schedule_candidate_count: count(diagnostics.schedule_candidate_count),
                unclassified_candidate_count: 0,
            },
            correlation_id: bounded(envelope.correlation_id, 64),
        };
    }
    catch (error) {
        return failure(error, 'INVALID_SIS_SYNC_RESPONSE');
    }
}
export async function readDesktopSISPreflight(client, input, signal) {
    try {
        const envelope = await client.preflight(input, signal);
        const result = envelope.result;
        if (!record(result) || result.read_only !== true || result.simulated !== false || result.sis_write_requests_sent !== 0 ||
            (result.enrollment_writes_performed !== undefined && result.enrollment_writes_performed !== 0) ||
            typeof result.ready !== 'boolean' || result.page_kind !== 'cart' || result.requested_term_label !== input.term_label ||
            typeof result.term_match !== 'boolean' || result.ok !== result.ready)
            throw new Error('Unexpected SIS preflight');
        const matched_courses = courses(result.matched_courses, true, 50);
        const missing_courses = courses(result.missing_courses, false, 50);
        const unexpected_courses = courses(result.unexpected_courses, true, 50);
        if (!matched_courses || !missing_courses || !unexpected_courses || !Array.isArray(result.issues) ||
            result.issues.length > 10 || result.issues.some(item => typeof item !== 'string' || item.length > 160))
            throw new Error('Incomplete SIS preflight');
        return {
            ok: true, read_only: true, sis_write_requests_sent: 0,
            ready: result.ready, term_match: result.term_match,
            requested_term_label: input.term_label, observed_term_label: bounded(result.term_label),
            matched_courses, missing_courses, unexpected_courses,
            issues: result.issues,
            task_id: record(envelope.task) ? bounded(envelope.task.id, 64) : null,
            correlation_id: bounded(envelope.correlation_id, 64),
        };
    }
    catch (error) {
        return failure(error, 'INVALID_SIS_PREFLIGHT_RESPONSE');
    }
}
function jsonResponse(value, status = 200) {
    return new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });
}
function route(path, method, run) {
    return {
        path, methods: ['POST'], requestBody: 'buffered',
        async fetch(request) {
            if (request.method !== 'POST')
                return jsonResponse({ error: 'method_not_allowed' }, 405);
            const declaredLength = Number(request.headers.get('content-length') ?? '0');
            if (Number.isFinite(declaredLength) && declaredLength > 4096)
                return jsonResponse({ error: 'invalid_request' }, 400);
            const parsed = requestPayload(await request.text(), method);
            if (!parsed)
                return jsonResponse({ error: 'invalid_request' }, 400);
            if (method.endsWith('/sync') && Object.keys(parsed.payload).length !== 0)
                return jsonResponse({ error: 'invalid_request' }, 400);
            const input = method.endsWith('/preflight') ? expected(parsed.payload) : null;
            if (method.endsWith('/preflight') && !input)
                return jsonResponse({ error: 'invalid_request' }, 400);
            const value = await run(input ?? {}, request.signal);
            return jsonResponse({ type: 'server-response', rpcId: parsed.rpcId, result: { ok: true, value } });
        },
    };
}
export function desktopSISSyncRoute(client) {
    return route(DESKTOP_SIS_SYNC_PATH, 'hku-agents/admin/sis/sync', (_payload, signal) => readDesktopSISSync(client, signal));
}
export function desktopSISPreflightRoute(client) {
    return route(DESKTOP_SIS_PREFLIGHT_PATH, 'hku-agents/admin/sis/preflight', (payload, signal) => readDesktopSISPreflight(client, payload, signal));
}
export function installDesktopSISBridge(ctx, client) {
    ctx.inject(['connection'], connectionContext => {
        const connection = connectionContext.connection;
        const disposeSync = connection.fetch.register(desktopSISSyncRoute(client));
        const disposePreflight = connection.fetch.register(desktopSISPreflightRoute(client));
        return () => { disposePreflight(); disposeSync(); };
    });
}
//# sourceMappingURL=desktop_sis.js.map