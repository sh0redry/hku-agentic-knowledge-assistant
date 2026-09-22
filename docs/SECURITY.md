# Security, Privacy, and Write Governance

HKU AGENTS handles authenticated academic pages, so its central design goal is
authority minimization: each capability receives only the access needed for one
bounded task.

## Trust boundaries

1. **Chrome** owns cookies, credentials, MFA state, and downstream sessions.
2. **Browser Bridge** owns fixed navigation and origin-specific parsing.
3. **Local backend** validates messages, runs policy, and stores sanitized audit data.
4. **GUI or Harness** sends structured intent through the bearer-protected localhost API.
5. **Model context** receives only the structured result allowed by the capability.

`INTEGRATION_API_TOKEN` protects boundary 4. `BROWSER_PAIRING_TOKEN` protects the
WebSocket between boundaries 2 and 3. They are deliberately separate.

## Data classification and lifetime

| Data | Immediate result | Process memory | SQLite history | Model must never receive |
|---|---:|---:|---:|---:|
| Sanitized counts/status/timestamps | yes | optional | yes | — |
| SIS course rows | yes | task lifetime | no | credentials/tickets |
| Weekly timetable meetings | yes | bounded cache | no | cookies/raw HTML |
| Moodle courses/deadlines | yes | bounded cache | no | grades/submissions unless a future explicit tool permits them |
| Portal notice cards | yes | bounded cache | no | authenticated detail HTML |
| Library result/item/availability rows | yes | task lifetime | no | proxy/SSO/full-text URLs |
| Password, PIN, MFA, CAPTCHA, cookie | no | no | no | always |

SQLite task records use each capability's `persisted_input` and
`persisted_result` projection. This is intentionally smaller than the live API
response. Process-memory caches disappear when HKU AGENTS stops.

## URL handling

- Browser targets must use approved HTTPS origins.
- Discovery status retains origin and path only.
- Query strings and fragments are stripped by default.
- The few returned Library detail URLs are reconstructed from allow-listed
  fields and reject unknown query parameters.
- Authentication, proxy, licensed-resource, relay-state, and ticket-bearing
  URLs are never returned.

## Read-only semantics

A read-only capability may still perform controlled navigation or SSO clicks.
Therefore results use separate fields such as:

```json
{
  "read_only": true,
  "navigation_interactions_performed": true,
  "sso_interactions_performed": true,
  "credentials_entered": false,
  "mfa_interactions_performed": false,
  "data_reads_performed": 1,
  "domain_writes_performed": 0
}
```

System-specific counters prevent ambiguous claims:

- `enrollment_writes_performed`
- `moodle_writes_performed`
- `portal_writes_performed`
- `library_writes_performed`
- `booking_writes_performed`

## Fail-closed parsing

Parsers expose count-only diagnostics for candidates, parsed rows, duplicates,
placeholders, and incomplete rows. Capabilities reject ambiguous partial output
when omission could change the answer. Verified empty states are distinct from
loading, unpublished, or inaccessible states.

Examples:

- an empty SIS cart is a valid observable state;
- Moodle returning zero visible deadline candidates includes a coverage warning;
- HKUL “opening hours not available yet” is not interpreted as `Closed`;
- duplicate responsive DOM copies are counted and deterministically collapsed;
- unsafe Library links are suppressed rather than returned partially.

## Extension permissions

The extension intentionally omits cookies, debugger, webRequest, downloads,
clipboard, broad scripting, and form-execution privileges. Host permissions are
limited to approved HKU origins and loopback communication.

## Write governance

Current HKU integrations expose no domain writes. A future write must be a
separate capability and satisfy all of the following:

1. exact structured target;
2. fresh read-only precondition check;
3. complete preview of the action and consequences;
4. explicit one-time user confirmation;
5. expiry of unused confirmation;
6. idempotency protection where feasible;
7. post-condition verification;
8. immutable sanitized audit event;
9. no generic click/script/URL escape hatch.

Enrollment, payment, application submission, identity or bank-account changes,
password/PIN handling, CAPTCHA, and MFA remain separately restricted even if
another reversible write is later enabled.

## Reporting security issues

Before sharing logs or screenshots, remove names, student identifiers, course
membership, assignment titles, tokens, complete URLs, and browser profile data.
Prefer correlation IDs, stable error codes, parser versions, and count-only
diagnostics when reporting a parser failure.
