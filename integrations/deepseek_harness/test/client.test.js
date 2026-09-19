import assert from 'node:assert/strict'
import { once } from 'node:events'
import http from 'node:http'
import test from 'node:test'

import { apply } from '../lib/index.js'
import { HKUAgentsAPIError, HKUAgentsClient } from '../lib/client.js'

const TOKEN = 'test-hku-agents-token-12345678901234567890'

function envelope(result, correlationId = 'server-correlation') {
  return {
    api_version: 'v1',
    ok: true,
    read_only: true,
    correlation_id: correlationId,
    result,
    task: null,
    error: null,
  }
}

async function withServer(handler, run) {
  const server = http.createServer(handler)
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const address = server.address()
  assert.equal(typeof address, 'object')
  try {
    await run(`http://127.0.0.1:${address.port}`)
  } finally {
    server.close()
    await once(server, 'close')
  }
}

test('client rejects non-loopback targets before reading a token', () => {
  assert.throws(
    () =>
      new HKUAgentsClient({
        baseUrl: 'https://example.com',
        tokenEnv: 'INTEGRATION_API_TOKEN',
        timeoutMs: 5000,
      }),
    error => error instanceof HKUAgentsAPIError && error.code === 'NON_LOOPBACK_BASE_URL',
  )
})

test('client sends bearer auth and accepts the versioned read-only envelope', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  try {
    await withServer(
      (request, response) => {
        assert.equal(request.url, '/api/v1/integration/status')
        assert.equal(request.headers.authorization, `Bearer ${TOKEN}`)
        assert.match(request.headers['x-correlation-id'], /^[0-9a-f-]{36}$/)
        response.setHeader('content-type', 'application/json')
        response.end(JSON.stringify(envelope({ service: 'hku-agents' })))
      },
      async baseUrl => {
        const client = new HKUAgentsClient({
          baseUrl,
          tokenEnv: 'INTEGRATION_API_TOKEN',
          timeoutMs: 5000,
        })
        const result = await client.status()
        assert.equal(result.result.service, 'hku-agents')
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})

test('client preserves stable API errors without leaking the token', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  try {
    await withServer(
      (_request, response) => {
        response.statusCode = 409
        response.setHeader('content-type', 'application/json')
        response.end(
          JSON.stringify({
            ...envelope(null),
            ok: false,
            error: {
              code: 'BROWSER_NOT_CONNECTED',
              message: 'Extension is not connected.',
              recovery: 'Pair the extension.',
              details: null,
            },
          }),
        )
      },
      async baseUrl => {
        const client = new HKUAgentsClient({
          baseUrl,
          tokenEnv: 'INTEGRATION_API_TOKEN',
          timeoutMs: 5000,
        })
        await assert.rejects(
          client.syncCourseLists(),
          error =>
            error instanceof HKUAgentsAPIError &&
            error.code === 'BROWSER_NOT_CONNECTED' &&
            !error.message.includes(TOKEN),
        )
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})

test('plugin registers exactly nineteen restricted HKU tools and forwards preflight input', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  let receivedBody
  try {
    await withServer(
      (request, response) => {
        const chunks = []
        request.on('data', chunk => chunks.push(chunk))
        request.on('end', () => {
          receivedBody = JSON.parse(Buffer.concat(chunks).toString('utf8'))
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify(envelope({ ready: false, sis_write_requests_sent: 0 })))
        })
      },
      async baseUrl => {
        const tools = []
        const ctx = { tools: { register(tool) { tools.push(tool) } } }
        apply(ctx, { baseUrl, tokenEnv: 'INTEGRATION_API_TOKEN', timeoutMs: 5000 })
        assert.deepEqual(
          tools.map(tool => tool.name),
          [
            'hku_sis_status',
            'hku_sis_navigate_and_preflight',
            'hku_sis_open_enrollment_add_classes',
            'hku_sis_sync_course_lists',
            'hku_sis_preflight',
            'hku_sis_timetable_sync',
            'hku_sis_next_class',
            'hku_sis_find_free_slots',
            'hku_sis_check_timetable_conflicts',
            'hku_sis_exam_status',
            'hku_moodle_inspect_dashboard',
            'hku_moodle_list_courses',
            'hku_moodle_upcoming_assignments',
            'hku_portal_list_notices',
            'hku_daily_briefing',
            'hku_library_research_search',
            'hku_library_space_availability',
            'hku_library_research_item',
            'hku_library_research_access_options',
          ],
        )

        const preflight = tools.find(tool => tool.name === 'hku_sis_preflight')
        const result = await preflight.execute(
          {
            term_label: '2026-27 Sem 2',
            expected_courses: [{ course_code: 'COMP3297', section: '2B' }],
          },
          { signal: new AbortController().signal },
        )
        assert.equal(result.result.ready, false)
        assert.equal(result.result.sis_write_requests_sent, 0)
        assert.deepEqual(receivedBody, {
          term_label: '2026-27 Sem 2',
          expected_courses: [{ course_code: 'COMP3297', section: '2B' }],
        })
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})

test('Library tools forward only bounded structured search, record, and facility inputs', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  const requests = []
  try {
    await withServer(
      (request, response) => {
        const chunks = []
        request.on('data', chunk => chunks.push(chunk))
        request.on('end', () => {
          requests.push({ url: request.url, body: JSON.parse(Buffer.concat(chunks).toString('utf8')) })
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify(envelope({ read_only: true, library_writes_performed: 0 })))
        })
      },
      async baseUrl => {
        const tools = []
        const ctx = { tools: { register(tool) { tools.push(tool) } } }
        apply(ctx, { baseUrl, tokenEnv: 'INTEGRATION_API_TOKEN', timeoutMs: 5000 })
        await tools.find(tool => tool.name === 'hku_library_research_search').execute(
          { query: 'artificial intelligence', field: 'title', scope: 'hku', limit: 5 },
          { signal: new AbortController().signal },
        )
        await tools.find(tool => tool.name === 'hku_library_space_availability').execute(
          { facility_type: 'single_study_room' },
          { signal: new AbortController().signal },
        )
        await tools.find(tool => tool.name === 'hku_library_research_item').execute(
          { record_id: 'alma991234' },
          { signal: new AbortController().signal },
        )
        await tools.find(tool => tool.name === 'hku_library_research_access_options').execute(
          { record_id: 'alma991234' },
          { signal: new AbortController().signal },
        )
        assert.deepEqual(requests, [
          {
            url: '/api/v1/integration/library/research/search',
            body: { query: 'artificial intelligence', field: 'title', scope: 'hku', limit: 5 },
          },
          {
            url: '/api/v1/integration/library/spaces/search-availability',
            body: { facility_type: 'single_study_room' },
          },
          {
            url: '/api/v1/integration/library/research/item',
            body: { record_id: 'alma991234' },
          },
          {
            url: '/api/v1/integration/library/research/access-options',
            body: { record_id: 'alma991234' },
          },
        ])
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})

test('timetable sync tool forwards only the exact term to the Phase B endpoint', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  try {
    await withServer(
      (request, response) => {
        assert.equal(request.method, 'POST')
        assert.equal(request.url, '/api/v1/integration/sis/timetable/sync-weekly')
        const chunks = []
        request.on('data', chunk => chunks.push(chunk))
        request.on('end', () => {
          assert.deepEqual(JSON.parse(Buffer.concat(chunks).toString('utf8')), {
            term_label: '2026-27 Sem 1',
          })
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify(envelope({
            read_only: true,
            domain_writes_performed: 0,
            timetable: { meeting_count: 7 },
          })))
        })
      },
      async baseUrl => {
        const tools = []
        const ctx = { tools: { register(tool) { tools.push(tool) } } }
        apply(ctx, { baseUrl, tokenEnv: 'INTEGRATION_API_TOKEN', timeoutMs: 5000 })
        const sync = tools.find(tool => tool.name === 'hku_sis_timetable_sync')
        const result = await sync.execute(
          {
            term_label: '2026-27 Sem 1',
            sis_session_reused: false,
            navigation_interactions_performed: true,
          },
          { signal: new AbortController().signal },
        )
        assert.equal(result.result.domain_writes_performed, 0)
        assert.equal(result.result.timetable.meeting_count, 7)
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})

test('three derived timetable tools forward cache-only calculation inputs', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  const received = []
  try {
    await withServer(
      (request, response) => {
        const chunks = []
        request.on('data', chunk => chunks.push(chunk))
        request.on('end', () => {
          const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
          received.push({ url: request.url, body })
          let result
          if (request.url.endsWith('/next-class')) {
            result = { derived_locally: true, browser_interactions_performed: false, next_class: { course_code: 'COMP3230' } }
          } else if (request.url.endsWith('/free-slots')) {
            result = { derived_locally: true, browser_interactions_performed: false, free_slots: [] }
          } else {
            result = { derived_locally: true, browser_interactions_performed: false, has_conflicts: true, conflict_count: 1 }
          }
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify(envelope(result)))
        })
      },
      async baseUrl => {
        const tools = []
        const ctx = { tools: { register(tool) { tools.push(tool) } } }
        apply(ctx, { baseUrl, tokenEnv: 'INTEGRATION_API_TOKEN', timeoutMs: 5000 })
        const execution = { signal: new AbortController().signal }
        const next = await tools.find(tool => tool.name === 'hku_sis_next_class').execute(
          { term_label: '2026-27 Sem 1', as_of: '2026-09-14T12:00:00+08:00', days_ahead: 7 },
          execution,
        )
        const free = await tools.find(tool => tool.name === 'hku_sis_find_free_slots').execute(
          { term_label: '2026-27 Sem 1', weekdays: ['monday'], window_start: '09:00', window_end: '18:00', minimum_minutes: 60 },
          execution,
        )
        const conflicts = await tools.find(tool => tool.name === 'hku_sis_check_timetable_conflicts').execute(
          {
            term_label: '2026-27 Sem 1',
            candidate_meetings: [{ course_code: 'COMP9999', section: '1A', weekday: 'monday', start_time: '13:30', end_time: '14:00' }],
          },
          execution,
        )
        for (const output of [next, free, conflicts]) {
          assert.equal(output.result.derived_locally, true)
          assert.equal(output.result.browser_interactions_performed, false)
        }
      },
    )
    assert.deepEqual(received, [
      {
        url: '/api/v1/integration/sis/timetable/next-class',
        body: { term_label: '2026-27 Sem 1', as_of: '2026-09-14T12:00:00+08:00', days_ahead: 7 },
      },
      {
        url: '/api/v1/integration/sis/timetable/free-slots',
        body: { term_label: '2026-27 Sem 1', weekdays: ['monday'], window_start: '09:00', window_end: '18:00', minimum_minutes: 60 },
      },
      {
        url: '/api/v1/integration/sis/timetable/check-conflicts',
        body: {
          term_label: '2026-27 Sem 1',
          candidate_meetings: [{ course_code: 'COMP9999', section: '1A', weekday: 'monday', start_time: '13:30', end_time: '14:00' }],
        },
      },
    ])
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})

test('Moodle diagnostic tool sends an empty read-only inspection request', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  try {
    await withServer(
      (request, response) => {
        assert.equal(request.method, 'POST')
        assert.equal(request.url, '/api/v1/integration/moodle/dashboard/inspect')
        const chunks = []
        request.on('data', chunk => chunks.push(chunk))
        request.on('end', () => {
          assert.deepEqual(JSON.parse(Buffer.concat(chunks).toString('utf8')), {})
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify(envelope({
            read_only: true,
            course_data_read: false,
            assignment_data_read: false,
            moodle_writes_performed: 0,
          })))
        })
      },
      async baseUrl => {
        const tools = []
        const ctx = { tools: { register(tool) { tools.push(tool) } } }
        apply(ctx, { baseUrl, tokenEnv: 'INTEGRATION_API_TOKEN', timeoutMs: 5000 })
        const tool = tools.find(item => item.name === 'hku_moodle_inspect_dashboard')
        const result = await tool.execute({}, { signal: new AbortController().signal })
        assert.equal(result.result.course_data_read, false)
        assert.equal(result.result.assignment_data_read, false)
        assert.equal(result.result.moodle_writes_performed, 0)
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})

test('Moodle course tool sends an empty request and preserves privacy indicators', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  try {
    await withServer(
      (request, response) => {
        assert.equal(request.method, 'POST')
        assert.equal(request.url, '/api/v1/integration/moodle/courses/list')
        const chunks = []
        request.on('data', chunk => chunks.push(chunk))
        request.on('end', () => {
          assert.deepEqual(JSON.parse(Buffer.concat(chunks).toString('utf8')), {})
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify(envelope({
            read_only: true,
            course_membership_read: true,
            assignment_data_read: false,
            grade_data_read: false,
            moodle_writes_performed: 0,
          })))
        })
      },
      async baseUrl => {
        const tools = []
        const ctx = { tools: { register(tool) { tools.push(tool) } } }
        apply(ctx, { baseUrl, tokenEnv: 'INTEGRATION_API_TOKEN', timeoutMs: 5000 })
        const tool = tools.find(item => item.name === 'hku_moodle_list_courses')
        const result = await tool.execute({}, { signal: new AbortController().signal })
        assert.equal(result.result.course_membership_read, true)
        assert.equal(result.result.assignment_data_read, false)
        assert.equal(result.result.grade_data_read, false)
        assert.equal(result.result.moodle_writes_performed, 0)
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})

test('Moodle assignment tool forwards only the bounded window and preserves privacy indicators', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  try {
    await withServer(
      (request, response) => {
        assert.equal(request.method, 'POST')
        assert.equal(request.url, '/api/v1/integration/moodle/assignments/upcoming')
        const chunks = []
        request.on('data', chunk => chunks.push(chunk))
        request.on('end', () => {
          assert.deepEqual(JSON.parse(Buffer.concat(chunks).toString('utf8')), {
            days_ahead: 14,
          })
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify(envelope({
            read_only: true,
            assignment_data_read: true,
            grade_data_read: false,
            submission_data_read: false,
            activity_pages_opened: 0,
            moodle_writes_performed: 0,
          })))
        })
      },
      async baseUrl => {
        const tools = []
        const ctx = { tools: { register(tool) { tools.push(tool) } } }
        apply(ctx, { baseUrl, tokenEnv: 'INTEGRATION_API_TOKEN', timeoutMs: 5000 })
        const tool = tools.find(item => item.name === 'hku_moodle_upcoming_assignments')
        const result = await tool.execute(
          { days_ahead: 14 },
          { signal: new AbortController().signal },
        )
        assert.equal(result.result.assignment_data_read, true)
        assert.equal(result.result.grade_data_read, false)
        assert.equal(result.result.submission_data_read, false)
        assert.equal(result.result.activity_pages_opened, 0)
        assert.equal(result.result.moodle_writes_performed, 0)
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})

test('Portal notice tool sends an empty read-only request', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  try {
    await withServer(
      (request, response) => {
        assert.equal(request.method, 'POST')
        assert.equal(request.url, '/api/v1/integration/portal/notices/list')
        const chunks = []
        request.on('data', chunk => chunks.push(chunk))
        request.on('end', () => {
          assert.deepEqual(JSON.parse(Buffer.concat(chunks).toString('utf8')), {})
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify(envelope({
            read_only: true,
            navigation_interactions_performed: false,
            portal_writes_performed: 0,
            notice_detail_pages_opened: 0,
          })))
        })
      },
      async baseUrl => {
        const tools = []
        const ctx = { tools: { register(tool) { tools.push(tool) } } }
        apply(ctx, { baseUrl, tokenEnv: 'INTEGRATION_API_TOKEN', timeoutMs: 5000 })
        const tool = tools.find(item => item.name === 'hku_portal_list_notices')
        const result = await tool.execute({}, { signal: new AbortController().signal })
        assert.equal(result.result.navigation_interactions_performed, false)
        assert.equal(result.result.portal_writes_performed, 0)
        assert.equal(result.result.notice_detail_pages_opened, 0)
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})

test('daily briefing tool forwards only cache-derived inputs', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  try {
    await withServer(
      (request, response) => {
        assert.equal(request.method, 'POST')
        assert.equal(request.url, '/api/v1/integration/briefing/today')
        const chunks = []
        request.on('data', chunk => chunks.push(chunk))
        request.on('end', () => {
          assert.deepEqual(JSON.parse(Buffer.concat(chunks).toString('utf8')), {
            term_label: '2026-27 Sem 1',
            days_ahead: 7,
            max_cache_age_minutes: 120,
          })
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify(envelope({
            read_only: true,
            derived_locally: true,
            browser_interactions_performed: false,
            domain_writes_performed: 0,
            complete: true,
          })))
        })
      },
      async baseUrl => {
        const tools = []
        const ctx = { tools: { register(tool) { tools.push(tool) } } }
        apply(ctx, { baseUrl, tokenEnv: 'INTEGRATION_API_TOKEN', timeoutMs: 5000 })
        const tool = tools.find(item => item.name === 'hku_daily_briefing')
        const result = await tool.execute(
          {
            term_label: '2026-27 Sem 1',
            days_ahead: 7,
            max_cache_age_minutes: 120,
          },
          { signal: new AbortController().signal },
        )
        assert.equal(result.result.derived_locally, true)
        assert.equal(result.result.browser_interactions_performed, false)
        assert.equal(result.result.domain_writes_performed, 0)
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})

test('navigation tool sends only the validated target term to the fixed local endpoint', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  try {
    await withServer(
      (request, response) => {
        assert.equal(request.method, 'POST')
        assert.equal(request.url, '/api/v1/integration/sis/navigate')
        const chunks = []
        request.on('data', chunk => chunks.push(chunk))
        request.on('end', () => {
          assert.deepEqual(
            JSON.parse(Buffer.concat(chunks).toString('utf8')),
            { term_label: '2026-27 Sem 2' },
          )
          response.setHeader('content-type', 'application/json')
          response.end(
            JSON.stringify(
              envelope({
                read_only: true,
                navigation_only: true,
                sis_write_requests_sent: 0,
                target_page_kind: 'cart',
              }),
            ),
          )
        })
      },
      async baseUrl => {
        const client = new HKUAgentsClient({
          baseUrl,
          tokenEnv: 'INTEGRATION_API_TOKEN',
          timeoutMs: 5000,
        })
        const result = await client.navigateToEnrollmentAddClasses({
          term_label: '2026-27 Sem 2',
        })
        assert.equal(result.result.navigation_only, true)
        assert.equal(result.result.sis_write_requests_sent, 0)
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})

test('combined tool forwards only term and expected course intent', async () => {
  const previous = process.env.INTEGRATION_API_TOKEN
  process.env.INTEGRATION_API_TOKEN = TOKEN
  try {
    await withServer(
      (request, response) => {
        assert.equal(request.method, 'POST')
        assert.equal(request.url, '/api/v1/integration/sis/navigate-and-preflight')
        const chunks = []
        request.on('data', chunk => chunks.push(chunk))
        request.on('end', () => {
          assert.deepEqual(JSON.parse(Buffer.concat(chunks).toString('utf8')), {
            term_label: '2026-27 Sem 2',
            expected_courses: [{ course_code: 'COMP3297', section: '2B' }],
          })
          response.setHeader('content-type', 'application/json')
          response.end(
            JSON.stringify(
              envelope({
                ready: true,
                read_only: true,
                sis_write_requests_sent: 0,
                navigation_interactions_performed: true,
                term_selection_performed: true,
                enrollment_writes_performed: 0,
              }),
            ),
          )
        })
      },
      async baseUrl => {
        const tools = []
        const ctx = { tools: { register(tool) { tools.push(tool) } } }
        apply(ctx, { baseUrl, tokenEnv: 'INTEGRATION_API_TOKEN', timeoutMs: 5000 })
        const combined = tools.find(tool => tool.name === 'hku_sis_navigate_and_preflight')
        const result = await combined.execute(
          {
            term_label: '2026-27 Sem 2',
            expected_courses: [{ course_code: 'COMP3297', section: '2B' }],
          },
          { signal: new AbortController().signal },
        )
        assert.equal(result.result.ready, true)
        assert.equal(result.result.sis_write_requests_sent, 0)
        assert.equal(result.result.navigation_interactions_performed, true)
        assert.equal(result.result.term_selection_performed, true)
        assert.equal(result.result.enrollment_writes_performed, 0)
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})
