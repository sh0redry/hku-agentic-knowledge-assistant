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

test('plugin registers exactly five restricted HKU tools and forwards preflight input', async () => {
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
      },
    )
  } finally {
    if (previous === undefined) delete process.env.INTEGRATION_API_TOKEN
    else process.env.INTEGRATION_API_TOKEN = previous
  }
})
