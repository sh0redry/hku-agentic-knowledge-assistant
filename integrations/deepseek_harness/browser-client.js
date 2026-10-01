// Browser half for DeepSeek Harness Desktop 0.2.0-rc.2. The loader expects
// this module wrapper, not Node's ESM format. No API credential enters here.
window.__ModuleLoader__.load({
  id: 'dsh-hku-agents',
  factory: require => {
    const React = require('react')
    const h = React.createElement
    const PANEL_ID = 'hku-agents'
    const ADMIN_PANEL_ID = 'hku-agents-admin'
    const HKU_TOOL_NAMES = [
      'hku_sis_status', 'hku_sis_navigate_and_preflight', 'hku_sis_open_enrollment_add_classes',
      'hku_sis_sync_course_lists', 'hku_sis_preflight', 'hku_sis_timetable_sync', 'hku_sis_next_class',
      'hku_sis_find_free_slots', 'hku_sis_check_timetable_conflicts', 'hku_sis_exam_status',
      'hku_moodle_inspect_dashboard', 'hku_moodle_list_courses', 'hku_moodle_upcoming_assignments',
      'hku_portal_list_notices', 'hku_daily_briefing', 'hku_library_research_search',
      'hku_library_list_facilities', 'hku_library_hours_and_locations', 'hku_library_space_availability',
      'hku_library_space_dates', 'hku_library_space_booking_preview', 'hku_library_research_item',
      'hku_library_research_access_options',
    ]
    const SUMMARY_FIELDS = ['domain_writes', 'source', 'term_label', 'meeting_count', 'course_count',
      'assignment_count', 'notice_count', 'result_count', 'available_slot_count', 'date_option_count',
      'offered_dates', 'hours_available', 'location_count', 'ready', 'reason', 'complete', 'date',
      'next_class_starts_at', 'fetched_at', 'observed_at', 'source_fetched_at', 'availability_observed_at',
      'source_timetable', 'source_moodle_assignments', 'source_portal_notices', 'parser_version',
      'task_id', 'correlation_id']

    // Desktop rc.2 dispatches keyed client toolviews, not Host presentCall hooks.
    // Read only the durable, redacted metadata; never derive a summary from private content/arguments.
    function HKUToolCard({ toolName, phase, block, inspect }) {
      const done = phase === 'result'
      const failed = done && block?.isError === true
      const interrupted = failed && block?.error?.code === 'interrupted'
      const meta = block?.meta && typeof block.meta === 'object' && !Array.isArray(block.meta) ? block.meta : {}
      const verified = done && !failed && meta.state === 'Read completed — not a booking'
      const state = !done ? (phase === 'preparing' ? 'Preparing read…' : 'Reading…')
        : interrupted ? 'Read interrupted' : failed ? 'Read failed'
          : verified ? 'Read completed — not a booking' : 'Result not verified — view details'
      const rows = done && !failed ? SUMMARY_FIELDS.flatMap(key => {
        const value = meta[key]
        if (typeof value === 'string' && value.length <= 250 || typeof value === 'boolean' ||
            typeof value === 'number' && Number.isFinite(value)) return [[key, String(value)]]
        return []
      }) : []
      const error = failed && typeof block?.error?.code === 'string' && /^[A-Z0-9_]{1,64}$/.test(block.error.code)
        ? block.error.code : null
      return h('section', { style: { ...card, marginTop: 8, padding: 12 }, 'aria-label': 'HKU read-only tool result' },
        h('h3', { style: { fontSize: 15, margin: '0 0 6px' } }, `HKU · ${toolName.replace(/^hku_/, '').replaceAll('_', ' ')}`),
        h('p', { role: 'status', style: { margin: '4px 0' } }, state),
        error ? h('p', null, `Error: ${error}`) : null,
        h('dl', null, ...rows.map(([key, value]) => h('div', { key },
          h('dt', { style: { display: 'inline', fontWeight: 600 } }, `${key.replaceAll('_', ' ')}: `),
          h('dd', { style: { display: 'inline', margin: 0, overflowWrap: 'anywhere' } }, value)))),
        h('p', { style: { fontSize: 12, margin: '6px 0' } }, 'Read-only HKU workflow. Navigation may occur; no booking authority is granted.'),
        /timetable|next_class|free_slots/.test(toolName) ? h('p', null, 'Weekly recurrence only; holidays and teaching weeks are not verified.') : null,
        /moodle/.test(toolName) ? h('p', null, 'Visible Dashboard data only; not a complete audit of every course.') : null,
        /booking_preview/.test(toolName) ? h('p', null, 'A ready preview is not a reservation.') : null,
        failed ? h('p', null, 'A failed read is not an empty result. Check connection/login and Admin diagnostics.') : null,
        typeof inspect === 'function' ? h('button', { type: 'button', onClick: () => inspect() }, 'View original details') : null)
    }

    function Icon({ size = 20 }) {
      return h('svg', {
        width: size,
        height: size,
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.8,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        'aria-hidden': true,
      },
      h('path', { d: 'M3 20V7l9-4 9 4v13' }),
      h('path', { d: 'M7 20v-8h10v8M3 20h18M10 12v8M14 12v8' }))
    }

    const surface = {
      boxSizing: 'border-box',
      height: '100%',
      overflowY: 'auto',
      padding: 'max(24px, var(--dsh-frame-top-clearance, 24px)) 28px 32px',
      color: 'var(--dsw-alias-label-primary)',
      background: 'var(--dsw-alias-bg-base)',
      fontFamily: 'inherit',
    }
    const card = {
      border: '1px solid var(--dsw-alias-border-l3)',
      borderRadius: 12,
      padding: 18,
      background: 'var(--dsw-alias-bg-layer-1)',
      marginTop: 16,
    }

    function Panel({ connection }) {
      const [view, setView] = React.useState({ phase: 'loading' })
      const pending = React.useRef(null)
      const load = (connect = false, start = false) => {
        if (start && ['loading', 'starting', 'connecting'].includes(view.phase)) return
        pending.current?.abort()
        const controller = new AbortController()
        pending.current = controller
        setView({ phase: start ? 'starting' : 'loading' })
        const call = endpoint => connection.rpc.call('/api', endpoint, {}, controller.signal)
        const action = start ? call('hku-agents/start').then(async result => {
          if (controller.signal.aborted || result?.ok !== true || result?.value?.core?.state !== 'connected') return result
          setView({ phase: 'connecting' })
          // Give an already-paired extension a bounded opportunity to reconnect.
          for (let attempt = 0; attempt < 40; attempt++) {
            if (result.value.connections?.some(item => item.id === 'sis_browser' && item.status === 'connected')) break
            setView({ phase: 'connecting', waitSeconds: attempt })
            await new Promise(resolve => setTimeout(resolve, 1000))
            if (controller.signal.aborted) return result
            result = await call('hku-agents/status')
          }
          if (controller.signal.aborted) return result
          return call('hku-agents/connect')
        }) : call(connect === true ? 'hku-agents/connect' : 'hku-agents/status')
        action.then(result => {
          if (controller.signal.aborted) return
          const value = result?.ok === true ? result.value : null
          if (value?.read_only !== true || !value.core || !Array.isArray(value.connections)) {
            setView({ phase: 'error', code: result?.error?.code || 'INVALID_STATUS_RESPONSE' })
            return
          }
          setView({ phase: 'ready', value })
        }).catch(error => {
          if (controller.signal.aborted) return
          const message = typeof error?.message === 'string' ? error.message : ''
          const code = message.includes('invalid RPC target') ? 'INVALID_RPC_TARGET'
            : message.includes('HTTP 404') ? 'STATUS_ROUTE_NOT_FOUND'
              : message.includes('HTTP 405') ? 'STATUS_METHOD_NOT_ALLOWED'
                : message.includes('rpcId mismatch') || message.includes('invalid server-response') ? 'STATUS_PROTOCOL_ERROR'
                  : 'HOST_REQUEST_FAILED'
          setView({ phase: 'error', code })
        }).finally(() => { if (pending.current === controller) pending.current = null })
      }
      React.useEffect(() => {
        load()
        const unsubscribe = connection.state.subscribe(() => {
          if (connection.state.getSnapshot() === 'connected' && !pending.current) load()
        })
        return () => {
          pending.current?.abort()
          unsubscribe()
        }
      }, [connection])

      const status = view.value
      const core = status?.core
      const bridge = status?.connections?.find(item => item.id === 'sis_browser')
      const statusText = view.phase === 'loading'
        ? 'Checking local service...'
        : view.phase === 'starting' ? 'Checking and starting local Core in the background...'
        : view.phase === 'connecting' ? `Core ready. Waiting for Chrome Bridge (${view.waitSeconds || 0}/40s), then checking HKU login...`
        : view.phase === 'error'
          ? `Desktop Host status request failed (${view.code}). Check the plugin version and Host connection, then refresh.`
          : core?.state === 'connected'
            ? `Core connected${core.version ? ` (v${core.version})` : ''}.`
            : `Core unavailable (${core?.error_code || 'UNKNOWN'}). ${core?.recovery || ''}`
      return h('main', { style: surface, 'aria-label': 'HKU AGENTS' },
        h('div', { style: { maxWidth: 840, margin: '0 auto' } },
          h('h1', { style: { margin: '0 0 8px', fontSize: 26 } }, 'HKU AGENTS'),
          h('p', { style: { margin: 0, color: 'var(--dsw-alias-label-secondary)' } },
            'Desktop integration - Agent Chat first, Admin testing separately'),
          h('section', { style: card, 'aria-labelledby': 'hku-connection-heading' },
            h('h2', { id: 'hku-connection-heading', style: { marginTop: 0, fontSize: 18 } }, 'Connection'),
            h('p', { role: 'status', 'aria-live': 'polite' }, statusText),
            bridge ? h('p', null, `Chrome Bridge: ${bridge.status}${bridge.lifecycle_state ? ` (${bridge.lifecycle_state})` : ''}.`) : null,
            status?.binding ? h('p', { role: 'status' }, status.binding.state === 'connected'
              ? 'HKU connected. You can use Agent Chat or the Admin tests.'
              : status.binding.state === 'login_required'
                ? 'Complete HKU Portal login and MFA in Chrome, then click Connect HKU again.'
                : status.binding.error_code === 'HKU_TAB_NOT_FOUND'
                  ? 'Open HKU Portal in your paired Chrome profile, then click Connect HKU again.'
                  : `Open Chrome and check the HKU AGENTS extension connection (${status.binding.error_code || 'BRIDGE_UNAVAILABLE'}).`) : null,
            status?.correlation_id ? h('p', { style: { fontSize: 12 } }, `Correlation ID: ${status.correlation_id}`) : null,
            h('button', { type: 'button', onClick: () => load(false, true), disabled: ['loading', 'starting', 'connecting'].includes(view.phase) }, 'Start and connect HKU'),
            h('button', { type: 'button', onClick: () => load(true), disabled: ['loading', 'starting', 'connecting'].includes(view.phase), style: { marginLeft: 8 } }, 'Connect HKU'),
            h('button', { type: 'button', onClick: () => load(), disabled: ['loading', 'starting', 'connecting'].includes(view.phase), style: { marginLeft: 8 } }, 'Refresh status'),
            h('p', { style: { color: 'var(--dsw-alias-label-secondary)' } },
              'Start and connect HKU launches the registered local Core without a terminal, then checks the paired Chrome extension and HKU tab. Open Chrome and complete Portal login/MFA manually when prompted. Core stays running after Desktop closes so scheduled tasks are not interrupted. Local credentials are managed automatically by Windows.')),
          h('section', { style: card, 'aria-labelledby': 'hku-tools-heading' },
            h('h2', { id: 'hku-tools-heading', style: { marginTop: 0, fontSize: 18 } }, 'Available now'),
            h('p', null, 'The installed Host adapter contributes 23 bounded, read-only SIS, Moodle, Portal and Library tools to Harness conversations.'),
            h('p', null, 'For booking, recurring checks, or recovery, continue using the HKU AGENTS local GUI. This panel cannot select a slot, submit a booking, or authorize F4.')),
          h(ReadOnlyAdminSection, { connection, business: true }),
          h('section', { style: card, 'aria-labelledby': 'hku-next-heading' },
            h('h2', { id: 'hku-next-heading', style: { marginTop: 0, fontSize: 18 } }, 'Next integration gate'),
            h('p', null, 'Use a new Harness conversation for HKU tasks. Examples: “Show upcoming Moodle deadlines”; “Synchronize my weekly timetable for 2026-27 Sem 1”; “Read live Discussion Room dates without booking”. Tool cards summarize sources and status. Cached weekly schedules do not verify holidays or teaching weeks. Booking confirmation controls remain in the local GUI.'))))
    }

    function catalogTable(value) {
      const rows = value.availability_targets.map(item => h('tr', { key: `${item.facility_type}:${item.location}` },
        h('td', null, item.booking_facility_type), h('td', null, item.location),
        h('td', null, item.booking_preview_supported ? 'Catalog-supported' : 'No'),
        h('td', null, item.supervised_booking_supported ? 'Catalog-supported' : 'No')))
      return h('table', { style: { width: '100%', borderCollapse: 'collapse', textAlign: 'left' } },
        h('thead', null, h('tr', null,
          h('th', null, 'Facility type'), h('th', null, 'Location'),
          h('th', null, 'Preview'), h('th', null, 'Supervised F2'))),
        h('tbody', null, ...rows))
    }

    function courseList(label, rows) {
      return h('div', null,
        h('h3', { style: { fontSize: 15, marginBottom: 4 } }, `${label} (${rows.length})`),
        rows.length
          ? h('ul', null, ...rows.map(item => h('li', { key: `${item.course_code}:${item.section}:${item.class_number || ''}` },
            `${item.course_code} ${item.section}${item.class_number ? ` — class ${item.class_number}` : ''}`)))
          : h('p', null, 'None'))
    }

    function SISAdminSection({ connection }) {
      const [model, setModel] = React.useState({ phase: 'idle', term: '', courses: '' })
      const pending = React.useRef(null)
      const run = (kind) => {
        if (model.phase === 'loading') return
        let payload = {}
        if (kind === 'preflight') {
          const term = model.term.trim()
          const lines = model.courses.split('\n').map(line => line.trim()).filter(Boolean)
          const entries = lines.map(line => line.split('|').map(part => part.trim().toUpperCase()))
          if (!/^\d{4}-\d{2} Sem [12]$/.test(term) || entries.length < 1 || entries.length > 20 ||
            entries.some(parts => parts.length !== 2 || !/^[A-Z]{2,8}\d{3,5}[A-Z]?$/.test(parts[0]) || !/^[A-Z0-9-]{1,40}$/.test(parts[1])) ||
            new Set(entries.map(parts => parts.join(':'))).size !== entries.length) {
            setModel({ ...model, phase: 'error', code: 'INVALID_SIS_INPUT', recovery: 'Enter an exact SIS term and one COURSE_CODE | SECTION per line.' })
            return
          }
          payload = { term_label: term, expected_courses: entries.map(([course_code, section]) => ({ course_code, section })) }
        }
        pending.current?.abort()
        const controller = new AbortController()
        pending.current = controller
        setModel({ ...model, phase: 'loading', kind })
        const endpoint = kind === 'status' ? 'hku-agents/status' : `hku-agents/admin/sis/${kind}`
        connection.rpc.call('/api', endpoint, payload, controller.signal).then(result => {
          if (controller.signal.aborted) return
          const value = result?.ok === true ? result.value : null
          if (value?.read_only !== true || (kind !== 'status' && typeof value.ok !== 'boolean')) {
            setModel(current => ({ ...current, phase: 'error', code: 'INVALID_SIS_RESPONSE' }))
          } else if (kind !== 'status' && !value.ok) {
            setModel(current => ({ ...current, phase: 'error', code: value.error?.code || 'SIS_READ_FAILED', recovery: value.error?.recovery }))
          } else if (kind === 'sync' && (!Array.isArray(value.temporary_courses) || !Array.isArray(value.schedule_courses) || value.sis_write_requests_sent !== 0)) {
            setModel(current => ({ ...current, phase: 'error', code: 'INVALID_SIS_SYNC_RESPONSE' }))
          } else if (kind === 'preflight' && (typeof value.ready !== 'boolean' || !Array.isArray(value.matched_courses) || !Array.isArray(value.missing_courses) || !Array.isArray(value.unexpected_courses) || value.sis_write_requests_sent !== 0)) {
            setModel(current => ({ ...current, phase: 'error', code: 'INVALID_SIS_PREFLIGHT_RESPONSE' }))
          } else {
            setModel(current => ({ ...current, phase: 'ready', kind, value }))
          }
        }).catch(error => {
          if (controller.signal.aborted) return
          const message = typeof error?.message === 'string' ? error.message : ''
          const code = message.includes('HTTP 404') ? 'SIS_ADMIN_ROUTE_NOT_FOUND'
            : message.includes('HTTP 400') ? 'SIS_ADMIN_PROTOCOL_ERROR' : 'SIS_ADMIN_REQUEST_FAILED'
          setModel(current => ({ ...current, phase: 'error', code }))
        })
      }
      React.useEffect(() => () => pending.current?.abort(), [])
      const value = model.value
      const busy = model.phase === 'loading'
      return h('section', { style: card, 'aria-labelledby': 'hku-admin-sis-heading' },
        h('h2', { id: 'hku-admin-sis-heading', style: { marginTop: 0, fontSize: 18 } }, 'SIS read-only tests'),
        h('p', null, 'Use an authenticated Chrome SIS Temporary Course List. Sync and preflight read the open page; they do not navigate, enroll, or change the cart. Course rows appear only in this immediate panel result.'),
        h('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
          h('button', { type: 'button', disabled: busy, onClick: () => run('status') }, 'Check connection'),
          h('button', { type: 'button', disabled: busy, onClick: () => run('sync') }, 'Sync course lists (read-only)')),
        h('p', null, h('label', null, 'Exact term label (e.g. 2026-27 Sem 1)',
          h('input', { type: 'text', value: model.term, maxLength: 40, onChange: event => setModel(current => ({ ...current, term: event.target.value, phase: 'idle' })), style: { display: 'block', width: '100%', maxWidth: 320 } }))),
        h('p', null, h('label', null, 'Expected courses, one COURSE_CODE | SECTION per line',
          h('textarea', { value: model.courses, rows: 4, maxLength: 1200, onChange: event => setModel(current => ({ ...current, courses: event.target.value, phase: 'idle' })), style: { display: 'block', width: '100%' } }))),
        h('button', { type: 'button', disabled: busy, onClick: () => run('preflight') }, 'Run exact live preflight (read-only)'),
        busy ? h('p', { role: 'status' }, 'Reading SIS through Chrome Bridge...') : null,
        model.phase === 'error' ? h('p', { role: 'alert' }, `Test failed (${model.code}). ${model.recovery || 'Check Core, Chrome Bridge and SIS login.'}`) : null,
        model.phase === 'ready' && model.kind === 'status'
          ? h('div', { role: 'status' },
            h('p', null, `Core: ${value.core?.state || 'unknown'}. Chrome Bridge: ${value.connections?.find(item => item.id === 'sis_browser')?.status || 'unknown'}.`),
            h('p', null, `Correlation ID: ${value.correlation_id || 'unavailable'}`)) : null,
        model.phase === 'ready' && model.kind === 'sync'
          ? h('div', { role: 'status' },
            h('p', null, `SIS term: ${value.term_label || 'unknown'} | Parser: ${value.diagnostics?.parser_version || 'unknown'} | Correlation ID: ${value.correlation_id || 'unavailable'}`),
            courseList('Temporary Course List', value.temporary_courses), courseList('Class Schedule', value.schedule_courses)) : null,
        model.phase === 'ready' && model.kind === 'preflight'
          ? h('div', { role: 'status' },
            h('p', null, `Verdict: ${value.ready ? 'ready' : 'not ready'} | Term match: ${value.term_match ? 'yes' : 'no'} | Observed: ${value.observed_term_label || 'unknown'}`),
            h('p', null, `Task ID: ${value.task_id || 'unavailable'} | Correlation ID: ${value.correlation_id || 'unavailable'}`),
            value.issues.length ? h('p', null, `Issues: ${value.issues.join(' ')}`) : null,
            courseList('Matched', value.matched_courses), courseList('Missing', value.missing_courses), courseList('Unexpected', value.unexpected_courses)) : null)
    }

    const READ_GROUPS = [
      { title: 'SIS timetable', cases: [['timetable_sync', 'Sync weekly timetable'], ['next_class', 'Next class from cache']] },
      { title: 'Moodle', cases: [['moodle_dashboard', 'Inspect Dashboard'], ['moodle_courses', 'Count visible courses'], ['moodle_assignments', 'Count upcoming assignments']] },
      { title: 'Portal and briefing', cases: [['portal_notices', 'Count visible notices'], ['briefing', 'Read cache-based daily briefing']] },
      { title: 'Library reads', cases: [['library_hours', 'Read current hours'], ['library_dates', 'Read live Date options'],
        ['library_availability', 'Count available slots'], ['library_research', 'Count research results']] },
    ]
    const FACILITY_CHOICES = [
      'single_study_room', 'av_group_viewing_room', 'communal_virtual_pc', 'computer', 'computer_in_lic',
      'engraving_cutting_computer', 'concept_and_creation_room', 'discussion_room', 'microform_scanner',
      'overhead_scanner', 'research_desk', 'studio_editing_room', 'study_table', 'study_table_deep_quiet', 'study_room',
    ]

    function ReadOnlyAdminSection({ connection, business = false }) {
      const [model, setModel] = React.useState({ phase: 'idle', term: '', days: '14', facility: 'discussion_room', date: '', query: '' })
      const pending = React.useRef(null)
      const setField = (field, value) => setModel(current => ({ ...current, [field]: value, phase: 'idle' }))
      const run = operation => {
        if (model.phase === 'loading') return
        let payload = {}
        if (operation === 'timetable_sync' || operation === 'next_class') {
          if (!/^\d{4}-\d{2} Sem [12]$/.test(model.term.trim())) return setModel({ ...model, phase: 'error', code: 'INVALID_TERM', recovery: 'Enter the exact SIS term label.' })
          payload = { term_label: model.term.trim() }
        } else if (operation === 'moodle_assignments') {
          const days = Number(model.days)
          if (!Number.isInteger(days) || days < 1 || days > 90) return setModel({ ...model, phase: 'error', code: 'INVALID_DAYS', recovery: 'Enter 1–90 days.' })
          payload = { days_ahead: days }
        } else if (operation === 'library_dates') {
          payload = { facility_type: model.facility }
        } else if (operation === 'library_availability') {
          if (!/^\d{4}-\d{2}-\d{2}$/.test(model.date.trim())) return setModel({ ...model, phase: 'error', code: 'INVALID_DATE', recovery: 'Copy an exact YYYY-MM-DD date from the live Date options.' })
          payload = { facility_type: model.facility, date: model.date.trim() }
        } else if (operation === 'library_research') {
          const query = model.query.trim()
          if (query.length < 2 || query.length > 200) return setModel({ ...model, phase: 'error', code: 'INVALID_QUERY', recovery: 'Enter 2–200 search characters.' })
          payload = { query }
        }
        pending.current?.abort()
        const controller = new AbortController()
        pending.current = controller
        setModel({ ...model, phase: 'loading', operation })
        connection.rpc.call('/api', `hku-agents/admin/read/${operation}`, payload, controller.signal).then(result => {
          if (controller.signal.aborted) return
          const value = result?.ok === true ? result.value : null
          if (value?.read_only !== true || typeof value.ok !== 'boolean') {
            setModel(current => ({ ...current, phase: 'error', code: 'INVALID_ADMIN_READ_RESPONSE' }))
          } else if (!value.ok) {
            setModel(current => ({ ...current, phase: 'error', value, code: value.error?.code || 'READ_FAILED', recovery: value.error?.recovery }))
          } else if (value.operation !== operation || value.domain_writes_performed !== 0 || !value.summary || typeof value.summary !== 'object') {
            setModel(current => ({ ...current, phase: 'error', code: 'UNSAFE_ADMIN_READ_RESPONSE' }))
          } else {
            setModel(current => ({ ...current, phase: 'ready', operation, value,
              date: operation === 'library_dates' && Array.isArray(value.summary.offered_dates) && value.summary.offered_dates.length
                ? value.summary.offered_dates[0] : current.date }))
          }
        }).catch(error => {
          if (controller.signal.aborted) return
          const message = typeof error?.message === 'string' ? error.message : ''
          setModel(current => ({ ...current, phase: 'error', code: message.includes('HTTP 404') ? 'ADMIN_READ_ROUTE_NOT_FOUND' : 'ADMIN_READ_REQUEST_FAILED' }))
        })
      }
      React.useEffect(() => () => pending.current?.abort(), [])
      const details = model.value?.summary
      return h('section', { style: card, 'aria-labelledby': 'hku-admin-read-heading' },
        h('h2', { id: 'hku-admin-read-heading', style: { marginTop: 0, fontSize: 18 } }, business ? 'Quick read-only checks' : 'Other read-only interface tests'),
        h('p', null, business ? 'Agent Chat is the main workflow. These shortcuts only refresh counts or live dates; they never book.' : 'Each button calls one fixed Host route. Results below are bounded summaries; private Moodle, Portal, timetable and research rows are omitted. Some reads navigate in Chrome, but none submit changes.'),
        h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 } },
          h('label', null, 'Exact SIS term', h('input', { type: 'text', value: model.term, maxLength: 40, onChange: event => setField('term', event.target.value), style: { display: 'block', width: '100%' } })),
          h('label', null, 'Assignment horizon (days)', h('input', { type: 'number', min: 1, max: 90, value: model.days, onChange: event => setField('days', event.target.value), style: { display: 'block', width: '100%' } })),
          h('label', null, 'Library facility', h('select', { value: model.facility, onChange: event => setField('facility', event.target.value), style: { display: 'block', width: '100%' } },
            ...FACILITY_CHOICES.map(item => h('option', { key: item, value: item }, item)))),
          !business ? h('label', null, 'Live offered date (YYYY-MM-DD)', h('input', { type: 'text', value: model.date, maxLength: 10, onChange: event => setField('date', event.target.value), style: { display: 'block', width: '100%' } })) : null,
          !business ? h('label', null, 'Library research keywords', h('input', { type: 'text', value: model.query, maxLength: 200, onChange: event => setField('query', event.target.value), style: { display: 'block', width: '100%' } })) : null),
        ...(business ? [{ title: 'Manual shortcuts', cases: [['next_class', 'Next class from cache'], ['moodle_assignments', 'Refresh assignment count'], ['library_dates', 'Read live facility dates']] }] : READ_GROUPS).map(group => h('div', { key: group.title },
          h('h3', { style: { fontSize: 16, marginBottom: 6 } }, group.title),
          h('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
            ...group.cases.map(([operation, label]) => h('button', { key: operation, type: 'button', disabled: model.phase === 'loading', onClick: () => run(operation) }, label))))),
        model.phase === 'loading' ? h('p', { role: 'status' }, `Running ${model.operation} read-only test...`) : null,
        model.phase === 'error' ? h('p', { role: 'alert' }, `Test failed (${model.code}). ${model.recovery || 'Check Core, Chrome Bridge, HKU login and exact input.'}`) : null,
        model.value ? h('p', null, `Task: ${model.value.task_id || 'none'} | Correlation: ${model.value.correlation_id || 'none'}`) : null,
        model.value?.history_warning ? h('p', { role: 'alert' }, model.value.history_warning) : null,
        model.value?.diagnostics ? h('details', null, h('summary', null, 'Parser diagnostics (redacted)'), h('pre', null, JSON.stringify(model.value.diagnostics, null, 2))) : null,
        model.phase === 'ready' ? h('div', { role: 'status', 'aria-live': 'polite' },
          h('p', null, `Read-only ${model.operation} completed. Domain writes: 0.`),
          h('dl', null, ...Object.entries(details).map(([key, raw]) => h('div', { key, style: { marginBottom: 4 } },
            h('dt', { style: { display: 'inline', fontWeight: 600 } }, `${key}: `),
            h('dd', { style: { display: 'inline', margin: 0 } }, raw === null ? 'unknown' : Array.isArray(raw) ? raw.join(', ') : typeof raw === 'object' ? Object.entries(raw).map(([k, v]) => `${k}=${v}`).join('; ') : String(raw)))))) : null)
    }

    function HistorySection({ connection }) {
      const [view, setView] = React.useState({ phase: 'idle', records: [] })
      const pending = React.useRef(null)
      const load = (id, verdict) => {
        if (view.phase === 'loading') return
        const controller = new AbortController(); pending.current = controller
        setView(current => ({ ...current, phase: 'loading' }))
        connection.rpc.call('/api', `hku-agents/admin/history/${id ? 'review' : 'list'}`, id ? { id, verdict } : {}, controller.signal).then(result => {
          if (controller.signal.aborted) return
          const value = result?.ok === true ? result.value : null
          if (value?.ok !== true || !Array.isArray(value.records)) return setView({ phase: 'error', records: [] })
          setView({ phase: 'ready', records: value.records })
        }).catch(() => { if (!controller.signal.aborted) setView({ phase: 'error', records: [] }) })
      }
      React.useEffect(() => () => pending.current?.abort(), [])
      return h('section', { style: card },
        h('h2', null, 'Read/test history'),
        h('p', null, 'Latest 100 calls, saved locally for this Windows user. Execution completed is not human acceptance. No inputs, course rows, raw DOM or secrets are stored. Chat calls are not recorded here.'),
        h('button', { disabled: view.phase === 'loading', onClick: () => load() }, 'Refresh test history'),
        view.phase === 'error' ? h('p', { role: 'alert' }, 'HISTORY_UNAVAILABLE. Existing results remain valid; do not delete the history file to hide this error.') : null,
        view.phase === 'ready' && !view.records.length ? h('p', null, 'No records yet. Run an Admin test or a quick check, then refresh.') : null,
        ...view.records.map(row => h('details', { key: row.id, style: { marginTop: 12 } },
          h('summary', null, `${row.recorded_at} | ${row.operation} | ${row.outcome} | review: ${row.verdict}`),
          h('p', null, `Plugin ${row.plugin_version} | Domain writes: ${row.domain_writes} | Error: ${row.error_code || 'none'}`),
          h('p', null, `Host: ${row.host_runtime || 'unknown'} | Core/extension versions: not reported by this operation`),
          h('p', null, `Task: ${row.task_id || 'none'} | Correlation: ${row.correlation_id || 'none'}`),
          h('pre', null, JSON.stringify(row.diagnostics, null, 2)),
          ...['pass', 'fail', 'needs_review'].map(verdict => h('button', { key: verdict, disabled: view.phase === 'loading', onClick: () => load(row.id, verdict), style: { marginRight: 8 } }, `Mark ${verdict}`)))))
    }

    function AdminPanel({ connection }) {
      const [view, setView] = React.useState({ phase: 'idle' })
      const pending = React.useRef(null)
      const runCatalogTest = () => {
        pending.current?.abort()
        const controller = new AbortController()
        pending.current = controller
        setView({ phase: 'loading' })
        connection.rpc.call('/api', 'hku-agents/admin/facilities', {}, controller.signal).then(result => {
          if (controller.signal.aborted) return
          const value = result?.ok === true ? result.value : null
          if (value?.read_only !== true || typeof value.ok !== 'boolean') {
            setView({ phase: 'error', code: 'INVALID_ADMIN_RESPONSE' })
          } else if (!value.ok) {
            setView({ phase: 'error', code: value.error?.code || 'CATALOG_READ_FAILED', recovery: value.error?.recovery })
          } else if (!Array.isArray(value.facilities) || !Array.isArray(value.availability_targets) || value.booking_writes_performed !== 0) {
            setView({ phase: 'error', code: 'INVALID_CATALOG_RESPONSE' })
          } else {
            setView({ phase: 'ready', value })
          }
        }).catch(error => {
          if (controller.signal.aborted) return
          const message = typeof error?.message === 'string' ? error.message : ''
          const code = message.includes('HTTP 404') ? 'ADMIN_ROUTE_NOT_FOUND'
            : message.includes('HTTP 400') ? 'ADMIN_PROTOCOL_ERROR' : 'ADMIN_REQUEST_FAILED'
          setView({ phase: 'error', code })
        })
      }
      React.useEffect(() => () => pending.current?.abort(), [])
      const value = view.value
      return h('main', { style: surface, 'aria-label': 'HKU AGENTS Admin' },
        h('div', { style: { maxWidth: 960, margin: '0 auto' } },
          h('h1', { style: { margin: '0 0 8px', fontSize: 26 } }, 'HKU AGENTS Admin'),
          h('p', { style: { color: 'var(--dsw-alias-label-secondary)' } },
            'Manual interface tests and diagnostics live here. Agent Chat remains the primary business front-end.'),
          h('section', { style: card, 'aria-labelledby': 'hku-admin-catalog-heading' },
            h('h2', { id: 'hku-admin-catalog-heading', style: { marginTop: 0, fontSize: 18 } }, 'Library facility catalog'),
            h('p', null, 'Read-only local catalog test. No Chrome navigation, slot selection, booking form, or reservation write.'),
            h('button', { type: 'button', onClick: runCatalogTest, disabled: view.phase === 'loading' },
              view.phase === 'loading' ? 'Reading...' : 'Run read-only catalog test'),
            view.phase === 'error'
              ? h('p', { role: 'alert' }, `Test failed (${view.code}). ${view.recovery || 'Check the local Core and retry.'}`)
              : null,
            view.phase === 'ready'
              ? h('div', { role: 'status', 'aria-live': 'polite' },
                h('p', null, `Passed: ${value.facility_count} policy summaries and ${value.availability_target_count} availability targets. No browser interactions or booking writes.`),
                h('p', { style: { fontSize: 12 } },
                  `Policy verified on: ${value.policy_verified_on || 'unknown'} | Correlation ID: ${value.correlation_id || 'unavailable'}`),
                h('div', { style: { overflowX: 'auto' } }, catalogTable(value)))
              : null),
          h(SISAdminSection, { connection }),
          h(ReadOnlyAdminSection, { connection }),
          h(HistorySection, { connection }),
          h('p', { style: { color: 'var(--dsw-alias-label-secondary)' } },
            'Read-only tests do not verify account eligibility or F2 booking acceptance. History is redacted and is not a full Core audit-log viewer.')))
    }

    const inject = ['slots', 'layout', 'connection']
    function apply(ctx) {
      ctx.slots.inject('tool.call.toolview', function* () {
        for (const key of HKU_TOOL_NAMES) yield ctx.slots.register({ name: 'tool.call.toolview', key }, HKUToolCard)
      })
      ctx.slots.inject('main', () => ctx.slots.register({
        name: 'main',
        key: PANEL_ID,
      }, () => h(Panel, { connection: ctx.connection })))
      ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
        name: 'sidebar.panellist',
        id: PANEL_ID,
        order: 20,
        label: () => 'HKU AGENTS',
      }, Icon))
      ctx.slots.inject('main', () => ctx.slots.register({
        name: 'main',
        key: ADMIN_PANEL_ID,
      }, () => h(AdminPanel, { connection: ctx.connection })))
      ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
        name: 'sidebar.panellist',
        id: ADMIN_PANEL_ID,
        order: 21,
        label: () => 'HKU Admin',
      }, Icon))
    }

    return { inject, apply }
  },
})
