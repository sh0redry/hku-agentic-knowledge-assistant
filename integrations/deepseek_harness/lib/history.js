import { randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile, rename, lstat } from 'node:fs/promises';
import { join } from 'node:path';
const operations = new Set(['timetable_sync', 'next_class', 'moodle_dashboard', 'moodle_courses', 'moodle_assignments',
    'portal_notices', 'briefing', 'library_hours', 'library_dates', 'library_availability', 'library_research', 'sis_sync', 'sis_preflight', 'facilities']);
const verdicts = new Set(['pending', 'pass', 'fail', 'needs_review']);
const obj = (v) => !!v && typeof v === 'object' && !Array.isArray(v);
const id = (v) => typeof v === 'string' && /^[a-zA-Z0-9-]{1,64}$/.test(v) ? v : null;
export function safeDiagnostics(value) {
    const out = {};
    if (!obj(value))
        return out;
    for (const [key, item] of Object.entries(value)) {
        if (key === 'parser_version' && typeof item === 'string' && /^\d+\.\d+\.\d+$/.test(item))
            out[key] = item;
        else if (/^[a-z_]+_(count|found|complete)$/.test(key) && (typeof item === 'boolean' || typeof item === 'number' && Number.isInteger(item) && item >= 0 && item <= 100000))
            out[key] = item;
    }
    return out;
}
export class TestHistory {
    path;
    queue = Promise.resolve();
    constructor(path = join(process.env.USERPROFILE || process.env.HOME || '.', '.hku-agents', 'desktop-test-history-v1.json')) {
        this.path = path;
    }
    serial(job) {
        const next = this.queue.then(job, job);
        this.queue = next.catch(() => { });
        return next;
    }
    async read() {
        let stat;
        try {
            stat = await lstat(this.path);
        }
        catch (e) {
            if (e.code === 'ENOENT')
                return [];
            throw e;
        }
        if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 256000)
            throw new Error('Invalid history store');
        const value = JSON.parse(await readFile(this.path, 'utf8'));
        if (!Array.isArray(value) || value.length > 100 || value.some(r => !obj(r) || !id(r.id) || !operations.has(String(r.operation)) ||
            !verdicts.has(String(r.verdict)) || !['completed', 'failed'].includes(String(r.outcome)) ||
            typeof r.recorded_at !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(r.recorded_at) || !Number.isFinite(Date.parse(r.recorded_at)) ||
            typeof r.plugin_version !== 'string' || !/^\d+\.\d+\.\d+$/.test(r.plugin_version) || !obj(r.diagnostics) ||
            typeof r.host_runtime !== 'string' || !/^v\d+\.\d+\.\d+$/.test(r.host_runtime) || r.core_version !== null || r.extension_version !== null ||
            Object.keys(r).sort().join(',') !== 'core_version,correlation_id,diagnostics,domain_writes,error_code,extension_version,host_runtime,id,operation,outcome,plugin_version,recorded_at,task_id,verdict'))
            throw new Error('Invalid history store');
        // Re-project on read as well: modified files never become a raw-data channel.
        return value.map(r => ({ ...r, task_id: id(r.task_id), correlation_id: id(r.correlation_id),
            error_code: typeof r.error_code === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(r.error_code) ? r.error_code : null,
            domain_writes: r.domain_writes === '0' ? '0' : 'not_verified', diagnostics: safeDiagnostics(r.diagnostics) }));
    }
    async save(rows) {
        const dir = join(this.path, '..');
        await mkdir(dir, { recursive: true });
        if ((await lstat(dir)).isSymbolicLink())
            throw new Error('Invalid history directory');
        const temporary = `${this.path}.${randomUUID()}.tmp`;
        await writeFile(temporary, JSON.stringify(rows), { flag: 'wx', mode: 0o600 });
        await rename(temporary, this.path);
    }
    list() { return this.serial(() => this.read()); }
    append(operation, value) {
        return this.serial(async () => {
            if (!operations.has(operation) || !obj(value))
                throw new Error('Invalid history input');
            const rows = await this.read();
            const error = obj(value.error) ? value.error : {};
            const entry = { id: randomUUID(), operation, recorded_at: new Date().toISOString(), plugin_version: '0.18.14',
                outcome: value.ok === true ? 'completed' : 'failed', task_id: id(value.task_id), correlation_id: id(value.correlation_id),
                error_code: typeof error.code === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(error.code) ? error.code : null,
                verdict: 'pending', diagnostics: safeDiagnostics(value.diagnostics), domain_writes: value.domain_writes_performed === 0 ? '0' : 'not_verified',
                host_runtime: process.version, core_version: null, extension_version: null };
            await this.save([entry, ...rows].slice(0, 100));
            return entry.id;
        });
    }
    review(recordId, verdict) {
        return this.serial(async () => {
            if (!id(recordId) || !verdicts.has(verdict))
                throw new Error('Invalid verdict');
            const rows = await this.read();
            const row = rows.find(r => r.id === recordId);
            if (!row)
                throw new Error('Record not found');
            row.verdict = verdict;
            await this.save(rows);
        });
    }
}
export const testHistory = new TestHistory();
export function recordRoute(route, operation, history = testHistory) {
    return { ...route, async fetch(request) {
            const response = await route.fetch(request);
            if (!response.ok)
                return response;
            const body = await response.clone().json();
            const value = body?.result?.value;
            if (!obj(value))
                return response;
            try {
                value.history_record_id = await history.append(operation, value);
            }
            catch {
                value.history_warning = 'HISTORY_UNAVAILABLE — result remains valid; no history saved.';
            }
            return new Response(JSON.stringify(body), { status: response.status, headers: response.headers });
        } };
}
export function historyRoute(action, history = testHistory) {
    const path = `/api/hku-agents/admin/history/${action}`;
    return { path, methods: ['POST'], requestBody: 'buffered', async fetch(request) {
            const response = (result, status = 200) => new Response(JSON.stringify(result), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });
            if (request.method !== 'POST')
                return response({ error: 'method_not_allowed' }, 405);
            const raw = await request.text();
            if (raw.length > 2048)
                return response({ error: 'invalid_request' }, 400);
            let b;
            try {
                b = JSON.parse(raw);
            }
            catch {
                return response({ error: 'invalid_request' }, 400);
            }
            if (!obj(b) || Object.keys(b).sort().join(',') !== 'method,payload,rpcId,type' || b.type !== 'client-request' ||
                b.method !== `hku-agents/admin/history/${action}` || !id(b.rpcId) || !obj(b.payload))
                return response({ error: 'invalid_request' }, 400);
            const payload = b.payload;
            if (action === 'list' ? Object.keys(payload).length !== 0 : Object.keys(payload).sort().join(',') !== 'id,verdict' || !id(payload.id) || !verdicts.has(String(payload.verdict)))
                return response({ error: 'invalid_request' }, 400);
            try {
                if (action === 'review')
                    await history.review(String(payload.id), String(payload.verdict));
                return response({ type: 'server-response', rpcId: b.rpcId, result: { ok: true, value: { ok: true, local_only: true, records: await history.list() } } });
            }
            catch {
                return response({ type: 'server-response', rpcId: b.rpcId, result: { ok: true, value: { ok: false, error: { code: 'HISTORY_UNAVAILABLE' } } } });
            }
        } };
}
//# sourceMappingURL=history.js.map