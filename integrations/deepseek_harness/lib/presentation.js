const object = (v) => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v) => typeof v === 'string' ? v.replace(/[\r\n<>`]/g, ' ').slice(0, 120) : null;
const fields = ['term_label', 'meeting_count', 'course_count', 'assignment_count', 'notice_count', 'result_count',
    'available_slot_count', 'date_option_count', 'hours_available', 'location_count', 'ready', 'reason', 'complete', 'date'];
export function compactProjection(value) {
    const card = {};
    if (!object(value) || value.ok !== true || value.read_only !== true || !object(value.result)) {
        card.state = 'Result not verified';
        return card;
    }
    const r = value.result;
    card.state = 'Read completed — not a booking';
    const writes = ['domain_writes_performed', 'booking_writes_performed', 'moodle_writes_performed',
        'library_writes_performed', 'portal_writes_performed', 'enrollment_writes_performed', 'schedule_writes_performed'];
    const reported = writes.filter(k => r[k] !== undefined);
    card.domain_writes = reported.length && reported.every(k => r[k] === 0) ? '0' : 'not reported / not verified';
    for (const part of [r, r.timetable, r.course_list, r.assignment_list, r.notice_list]) {
        if (!object(part))
            continue;
        for (const key of fields) {
            const v = part[key];
            if (typeof v === 'number' && Number.isFinite(v) || typeof v === 'boolean')
                card[key] = v;
            else if (text(v))
                card[key] = text(v);
        }
        for (const key of ['fetched_at', 'observed_at', 'source_fetched_at']) {
            if (text(part[key]))
                card[key] = text(part[key]);
        }
    }
    if (Array.isArray(r.offered_dates))
        card.offered_dates = r.offered_dates.filter(d => typeof d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(d)).slice(0, 31).join(', ');
    if (object(r.next_class))
        card.next_class_starts_at = text(r.next_class.starts_at);
    if (object(r.source_status)) {
        for (const key of ['timetable', 'moodle_assignments', 'portal_notices']) {
            const source = r.source_status[key];
            if (object(source))
                card[`source_${key}`] = text(source.status);
        }
    }
    card.source = r.derived_locally === true ? 'Local cache / derived result' : 'Core read; freshness depends on operation';
    for (const key of ['source_fetched_at', 'availability_observed_at', 'observed_at', 'fetched_at']) {
        if (text(r[key]))
            card[key] = text(r[key]);
    }
    if (object(r.diagnostics))
        card.parser_version = text(r.diagnostics.parser_version);
    card.correlation_id = text(value.correlation_id);
    card.task_id = object(value.task) ? text(value.task.id) : null;
    return card;
}
export function toolPresentation(name) {
    const title = name.replace(/^hku_/, 'HKU · ').replaceAll('_', ' ');
    return {
        presentCall() { return { card: 'generic', title, kind: 'read', content: [{ type: 'text', text: 'Reading through HKU Core. Navigation may occur; no booking authority is granted.' }] }; },
        presentResult(_args, result) {
            if (result.isError)
                return { card: 'generic', title: `${title} · failed`, content: [{ type: 'text', text: 'Read failed. Check the error code, connection and HKU login; do not treat this as an empty result. Inspect Admin diagnostics.' }] };
            const meta = object(result.meta) ? result.meta : { state: 'Summary unavailable — review Agent response' };
            const lines = Object.entries(meta).map(([k, v]) => `${k.replaceAll('_', ' ')}: ${text(String(v ?? 'unknown'))}`);
            if (/timetable|next_class|free_slots/.test(name))
                lines.push('Weekly recurrence only; holidays and teaching weeks are not verified.');
            if (/moodle/.test(name))
                lines.push('Visible Dashboard data only; this is not a complete audit of every course activity.');
            if (/booking_preview/.test(name))
                lines.push('A ready preview is not a reservation and grants no booking authority.');
            return { card: 'generic', title, content: [{ type: 'text', text: lines.join('\n') }] };
        }
    };
}
//# sourceMappingURL=presentation.js.map