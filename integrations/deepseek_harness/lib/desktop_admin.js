import { HKUAgentsAPIError } from './client.js';
export const DESKTOP_FACILITIES_PATH = '/api/hku-agents/admin/facilities';
const RPC_METHOD = 'hku-agents/admin/facilities';
function isRecord(value) {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function boundedString(value, limit = 120) {
    return typeof value === 'string' && value.length <= limit ? value : null;
}
function boundedCount(value) {
    return Number.isInteger(value) && typeof value === 'number' && value >= 0 && value <= 100 ? value : null;
}
function parseRequest(text) {
    if (Buffer.byteLength(text, 'utf8') > 2048)
        return null;
    let value;
    try {
        value = JSON.parse(text);
    }
    catch {
        return null;
    }
    if (!isRecord(value) || Object.keys(value).sort().join(',') !== 'method,payload,rpcId,type')
        return null;
    if (value.type !== 'client-request' || value.method !== RPC_METHOD)
        return null;
    if (typeof value.rpcId !== 'string' || !/^[0-9a-f-]{36}$/i.test(value.rpcId))
        return null;
    if (!isRecord(value.payload) || Object.keys(value.payload).length !== 0)
        return null;
    return value.rpcId;
}
function projectFacility(value) {
    if (!isRecord(value))
        return null;
    const facility_type = boundedString(value.facility_type, 64);
    const name = boundedString(value.name);
    const location = boundedString(value.location);
    if (facility_type === null || name === null || location === null)
        return null;
    return { facility_type, name, location };
}
function projectTarget(value) {
    if (!isRecord(value))
        return null;
    const facility_type = boundedString(value.facility_type, 64);
    const location = boundedString(value.location);
    const booking_facility_type = boundedString(value.booking_facility_type);
    if (facility_type === null || location === null || booking_facility_type === null)
        return null;
    if (value.availability_search_supported !== true)
        return null;
    if (typeof value.booking_preview_supported !== 'boolean' || typeof value.supervised_booking_supported !== 'boolean')
        return null;
    return {
        facility_type,
        location,
        booking_facility_type,
        availability_search_supported: true,
        booking_preview_supported: value.booking_preview_supported,
        supervised_booking_supported: value.supervised_booking_supported,
    };
}
export async function readDesktopFacilities(client, signal) {
    try {
        const envelope = await client.listLibraryFacilities(signal);
        const result = envelope.result;
        if (!isRecord(result) || result.read_only !== true || result.browser_interactions_performed !== false ||
            result.domain_writes_performed !== 0 || result.library_writes_performed !== 0 || result.booking_writes_performed !== 0 ||
            result.slot_selection_performed !== false || result.booking_form_opened !== false) {
            throw new Error('Unexpected facility catalog response');
        }
        if (!Array.isArray(result.facilities) || !Array.isArray(result.availability_targets) || result.facilities.length > 30 || result.availability_targets.length > 30) {
            throw new Error('Unexpected facility catalog size');
        }
        const facilities = result.facilities.map(projectFacility);
        const targets = result.availability_targets.map(projectTarget);
        const facility_count = boundedCount(result.facility_count);
        const availability_target_count = boundedCount(result.availability_target_count);
        if (facilities.includes(null) || targets.includes(null) || facility_count !== facilities.length || availability_target_count !== targets.length) {
            throw new Error('Incomplete facility catalog projection');
        }
        return {
            ok: true,
            read_only: true,
            derived_locally: true,
            browser_interactions_performed: false,
            booking_writes_performed: 0,
            facility_count,
            availability_target_count,
            facilities,
            availability_targets: targets,
            policy_verified_on: boundedString(result.policy_verified_on, 32),
            correlation_id: boundedString(envelope.correlation_id, 64),
        };
    }
    catch (error) {
        const rawCode = error instanceof HKUAgentsAPIError ? error.code : 'INVALID_CATALOG_RESPONSE';
        const code = /^[A-Z][A-Z0-9_]{0,63}$/.test(rawCode) ? rawCode : 'CATALOG_READ_FAILED';
        return {
            ok: false,
            read_only: true,
            error: {
                code,
                recovery: code === 'TOKEN_NOT_CONFIGURED'
                    ? 'Restart the updated HKU AGENTS service once to initialize automatic connection.'
                    : 'Check the local HKU AGENTS Core, then run this read-only test again.',
            },
            correlation_id: null,
        };
    }
}
function jsonResponse(value, status = 200) {
    return new Response(JSON.stringify(value), {
        status,
        headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
    });
}
export function desktopFacilitiesRoute(client) {
    return {
        path: DESKTOP_FACILITIES_PATH,
        methods: ['POST'],
        requestBody: 'buffered',
        async fetch(request) {
            if (request.method !== 'POST')
                return jsonResponse({ error: 'method_not_allowed' }, 405);
            const declaredLength = Number(request.headers.get('content-length') ?? '0');
            if (Number.isFinite(declaredLength) && declaredLength > 2048)
                return jsonResponse({ error: 'invalid_request' }, 400);
            const rpcId = parseRequest(await request.text());
            if (rpcId === null)
                return jsonResponse({ error: 'invalid_request' }, 400);
            const value = await readDesktopFacilities(client, request.signal);
            return jsonResponse({ type: 'server-response', rpcId, result: { ok: true, value } });
        },
    };
}
export function installDesktopAdminBridge(ctx, client) {
    ctx.inject(['connection'], connectionContext => {
        const connection = connectionContext.connection;
        return connection.fetch.register(desktopFacilitiesRoute(client));
    });
}
//# sourceMappingURL=desktop_admin.js.map