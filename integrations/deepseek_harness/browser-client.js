// Browser half for DeepSeek Harness Desktop 0.2.0-rc.2. The loader expects
// this module wrapper, not Node's ESM format. No API credential enters here.
window.__ModuleLoader__.load({
  id: 'dsh-hku-agents',
  factory: require => {
    const React = require('react')
    const h = (type, props, ...children) => React.createElement(type, type === 'button'
      ? { ...props, style: { padding: '7px 12px', borderRadius: 6, cursor: props?.disabled ? 'not-allowed' : 'pointer',
        ...props?.style } } : props, ...children)
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

    function hostRequest(connection, endpoint, payload, controller, timeout = 45000) {
      let timer
      let cancelled
      const deadline = new Promise((_resolve, reject) => {
        cancelled = () => reject(new Error('REQUEST_CANCELLED'))
        if (controller.signal.aborted) return cancelled()
        controller.signal.addEventListener('abort', cancelled, { once: true })
        timer = setTimeout(() => { reject(new Error('HOST_REQUEST_TIMEOUT')); controller.abort() }, timeout)
      })
      return Promise.race([connection.rpc.call('/api', endpoint, payload, controller.signal), deadline])
        .finally(() => { clearTimeout(timer); controller.signal.removeEventListener('abort', cancelled) })
    }

    function Panel({ connection }) {
      const [view, setView] = React.useState({ phase: 'loading' })
      const pending = React.useRef(null)
      const load = (connect = false, start = false) => {
        if (pending.current) return
        const controller = new AbortController()
        pending.current = controller
        setView({ phase: start ? 'starting' : 'loading' })
        const call = endpoint => hostRequest(connection, endpoint, {}, controller, endpoint.endsWith('/start') ? 60000 : 15000)
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
          if (controller.signal.aborted) {
            if (pending.current === controller && error?.message === 'HOST_REQUEST_TIMEOUT') setView({ phase: 'error', code: 'HOST_REQUEST_TIMEOUT' })
            return
          }
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
          else if (connection.state.getSnapshot() !== 'connected') {
            pending.current?.abort()
            pending.current = null
            setView({ phase: 'error', code: 'HOST_DISCONNECTED' })
          }
        })
        return () => {
          pending.current?.abort()
          unsubscribe()
        }
      }, [connection])

      React.useEffect(() => {
        // Recover the paired Bridge without starting Core, navigating or changing
        // any gate. Only the explicit Start/connect action inspects HKU login.
        if (view.phase !== 'ready' || view.value?.core?.state !== 'connected' ||
            view.value.connections.some(item => item.id === 'sis_browser' && item.status === 'connected')) return
        const timer = setTimeout(() => load(), 15000)
        return () => clearTimeout(timer)
      }, [view])

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
            '以 AI Agent 对话为主；精简手动操作和 Admin 测试分别保留。'),
          h('section', { style: card, 'aria-labelledby': 'hku-connection-heading' },
            h('h2', { id: 'hku-connection-heading', style: { marginTop: 0, fontSize: 18 } }, '连接与启动 / Connection'),
            h('p', { role: 'status', 'aria-live': 'polite' }, statusText),
            bridge ? h('p', null, `Chrome Bridge: ${bridge.status}${bridge.lifecycle_state ? ` (${bridge.lifecycle_state})` : ''}.`) : null,
            bridge ? h('p', null, `Chrome 扩展：${bridge.extension_version || '版本未报告'}；本批要求 0.17.29 或更新。更新后需重新加载扩展并刷新 HKU 标签页。`) : null,
            view.phase === 'error' || core?.state !== 'connected' || bridge?.status !== 'connected'
              ? h('p', { role: 'status' }, '排查顺序：Desktop Host → 启动 Core → Chrome 扩展连接 → Portal 登录。Bridge 断线时每 15 秒刷新本地状态；不会自动登录或提交预约。') : null,
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
            h('h2', { id: 'hku-tools-heading', style: { marginTop: 0, fontSize: 18 } }, 'Agent Chat：主要业务入口'),
            h('p', null, '在左侧新建会话，直接提出 HKU 查询。示例：查询未来 14 天 Moodle 截止日期并列出课程归属；查询讨论室现场可预约日期。'),
            h('p', null, 'The installed Host adapter contributes 23 bounded, read-only SIS, Moodle, Portal and Library tools to Harness conversations.'),
            h('p', null, 'Chat remains read-only. Exact supervised booking and separately armed scheduling controls are below.')),
          h(TaskCenter, { connection }),
          h('details', { style: card }, h('summary', null, '精简手动查询（可选）'), h(ReadOnlyAdminSection, { connection, business: true })),
          h('details', { style: card }, h('summary', null, 'Library 精确预约／定时任务（需单独确认）'), h(LibraryWorkflowSection, { connection })),
          h('section', { style: card, 'aria-labelledby': 'hku-next-heading' },
            h('h2', { id: 'hku-next-heading', style: { marginTop: 0, fontSize: 18 } }, 'Next integration gate'),
            h('p', null, 'Use Harness Chat for read-only HKU requests. Exact-target booking requires the separate confirmation controls, not Chat text. Cached schedules do not verify holidays or teaching weeks. The local GUI remains a recovery fallback.'))))
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

    function ReadOnlyAdminSection({ connection, business = false, domain = null }) {
      const [model, setModel] = React.useState({ phase: 'idle', term: '', days: '14', facility: 'discussion_room', date: '', query: '' })
      const pending = React.useRef(null)
      const setField = (field, value) => { if (!pending.current) setModel(current => ({ ...current, [field]: value, phase: 'idle' })) }
      const run = operation => {
        if (pending.current || model.phase === 'loading') return
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
        hostRequest(connection, `hku-agents/admin/read/${operation}`, payload, controller).then(result => {
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
          if (controller.signal.aborted && error?.message !== 'HOST_REQUEST_TIMEOUT') return
          const message = typeof error?.message === 'string' ? error.message : ''
          setModel(current => ({ ...current, phase: 'error', code: message.includes('HTTP 404') ? 'ADMIN_READ_ROUTE_NOT_FOUND' : 'ADMIN_READ_REQUEST_FAILED' }))
        }).finally(() => { if (pending.current === controller) pending.current = null })
      }
      React.useEffect(() => () => pending.current?.abort(), [])
      const details = model.value?.summary
      const headingId = `hku-admin-read-${business ? 'quick' : domain ? domain.toLowerCase().replaceAll(' ', '-') : 'all'}`
      return h('section', { style: card, 'aria-labelledby': headingId },
        h('h2', { id: headingId, style: { marginTop: 0, fontSize: 18 } }, business ? 'Quick read-only checks' : '只读接口测试'),
        h('p', null, business ? 'Agent Chat is the main workflow. These shortcuts only refresh counts or live dates; they never book.' : 'Each button calls one fixed Host route. Results below are bounded summaries; private Moodle, Portal, timetable and research rows are omitted. Some reads navigate in Chrome, but none submit changes.'),
        h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 } },
          !domain || domain === 'SIS timetable' ? h('label', null, '学期 / Exact SIS term', h('input', { type: 'text', disabled: model.phase === 'loading', value: model.term, maxLength: 40, onChange: event => setField('term', event.target.value), style: { display: 'block', width: '100%' } })) : null,
          !domain || domain === 'Moodle' ? h('label', null, '截止日期范围（天）', h('input', { type: 'number', disabled: model.phase === 'loading', min: 1, max: 90, value: model.days, onChange: event => setField('days', event.target.value), style: { display: 'block', width: '100%' } })) : null,
          !domain || domain === 'Library reads' ? h('label', null, 'Library facility / 设施', h('select', { disabled: model.phase === 'loading', value: model.facility, onChange: event => setField('facility', event.target.value), style: { display: 'block', width: '100%' } },
            ...FACILITY_CHOICES.map(item => h('option', { key: item, value: item }, item)))) : null,
          !business && (!domain || domain === 'Library reads') ? h('label', null, 'Live offered date (YYYY-MM-DD)', h('input', { disabled: model.phase === 'loading', type: 'text', value: model.date, maxLength: 10, onChange: event => setField('date', event.target.value), style: { display: 'block', width: '100%' } })) : null,
          !business && (!domain || domain === 'Library reads') ? h('label', null, 'Library research keywords', h('input', { disabled: model.phase === 'loading', type: 'text', value: model.query, maxLength: 200, onChange: event => setField('query', event.target.value), style: { display: 'block', width: '100%' } })) : null),
        ...(business ? [{ title: 'Manual shortcuts', cases: [['next_class', 'Next class from cache'], ['moodle_assignments', 'Refresh assignment count'], ['library_dates', 'Read live facility dates']] }] : READ_GROUPS.filter(group => !domain || group.title === domain)).map(group => h('div', { key: group.title },
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

    const phaseNames = { not_armed: '未武装', armed: '已武装，等待准备', preparing: '准备中',
      waiting_for_release: '等待开放时间', checking_date: '正在核对开放日期', checking_availability: '正在核对精确空位',
      checking_account_records: '正在核对账号记录', preparing_booking_form: '正在准备精确预约表单',
      failed_before_submit: '提交前停止（未提交）', booking_record_verified: '预约记录已核验',
      waiting: '等待检查时间', querying: '正在查询', suggestion_ready: '建议已生成（未预约）',
      dry_run_ready_no_submission: '演练通过，未提交', pending_executor: '已保存，尚未执行',
      completed: '执行结束（需核验业务结果）', outcome_unknown: '提交结果未知，请人工核对，勿重试',
      interrupted: '已中断，未自动重放', paused: '已暂停', revoked: '已撤销', expired: '已过期',
      authentication_required: '需要登录或连接', read_failed: '读取失败', no_match: '没有匹配时段',
      missed_after_restart: '重启后已错过，不补执行', active: '等待执行', migration_required: '旧规则需重新创建（不自动执行）',
      target_date_not_offered: '现场未提供目标日期' }
    function hongKongTime(value) {
      if (!value) return '—'
      // Never interpret a timezone-free timestamp using the Windows timezone.
      if (!/(Z|[+-]\d{2}:\d{2})$/.test(value)) return `${value}（时区未报告）`
      const date = new Date(value)
      if (!Number.isFinite(date.getTime())) return '时间无效'
      return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Hong_Kong', year: 'numeric', month: '2-digit',
        day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(date) + ' HKT'
    }

    function TaskCenter({ connection }) {
      const [view, setView] = React.useState({ phase: 'idle', value: null })
      const [automatic, setAutomatic] = React.useState(false)
      const pending = React.useRef(null)
      const load = () => {
        if (pending.current) return
        const controller = new AbortController(); pending.current = controller
        setView(old => ({ ...old, phase: 'loading' }))
        hostRequest(connection, 'hku-agents/admin/workbench/tasks', {}, controller).then(response => {
          if (controller.signal.aborted) return
          const value = response?.ok === true ? response.value : null
          if (value?.ok !== true || value.read_only !== true || value.changes_performed !== false || !Array.isArray(value.groups))
            return setView(old => ({ ...old, phase: 'error' }))
          setView({ phase: 'ready', value })
        }).catch(error => { if (!controller.signal.aborted || error?.message === 'HOST_REQUEST_TIMEOUT') setView(old => ({ ...old, phase: 'error' })) })
          .finally(() => { if (pending.current === controller) pending.current = null })
      }
      React.useEffect(() => () => pending.current?.abort(), [])
      React.useEffect(() => {
        if (!automatic || view.phase === 'loading') return
        const timer = setTimeout(load, 15000)
        return () => clearTimeout(timer)
      }, [automatic, view])
      return h('section', { style: card, 'aria-label': 'HKU task center' },
        h('h2', null, '任务状态中心'),
        h('p', null, '只读快照：F3 规则／最近运行、F4 授权。不会创建、武装、暂停或重试任务；这里只显示有限记录，不是完整审计。'),
        h('button', { type: 'button', disabled: view.phase === 'loading', onClick: load }, '刷新任务状态'),
        h('label', { style: { marginLeft: 12 } }, h('input', { type: 'checkbox', checked: automatic,
          onChange: e => setAutomatic(e.target.checked) }), ' 每 15 秒只读刷新（离开页面后停止）'),
        view.phase === 'loading' ? h('p', { role: 'status' }, '正在读取 Core 任务状态…') : null,
        view.phase === 'error' ? h('p', { role: 'alert' }, 'TASK_SNAPSHOT_UNAVAILABLE：刷新失败。以下旧快照不是当前状态；检查 Host/Core 后重试。') : null,
        view.value ? h('p', null, `快照时间：${hongKongTime(view.value.observed_at)}`) : null,
        ...(view.value?.groups || []).map(group => h('details', { key: group.kind, open: true },
          h('summary', null, `${group.kind} (${group.rows?.length || 0})`),
          group.ok !== true ? h('p', { role: 'alert' }, `读取失败：${group.error_code || 'UNKNOWN'}，不是零任务。`)
            : !group.rows.length ? h('p', null, '此次快照没有记录。')
            : h('ul', null, ...group.rows.map(row => h('li', { key: row.id, style: { marginBottom: 12 } },
              h('strong', null, `${row.state === 'expired' ? '授权已过期 · ' : ''}${phaseNames[row.execution_result?.phase || row.phase] || phaseNames[row.state] || row.phase || row.state || '状态未报告'}`),
              h('p', null, `${row.kind} | ${row.id} | ${row.read_only === true ? 'F3 只读' : row.dry_run === true ? '只读演练' : row.dry_run === false ? '真实模式' : '模式未报告'}`),
              h('p', null, `目标：${row.target?.date || '日期未报告'} ${row.target?.facility_type || ''} ${row.target?.room || ''} ${row.target?.start_time || ''}–${row.target?.end_time || ''}`),
              row.target?.preference_summary_only ? h('p', null, '仅显示首选摘要；完整偏好和实际候选请查看 F3 原始结果。') : null,
              row.target?.suggested_candidate_verified ? h('p', null, '已核对原始运行的建议候选；未预约。') : null,
              h('p', null, `${row.scheduled_time_basis === 'checking_start' ? '检查开始' : '原计划时间（准备／旧版）'}：${hongKongTime(row.scheduled_at)}；下次检查：${hongKongTime(row.next_run_at)}；结束：${hongKongTime(row.completed_at)}`),
              row.started_at ? h('p', null, `运行启动：${hongKongTime(row.started_at)}`) : null,
              h('p', null, `准备：${hongKongTime(row.prepare_at)}；停止期限：${hongKongTime(row.stop_at)}；日期检查次数：${row.date_check_count ?? '未报告'}`),
              row.kind === 'F3 rules' ? h('p', null, `已运行 ${row.run_count ?? '未报告'} / 上限 ${row.max_runs ?? '未报告'}。规则本身不是运行结果，写入请查看对应运行。`)
                : row.kind === 'F3 runs' ? h('p', null, `只读运行 / 写入 ${row.booking_writes_performed ?? '未报告'}；预约尝试和成功次数不适用。`)
                : h('p', null, `尝试 ${row.attempt_count ?? '未报告'} / 成功 ${row.success_count ?? '未报告'} / 写入 ${row.booking_writes_performed ?? '未报告'}`),
              row.error_code ? h('p', { role: 'alert' }, `停止原因：${row.error_code}`) : null,
              row.kind === 'F4 authorizations' ? h('details', null, h('summary', null, '执行详情与脱敏诊断'),
                h('p', null, `授权状态：${phaseNames[row.state] || row.state}；执行结果：${phaseNames[row.execution_result?.phase] || row.execution_result?.phase || '未报告，不能推断成功'}`),
                h('p', null, `完成：${hongKongTime(row.execution_result?.completed_at)}；结果来源：${row.execution_result?.source === 'legacy_audit' ? '旧审计记录恢复' : row.execution_result?.source === 'executor' ? '执行器持久化结果' : '未报告'}`),
                h('p', null, `已记录的登录恢复尝试：${row.session_recovery_count ?? '未报告'}（仅统计诊断中的恢复，不代表所有失败请求）`),
                h('pre', { style: { whiteSpace: 'pre-wrap', maxHeight: 360, overflowY: 'auto' } }, JSON.stringify({
                  execution_result: row.execution_result, stages: row.diagnostics || [] }, null, 2))) : null,
              row.state === 'outcome_unknown' || row.phase === 'outcome_unknown'
                ? h('p', { role: 'alert' }, '可能已提交。请检查 My Booking Record，不要重新提交。') : null)))))
      )
    }

    function Workbench({ connection }) {
      const [view, setView] = React.useState({ phase: 'idle' })
      const pending = React.useRef(null)
      const run = action => {
        if (pending.current) return
        const controller = new AbortController(); pending.current = controller
        setView({ phase: 'loading', action })
        hostRequest(connection, `hku-agents/admin/workbench/${action}`, {}, controller).then(response => {
          if (controller.signal.aborted) return
          const value = response?.ok === true ? response.value : null
          if (value?.ok !== true || (action === 'checks' && (value.local_only !== true || value.domain_writes_performed !== 0 ||
              value.browser_interactions_performed !== false || !Array.isArray(value.checks))) ||
              (action === 'report' && (!value.report || value.report.local_only !== true || value.report.domain_writes_performed !== 0)))
            return setView({ phase: 'error' })
          setView({ phase: 'ready', action, value })
        }).catch(error => { if (!controller.signal.aborted || error?.message === 'HOST_REQUEST_TIMEOUT') setView({ phase: 'error' }) })
          .finally(() => { if (pending.current === controller) pending.current = null })
      }
      React.useEffect(() => () => pending.current?.abort(), [])
      return h('section', { style: card, 'aria-label': 'Local acceptance workbench' },
        h('h2', null, '集中验收工作台'),
        h('p', null, '无需 HKU 登录：检查 Core、Bridge 版本、本地目录与运行开关。不会启动 Core、导航、登录、改变开关或执行现场查询。开关打开也不会被自动关闭。'),
        h('button', { type: 'button', onClick: () => run('checks'), disabled: view.phase === 'loading' }, '一键本地检查'),
        h('button', { type: 'button', onClick: () => run('report'), disabled: view.phase === 'loading', style: { marginLeft: 8 } }, '生成脱敏验收报告'),
        view.phase === 'loading' ? h('p', { role: 'status' }, '正在检查本地状态，请稍候…') : null,
        view.phase === 'error' ? h('p', { role: 'alert' }, 'LOCAL_CHECK_FAILED：检查失败，不代表现场没有数据。检查 Host/Core 后重试。') : null,
        view.phase === 'ready' ? h('div', null,
          h('p', null, `插件 ${view.value.plugin_version || view.value.report?.plugin_version}；本地接口完成 ≠ 人工验收通过。`),
          h('ul', null, ...(view.value.checks || view.value.report?.checks || []).map(check => h('li', { key: check.id },
            `${check.id}: ${check.state}${check.error_code ? ` (${check.error_code})` : ''}`,
            h('pre', null, JSON.stringify(check, null, 2))))),
          view.action === 'report' ? h('div', null,
            h('p', null, '报告仅含版本、检查结果和最近 100 条 Admin 测试摘要。无预约目标、输入、课程行、DOM、凭据。选中下框内容复制保存；历史缺失会明确标注。'),
            h('textarea', { readOnly: true, 'aria-label': 'Redacted acceptance report', rows: 16,
              value: JSON.stringify(view.value.report, null, 2), style: { width: '100%', boxSizing: 'border-box' } })) : null) : null)
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

    function LibraryWorkflowSection({ connection, admin = false }) {
      const [form, setForm] = React.useState({ stage: 'F1', facility_type: 'discussion_room', date: '',
        floor: 'Level 3', room: '', start_time: '09:00', end_time: '10:00', eligibility_category: 'current_hku_students',
        execution_at: '', prepare_at: '', stop_at: '', poll_interval_seconds: '15', max_date_checks: '8',
        rooms: '', sessions: '', allow_room_fallback: false, allow_time_fallback: false,
        policy: false, rules: false, reviewed: false, exact: false, future: false, gate: false, record_id: '', candidate_id: '', none: false })
      const [view, setView] = React.useState({ phase: 'idle' })
      const [selected, setSelected] = React.useState(null)
      const pending = React.useRef(null)
      const used = React.useRef(false)
      React.useEffect(() => () => pending.current?.abort(), [])
      const busy = view.phase === 'running'
      const change = (key, value) => {
        if (busy) return
        if (['record_id', 'candidate_id'].includes(key)) {
          if (key === 'record_id') setSelected(null)
          setForm(old => ({ ...old, [key]: value, exact: false }))
          return
        }
        setForm(old => ({ ...old, [key]: value, policy: false, rules: false, reviewed: false, exact: false, future: false }))
        setView({ phase: 'idle' })
        setSelected(null)
      }
      const field = (key, label, type = 'text') => h('label', { key, style: { display: 'block', margin: '10px 0' } },
        label, h('input', { type, value: form[key], disabled: busy, onChange: e => change(key, e.target.value),
          style: { display: 'block', width: '100%', boxSizing: 'border-box', padding: 8 } }))
      const check = (key, label) => h('label', { key, style: { display: 'block', margin: '10px 0' } },
        h('input', { type: 'checkbox', checked: form[key], disabled: busy,
          onChange: e => ['allow_room_fallback', 'allow_time_fallback'].includes(key)
            ? change(key, e.target.checked) : setForm(old => ({ ...old, [key]: e.target.checked })) }), ` ${label}`)
      const run = (operation, input = {}) => {
        if (pending.current) return
        if (operation === 'booking_execute') {
          if (used.current || !form.exact || !view.value?.result?.id) return
          used.current = true
        }
        const controller = new AbortController()
        pending.current = controller
        setView(old => ({ ...old, phase: 'running', operation }))
        connection.rpc.call('/api', 'hku-agents/library/operator', { operation, input }, controller.signal)
          .then(response => {
            if (controller.signal.aborted) return
            const value = response?.ok === true ? response.value : null
            if (value?.ok !== true) {
              setView({ phase: 'error', operation, code: value?.error?.code || 'HOST_REQUEST_FAILED', uncertain: operation === 'booking_execute' })
              return
            }
            if (operation === 'booking_prepare') used.current = false
            setView({ phase: 'ready', operation, value })
            setForm(old => ({ ...old, reviewed: false, exact: false, future: false, gate: false,
              record_id: operation === 'booking_execute' ? value.result?.task_id || '' : old.record_id }))
          }).catch(() => { if (!controller.signal.aborted) setView({ phase: 'error', operation, code: 'HOST_REQUEST_FAILED', uncertain: operation === 'booking_execute' }) })
          .finally(() => { if (pending.current === controller) pending.current = null })
      }
      const button = (label, operation, input = {}, disabled = false) => h('button', { key: label, type: 'button',
        disabled: busy || disabled, onClick: () => run(operation, typeof input === 'function' ? input() : input), style: { margin: '6px 8px 6px 0' } }, label)
      const target = () => ({ facility_type: form.facility_type, date: form.date, floor: form.floor || null,
        room: form.room, start_time: form.start_time, end_time: form.end_time, eligibility_category: form.eligibility_category })
      const time = value => value ? `${value.length === 16 ? `${value}:00` : value}+08:00` : null
      const schedule = () => ({ facility_type: form.facility_type, target_date: form.date, execution_at: time(form.execution_at),
        prepare_at: time(form.prepare_at), stop_at: time(form.stop_at), poll_interval_seconds: Number(form.poll_interval_seconds),
        max_date_checks: Number(form.max_date_checks), room_preference_order: (form.rooms.trim() || `${form.floor} | ${form.room}`).split('\n').map(line => {
          const parts = line.split('|').map(part => part.trim())
          return parts.length === 2 ? { floor: parts[0] || null, room: parts[1] } : { floor: null, room: parts[0] }
        }), session_preference_order: (form.sessions.trim() || `${form.start_time}-${form.end_time}`).split(',').map(value => {
          const parts = value.trim().split('-'); return { start_time: parts[0], end_time: parts[1] }
        }), allow_room_fallback: form.allow_room_fallback, allow_time_fallback: form.allow_time_fallback,
        eligibility_category: form.eligibility_category, max_runs: 1, shadow_only: true })
      const pilot = () => ({ facility_type: form.facility_type, target_date: form.date, floor: form.floor, room: form.room,
        start_time: form.start_time, end_time: form.end_time, eligibility_category: form.eligibility_category,
        execution_at: time(form.execution_at), prepare_at: time(form.prepare_at), stop_at: time(form.stop_at),
        poll_interval_seconds: Number(form.poll_interval_seconds), max_date_checks: Number(form.max_date_checks) })
      const result = view.value?.result
      const records = result?.rules || result?.runs || result?.drafts || result?.authorizations
      const digest = result?.rule_preview_digest || result?.preview_digest
      const fresh = operation => view.phase === 'ready' && view.operation === operation && typeof digest === 'string'
      return h('section', { style: card, 'aria-label': admin ? 'Library operator interface tests' : 'Library exact workflows' },
        h('h2', null, admin ? 'Library F1–F4 interface tests' : 'Library exact workflows'),
        h('p', null, 'F1 现场查询／预览 · F2 人工确认一次预约 · F3 定时只读观察 · F4 单独授权的受限定时执行。聊天消息不等于预约授权。'),
        h('p', null, 'All date/time fields use Hong Kong time (UTC+8). Live Date options remain authoritative. Target changes invalidate previews.'),
        h('nav', { 'aria-label': 'Library workflow stage' }, ...['F1', 'F2', 'F3', 'F4'].map(stage => h('button', { key: stage,
          disabled: busy, 'aria-pressed': form.stage === stage, onClick: () => change('stage', stage) }, stage))),
        h('label', null, 'Facility', h('select', { value: form.facility_type, disabled: busy, onChange: e => change('facility_type', e.target.value) },
          ...(['F1', 'F2'].includes(form.stage) ? ['discussion_room', 'study_room', 'single_study_room', 'studio_editing_room',
            'study_table', 'av_group_viewing_room', 'communal_virtual_pc', 'computer', 'computer_in_lic',
            'engraving_cutting_computer', 'concept_and_creation_room', 'microform_scanner', 'overhead_scanner',
            'research_desk', 'study_table_deep_quiet'] : ['discussion_room', 'study_room', 'single_study_room',
            'studio_editing_room', 'study_table']).map(value => h('option', { key: value, value }, value)))),
        field('date', 'Facility-use date (not execution date)', 'date'), field('floor', 'Exact floor'), field('room', 'Exact room'),
        field('start_time', 'Exact start time', 'time'), field('end_time', 'Exact end time', 'time'),
        h('label', null, 'Self-declared eligibility', h('select', { value: form.eligibility_category, disabled: busy,
          onChange: e => change('eligibility_category', e.target.value) }, ...['current_hku_students', 'current_hku_staff',
            'current_hku_space_students', 'current_hku_space_staff', 'hku_alumni'].map(value => h('option', { key: value, value }, value)))),
        ['F1', 'F2'].includes(form.stage) ? h('div', null,
          button('Read live dates', 'dates', () => ({ facility_type: form.facility_type })),
          button('Read availability', 'availability', () => ({ facility_type: form.facility_type, date: form.date })),
          button('Create fresh exact preview', 'preview', target)) : null,
        form.stage === 'F2' ? h('div', null,
          h('p', null, 'F2 may submit one real reservation. Core booking gate and policy remain in force. No automatic retry.'),
          result?.preview?.external_submission_enabled === false ? h('p', { role: 'status' },
            'Core booking write gate is disabled. Admin can explicitly enable it before a fresh preview.') : null,
          admin ? h('div', null,
            button('Read F2 booking gate', 'booking_gate_status'),
            check('gate', 'I explicitly review the supervised F2 write gate change. Every booking still requires exact confirmation.'),
            button('Enable supervised F2 gate', 'booking_gate_configure', { enabled: true, operator_acknowledged: true }, !form.gate),
            button('Disable supervised F2 gate', 'booking_gate_configure', { enabled: false, operator_acknowledged: true }, !form.gate)) : null,
          check('policy', 'I accept the displayed facility policy.'), check('rules', 'I reviewed facility/group-size/daily-limit rules.'),
          button('Prepare supervised booking', 'booking_prepare', () => ({ preview_digest: digest,
            policy_acceptance_acknowledged: true, discussion_room_rules_acknowledged: true, facility_rules_acknowledged: true }),
            !fresh('preview') || result?.ready !== true || !form.policy || !form.rules),
          check('exact', 'I reviewed this exact draft and explicitly request one real booking attempt.'),
          button('Confirm and submit once', 'booking_execute', () => ({ id: result.id, preview_digest: result.preview_digest,
            exact_booking_acknowledged: true }), !fresh('booking_prepare') || !form.exact || used.current),
          field('record_id', 'Booking task ID for reconciliation (not retry)'),
          button('Refresh booking outcome', 'booking_result', () => ({ id: form.record_id }), !form.record_id)) : null,
        ['F3', 'F4'].includes(form.stage) ? h('div', null,
          field('prepare_at', 'Preparation (up to 10 minutes before checks)', 'datetime-local'),
          field('execution_at', 'Checks start date/time', 'datetime-local'),
          field('stop_at', 'Stop (within 10 minutes after checks start)', 'datetime-local'),
          field('poll_interval_seconds', 'Date poll interval, 15–120 seconds', 'number'), field('max_date_checks', 'Maximum Date checks, 1–20', 'number')) : null,
        form.stage === 'F3' ? h('div', null,
          h('p', null, 'F3 observes and suggests only; it cannot book.'),
          h('label', null, 'Rooms, one FLOOR | ROOM per line', h('textarea', { value: form.rooms, disabled: busy,
            onChange: e => change('rooms', e.target.value), style: { display: 'block', width: '100%' } })),
          field('sessions', 'Intervals in preference order, e.g. 09:00-10:00, 10:00-11:00'),
          check('allow_room_fallback', 'Allow lower-ranked listed rooms'), check('allow_time_fallback', 'Allow lower-ranked listed intervals'),
          button('Preview read-only schedule', 'shadow_preview', () => ({ rule: schedule() })),
          check('reviewed', 'I reviewed this exact schedule; it creates read-only checks, not booking authority.'),
          button('Create reviewed F3 task', 'shadow_create', () => ({ preview_digest: digest, shadow_only_acknowledged: true }), !fresh('shadow_preview') || !form.reviewed),
          button('Read scheduler status', 'shadow_status'), button('List F3 rules', 'shadow_rules'), button('Refresh F3 runs', 'shadow_runs'),
          field('record_id', 'Selected rule ID (or run ID for feedback)'),
          button('Pause rule', 'shadow_action', () => ({ id: form.record_id, action: 'pause' }), !form.record_id),
          button('Resume rule', 'shadow_action', () => ({ id: form.record_id, action: 'resume' }), !form.record_id),
          check('exact', 'I acknowledge revocation of this selected record.'),
          button('Revoke rule', 'shadow_action', () => ({ id: form.record_id, action: 'revoke', revoke_acknowledged: true }), !form.record_id || !form.exact),
          field('candidate_id', 'Exact suggested candidate ID'), check('none', 'I would book none'),
          button('Record F3 feedback', 'shadow_feedback', () => ({ id: form.record_id, feedback: {
            candidate_id: form.none ? null : form.candidate_id, no_slot_would_be_booked: form.none } }), !form.record_id || (!form.none && !form.candidate_id))) : null,
        form.stage === 'F4' ? h('div', null,
          h('p', { role: 'status' }, 'F4 is disabled until explicitly enabled and an exact authorization is armed. Pilot: Main Library Discussion Room, Level 3, one 60-minute interval, verified empty target day; no fallback. Login/MFA remains manual.'),
          button('Read F4 runtime status', 'f4_executor_status'),
          admin ? h('div', null,
            check('gate', 'I explicitly review this local runtime change. Live mode can submit a real reservation; dry run cannot.'),
            button('Enable F4 dry run', 'f4_executor_configure', { enabled: true, dry_run: true, operator_acknowledged: true }, !form.gate),
            button('Enable F4 live pilot', 'f4_executor_configure', { enabled: true, dry_run: false, operator_acknowledged: true }, !form.gate),
            button('Disable F4 runtime', 'f4_executor_configure', { enabled: false, dry_run: false, operator_acknowledged: true }, !form.gate)) : null,
          button('Preview inert F4 draft', 'f4_draft_preview', pilot, form.facility_type !== 'discussion_room'),
          check('reviewed', 'I reviewed the draft and understand it grants no booking authority.'),
          button('Save inert draft', 'f4_draft_create', () => ({ preview_digest: digest, non_authorizing_acknowledged: true }), !fresh('f4_draft_preview') || !form.reviewed),
          button('Preview pending authorization', 'f4_authorization_preview', pilot, form.facility_type !== 'discussion_room'),
          check('future', 'I acknowledge one future exact attempt if the executor is separately enabled.'),
          check('policy', 'I accept the reviewed facility policy.'), check('rules', 'I reviewed Discussion Room rules.'),
          button('Save authorization — pending executor', 'f4_authorization_create', () => ({ preview_digest: digest,
            future_booking_acknowledged: true, policy_acceptance_acknowledged: true, discussion_room_rules_acknowledged: true }),
            !fresh('f4_authorization_preview') || !form.future || !form.policy || !form.rules),
          button('List inert drafts', 'f4_drafts'), button('List pending authorizations', 'f4_authorizations'),
          field('record_id', 'Selected draft / authorization ID'), check('exact', 'I reviewed the selected exact record and explicitly acknowledge this arm/revoke action.'),
          selected ? h('pre', { style: { whiteSpace: 'pre-wrap' } }, JSON.stringify({ state: selected.state, exact_target: selected.exact_target,
            dry_run: selected.dry_run, phase: selected.phase, error_code: selected.error_code,
            execution_result: selected.execution_result, started_at: selected.started_at, completed_at: selected.completed_at,
            diagnostics: selected.diagnostics }, null, 2)) : null,
          button('Arm selected exact authorization', 'f4_authorization_arm', () => ({ id: selected.id, arming_digest: selected.arming_digest,
            exact_booking_acknowledged: true, future_booking_acknowledged: true, policy_acceptance_acknowledged: true,
            discussion_room_rules_acknowledged: true }), !selected?.arming_digest || !selected?.execution_enabled ||
              !form.exact || !form.future || !form.policy || !form.rules),
          button('Revoke inert draft', 'f4_draft_revoke', () => ({ id: form.record_id }), !form.record_id || !form.exact),
          button('Pause authorization', 'f4_authorization_action', () => ({ id: form.record_id, action: 'pause' }), !form.record_id),
          button('Revoke authorization', 'f4_authorization_action', () => ({ id: form.record_id, action: 'revoke' }), !form.record_id || !form.exact)) : null,
        busy ? h('p', { role: 'status' }, 'Working through Core. Do not repeat a submission.') : null,
        view.phase === 'error' ? h('p', { role: 'alert' }, `Operation failed (${view.code}). ${view.uncertain
          ? 'Submission may be unknown. Do not retry; reconcile My Booking Record / Core task first.'
          : 'Check exact input, login, Core policy/gate and preview expiry.'}`) : null,
        view.phase === 'ready' ? h('div', { role: 'status' },
          h('p', null, `Operation: ${view.operation} | Task: ${view.value.task_id || 'none'} | Correlation: ${view.value.correlation_id || 'none'}`),
          h('p', null, view.operation === 'booking_execute' ? 'Submission requested, not yet verified as booked.'
            : view.operation === 'booking_result' ? (result?.result?.exact_target_verified_in_booking_record === true &&
              result?.result?.record_match_count === 1 ? 'One exact My Booking Record match verified.'
              : `Booking task: ${result?.state || 'unknown'}. Exact record success is not verified; do not retry an ambiguous submission.`)
            : form.stage === 'F4' ? 'Saved/reviewed is not executed or booked.' : 'Review domain result, not just request completion.'),
          view.value.history_warning ? h('p', { role: 'alert' }, view.value.history_warning) : null,
          Array.isArray(records) ? h('ul', null, ...records.map(row => h('li', { key: row.id },
            `${row.state || row.outcome || 'record'}${row.phase ? ` / ${row.phase}` : ''} | ${row.id} | ${row.next_run_at || row.scheduled_at_local || 'no scheduled run'}${row.error_code ? ` | ${row.error_code}` : ''}`,
            h('button', { type: 'button', onClick: () => { setSelected(row); setForm(old => ({ ...old, record_id: row.id,
              candidate_id: row.suggested_candidate_id || '', exact: false, future: false, policy: false, rules: false, none: false })) } }, 'Select record')))) : null,
          h('details', { open: admin || !records }, h('summary', null, 'Exact result / policy details'),
            h('pre', { style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 420, overflowY: 'auto' } }, JSON.stringify(result, null, 2)))) : null)
    }

    function AdminPanel({ connection }) {
      const [view, setView] = React.useState({ phase: 'idle' })
      const pending = React.useRef(null)
      const runCatalogTest = () => {
        if (pending.current) return
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
        }).finally(() => { if (pending.current === controller) pending.current = null })
      }
      React.useEffect(() => () => pending.current?.abort(), [])
      const value = view.value
      return h('main', { style: surface, 'aria-label': 'HKU AGENTS Admin' },
        h('div', { style: { maxWidth: 960, margin: '0 auto' } },
          h('h1', { style: { margin: '0 0 8px', fontSize: 26 } }, 'HKU AGENTS Admin'),
          h('p', { style: { color: 'var(--dsw-alias-label-secondary)' } },
            '管理员接口测试与诊断。业务操作以 Agent Chat 为主；本地检查通过不等于现场预约验收通过。'),
          h(Workbench, { connection }),
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
          h('details', { style: card }, h('summary', null, 'SIS：课程列表、预检与课表'),
            h(SISAdminSection, { connection }), h(ReadOnlyAdminSection, { connection, domain: 'SIS timetable' })),
          h('details', { style: card }, h('summary', null, 'Moodle：Dashboard、课程与截止日期'),
            h(ReadOnlyAdminSection, { connection, domain: 'Moodle' })),
          h('details', { style: card }, h('summary', null, 'Portal：公告与每日简报'),
            h(ReadOnlyAdminSection, { connection, domain: 'Portal and briefing' })),
          h('details', { style: card }, h('summary', null, 'Library：只读查询与 F1–F4 操作'),
            h(ReadOnlyAdminSection, { connection, domain: 'Library reads' }), h(LibraryWorkflowSection, { connection, admin: true })),
          h(TaskCenter, { connection }),
          h('details', { style: card }, h('summary', null, '测试历史与人工验收标记'), h(HistorySection, { connection })),
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
