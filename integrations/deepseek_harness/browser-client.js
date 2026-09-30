// Browser half for DeepSeek Harness Desktop 0.2.0-rc.2. The loader expects
// this module wrapper, not Node's ESM format. No API credential enters here.
window.__ModuleLoader__.load({
  id: 'dsh-hku-agents',
  factory: require => {
    const React = require('react')
    const h = React.createElement
    const PANEL_ID = 'hku-agents'
    const ADMIN_PANEL_ID = 'hku-agents-admin'

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
      const load = () => {
        pending.current?.abort()
        const controller = new AbortController()
        pending.current = controller
        setView({ phase: 'loading' })
        connection.rpc.call('/api', 'hku-agents/status', {}, controller.signal).then(result => {
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
        })
      }
      React.useEffect(() => {
        load()
        const unsubscribe = connection.state.subscribe(() => {
          if (connection.state.getSnapshot() === 'connected') load()
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
            status?.correlation_id ? h('p', { style: { fontSize: 12 } }, `Correlation ID: ${status.correlation_id}`) : null,
            h('button', { type: 'button', onClick: load, disabled: view.phase === 'loading' }, 'Refresh status'),
            h('p', { style: { color: 'var(--dsw-alias-label-secondary)' } },
              'Keep HKU AGENTS running locally and complete HKU sign-in in Chrome. The Host uses a separate Integration API token; no token or HKU cookie is stored in this panel.')),
          h('section', { style: card, 'aria-labelledby': 'hku-tools-heading' },
            h('h2', { id: 'hku-tools-heading', style: { marginTop: 0, fontSize: 18 } }, 'Available now'),
            h('p', null, 'The installed Host adapter contributes 22 bounded, read-only SIS, Moodle, Portal and Library tools to Harness conversations.'),
            h('p', null, 'For booking, recurring checks, or recovery, continue using the HKU AGENTS local GUI. This panel cannot select a slot, submit a booking, or authorize F4.')),
          h('section', { style: card, 'aria-labelledby': 'hku-next-heading' },
            h('h2', { id: 'hku-next-heading', style: { marginTop: 0, fontSize: 18 } }, 'Next integration gate'),
            h('p', null, 'This panel reads only a redacted status projection. Focused Chat result cards and the Admin interface-test workbench are next.'))))
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
          h('p', { style: { color: 'var(--dsw-alias-label-secondary)' } },
            'This is the first bounded Admin test. It does not verify live availability, account eligibility, or F2 booking acceptance.')))
    }

    const inject = ['slots', 'layout', 'connection']
    function apply(ctx) {
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
