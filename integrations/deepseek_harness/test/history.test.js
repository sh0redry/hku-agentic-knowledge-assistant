import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { TestHistory, historyRoute, recordRoute, safeDiagnostics } from '../lib/history.js'

test('history persists redacted records and human verdict, serializes concurrent writes and caps retention', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'hku-history-'))
  try {
    const path = join(dir, 'history.json'); const store = new TestHistory(path)
    const recordId = await store.append('moodle_assignments', { ok: true, domain_writes_performed: 0, input: { token: 'SECRET' },
      summary: { title: 'PRIVATE' }, diagnostics: { parser_version: '0.4.2', parsed_assignment_count: 8, raw_dom: 'SECRET' } })
    await store.review(recordId, 'pass')
    assert.equal((await new TestHistory(path).list())[0].verdict, 'pass')
    assert.doesNotMatch(await readFile(path, 'utf8'), /PRIVATE|SECRET|raw_dom|input|summary/)
    await assert.rejects(store.append('book', {}))
    await assert.rejects(store.review(recordId, 'authorize'))
    await Promise.all(Array.from({ length: 101 }, () => store.append('library_dates', { ok: false, error: { code: 'PORTAL_LOGIN_REQUIRED', message: 'SECRET' } })))
    assert.equal((await store.list()).length, 100)
    assert.equal(new Set((await store.list()).map(r => r.id)).size, 100)
    await writeFile(path, '{broken')
    await assert.rejects(store.append('library_dates', {}))
    assert.equal(await readFile(path, 'utf8'), '{broken', 'corrupt history must not be silently overwritten')
  } finally { await rm(dir, { recursive: true, force: true }) }
})

test('fixed history routes reject arbitrary data and record wrapper never persists private response', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'hku-history-'))
  try {
    const store = new TestHistory(join(dir, 'history.json'))
    const read = recordRoute({ path: '/read', methods: ['POST'], requestBody: 'buffered', async fetch() {
      return new Response(JSON.stringify({ result: { value: { ok: true, summary: { rows: ['PRIVATE'] }, domain_writes_performed: 0 } } }))
    } }, 'library_research', store)
    const response = await (await read.fetch(new Request('http://test/read'))).json()
    assert.ok(response.result.value.history_record_id)
    assert.equal(response.result.value.summary.rows[0], 'PRIVATE', 'immediate response is unchanged')
    const route = historyRoute('list', store)
    const req = payload => new Request('http://test' + route.path, { method: 'POST', body: JSON.stringify({ type: 'client-request', rpcId: '12345678-1234-4123-8123-123456789abc', method: 'hku-agents/admin/history/list', payload }) })
    assert.equal((await route.fetch(req({ url: 'https://remote' }))).status, 400)
    assert.equal((await route.fetch(new Request('http://test' + route.path))).status, 405)
    const list = await (await route.fetch(req({}))).json()
    assert.equal(list.result.value.records.length, 1)
    assert.doesNotMatch(JSON.stringify(list), /PRIVATE/)
    assert.deepEqual(safeDiagnostics({ unclassified_cell_shapes: ['PRIVATE'], parser_version: 'urlsecret', parsed_assignment_count: 8 }), { parsed_assignment_count: 8 })
  } finally { await rm(dir, { recursive: true, force: true }) }
})
