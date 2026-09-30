import assert from 'node:assert/strict'
import test from 'node:test'

import { DESKTOP_FACILITIES_PATH, desktopFacilitiesRoute, readDesktopFacilities } from '../lib/desktop_admin.js'

const rpcId = '12345678-1234-4123-8123-123456789abc'
const requestBody = JSON.stringify({ type: 'client-request', rpcId, method: 'hku-agents/admin/facilities', payload: {} })

function request(body = requestBody) {
  return new Request(`http://desktop.local${DESKTOP_FACILITIES_PATH}`, {
    method: 'POST', body,
  })
}

function catalogEnvelope() {
  return {
    correlation_id: 'safe-id',
    result: {
      read_only: true, derived_locally: true, browser_interactions_performed: false,
      domain_writes_performed: 0, library_writes_performed: 0, booking_writes_performed: 0,
      slot_selection_performed: false, booking_form_opened: false,
      facility_count: 1, availability_target_count: 1,
      policy_verified_on: '2026-09-24',
      facilities: [{
        facility_type: 'discussion_room', name: 'Discussion Rooms', location: 'Main Library',
        booking_policy: { secret: 'not-for-panel' },
      }],
      availability_targets: [{
        facility_type: 'discussion_room', location: 'Main Library', booking_facility_type: 'Discussion Room',
        availability_search_supported: true, booking_preview_supported: true, supervised_booking_supported: true,
        private_url: 'https://private.example/',
      }],
    },
  }
}

test('Admin catalog route is exact, read-only and redacts unused Core fields', async () => {
  let calls = 0
  const route = desktopFacilitiesRoute({ async listLibraryFacilities() { calls++; return catalogEnvelope() } })
  assert.equal(route.path, DESKTOP_FACILITIES_PATH)
  assert.deepEqual(route.methods, ['POST'])
  const response = await route.fetch(request())
  assert.equal(response.status, 200)
  assert.equal(response.headers.get('cache-control'), 'no-store')
  const body = await response.json()
  assert.equal(body.type, 'server-response')
  assert.equal(body.rpcId, rpcId)
  assert.equal(body.result.value.ok, true)
  assert.equal(body.result.value.facility_count, 1)
  assert.equal(body.result.value.booking_writes_performed, 0)
  assert.deepEqual(body.result.value.facilities, [
    { facility_type: 'discussion_room', name: 'Discussion Rooms', location: 'Main Library' },
  ])
  assert.equal(calls, 1)
  assert.doesNotMatch(JSON.stringify(body), /not-for-panel|private\.example/)
})

test('Admin catalog route rejects write methods and nonempty arguments before Core call', async () => {
  let calls = 0
  const route = desktopFacilitiesRoute({ async listLibraryFacilities() { calls++; return catalogEnvelope() } })
  for (const body of [
    '{}',
    JSON.stringify({ type: 'client-request', rpcId, method: 'hku-agents/admin/book', payload: {} }),
    JSON.stringify({ type: 'client-request', rpcId, method: 'hku-agents/admin/facilities', payload: { target: 'room' } }),
    'x'.repeat(2049),
  ]) assert.equal((await route.fetch(request(body))).status, 400)
  assert.equal(calls, 0)
})

test('Admin catalog refuses a response claiming a browser interaction or booking write', async () => {
  const unsafe = catalogEnvelope()
  unsafe.result.booking_writes_performed = 1
  const value = await readDesktopFacilities({ async listLibraryFacilities() { return unsafe } })
  assert.equal(value.ok, false)
  assert.equal(value.error.code, 'INVALID_CATALOG_RESPONSE')
  assert.equal(value.correlation_id, null)
})
