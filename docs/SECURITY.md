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

`library.spaces.booking_preview` also remains read-only. Its digest proves only
which freshly observed slot and policy data were shown; it records no policy
acceptance, grants no write authority, selects no slot, and cannot be submitted
to the booking system.

`library.spaces.search_availability` may change the Location, Facility Type,
and Date filters and press the non-writing `Search` control. These are reported
as navigation interactions, not booking writes. A separate F2 command can
select one exact green `Select` cell and prepare the matching session checkbox;
only the local GUI's one-time confirmation can authorize one `Submit`, and only
when `LIBRARY_BOOKING_WRITES_ENABLED=true`. It is limited to Main Library single
study rooms and never provides arbitrary selectors, URLs, scripts, or form
execution. It verifies one matching My Booking Record row and has no automated
cancellation command. Ambiguous post-submit results are terminal and must not
be retried.

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
clipboard, and the general-purpose scripting API. It uses fixed content-script
handlers for approved pages; F2's single form action is named, locally gated,
and structurally tied to one confirmed booking target. Host permissions are
limited to approved HKU origins and loopback communication.

## Write governance

All integrations other than the optional F2 reservation remain read-only. The
`library.spaces.book` F2 capability is high-risk, local-GUI-only, and disabled
by default; it is additionally unavailable unless `APP_HOST` is loopback
(`localhost`, `127.0.0.0/8`, or `::1`). It accepts only a fresh process-issued preview digest and requires
the platform's one-time two-phase confirmation. Its exact target is redacted
from persistent action-draft storage. Before Submit, it refreshes availability
and verifies the complete booking form; a persistent one-shot execution ID is
armed before the exact Submit click, and the result must appear exactly once in
My Booking Record. This bounded path satisfies:

1. exact structured target;
2. fresh read-only precondition check;
3. complete preview of the action and consequences;
4. explicit one-time user confirmation;
5. expiry of unused confirmation;
6. idempotency protection where feasible;
7. post-condition verification;
8. sanitized audit event;
9. no generic click/script/URL escape hatch;
10. fail-closed handling of uncertain outcomes, with no automatic retry.

Enrollment, payment, application submission, identity or bank-account changes,
password/PIN handling, CAPTCHA, and MFA remain separately restricted even if
another reversible write is later enabled.

## Reporting security issues

Before sharing logs or screenshots, remove names, student identifiers, course
membership, assignment titles, tokens, complete URLs, and browser profile data.
Prefer correlation IDs, stable error codes, parser versions, and count-only
diagnostics when reporting a parser failure.
