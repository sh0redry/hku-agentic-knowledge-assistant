import test from 'node:test'
import assert from 'node:assert/strict'
import { compactProjection, toolPresentation } from '../lib/presentation.js'
import { apply } from '../lib/index.js'

test('all tools declare pure pending/result cards without changing model outputs', () => {
  const tools = []
  apply({ inject() {}, tools: { register(t) { tools.push(t) } } }, { baseUrl: 'http://127.0.0.1:7860', tokenEnv: 'INTEGRATION_API_TOKEN', timeoutMs: 45000 })
  assert.equal(tools.length, 23)
  for (const tool of tools) {
    assert.equal(typeof tool.presentCall, 'function')
    assert.equal(typeof tool.presentResult, 'function')
    const presentation = toolPresentation(tool.name)
    assert.equal(presentation.presentCall({ token: 'SECRET' }).card, 'generic')
    assert.doesNotMatch(JSON.stringify(presentation.presentCall({ token: 'SECRET' })), /SECRET/)
    const value = { ok: true, read_only: true, result: { domain_writes_performed: 0, course_list: { course_count: 2, courses: [{ title: 'PRIVATE' }] } } }
    const meta = tool.output.presentationMeta({}, value)
    assert.doesNotMatch(JSON.stringify(meta), /PRIVATE/)
    const content = tool.output.render({}, value)
    assert.match(JSON.stringify(content), /PRIVATE/, 'canonical model content remains available')
    const view = presentation.presentResult({}, { meta, content, isError: false })
    assert.doesNotMatch(JSON.stringify(view), /PRIVATE/)
    assert.match(JSON.stringify(view), /course count/)
  }
})

test('cards distinguish cache, partial sources, writes and unverified envelopes', () => {
  const v = { ok: true, read_only: true, result: { derived_locally: true, complete: false,
    source_status: { timetable: { status: 'stale' }, moodle_assignments: { status: 'missing' } } } }
  const p = compactProjection(v)
  assert.equal(p.complete, false)
  assert.equal(p.source_timetable, 'stale')
  assert.match(p.source, /cache/)
  assert.match(p.domain_writes, /not verified/)
  assert.equal(compactProjection({ ...v, ok: false }).state, 'Result not verified')
  const card = toolPresentation('hku_sis_next_class').presentResult({}, { meta: p, content: [], isError: false })
  assert.match(card.content[0].text, /holidays/)
  assert.match(toolPresentation('hku_moodle_upcoming_assignments').presentResult({}, { isError: true }).content[0].text, /not.*empty/)
})
