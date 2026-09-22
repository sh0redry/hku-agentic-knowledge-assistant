# Browser Bridge and Authentication

The Browser Bridge is a restricted Manifest V3 extension. It converts approved
HKU pages into structured snapshots and executes only named navigation recipes.
It is not a general-purpose browser automation layer.

## Supported systems

```text
studentportal.hku.hk
 ├─ SIS enrollment          → sis-main.hku.hk
 ├─ My Weekly Schedule      → sweb.hku.hk
 ├─ Moodle                  → moodle.hku.hk
 ├─ Find@HKUL               → julac-hku.primo.exlibrisgroup.com
 └─ Book a Space            → booking.lib.hku.hk

Public HKUL information     → lib.hku.hk
```

Portal is an entry point and identity session; it is not the downstream
application itself. A valid Portal login may allow a downstream SSO flow to
complete, but it does not prove that SIS, Moodle, or Library has already created
its own session.

## Connection lifecycle

```text
not_configured
      │ pairing token saved
      ▼
connecting ────────────────┐
      │ pair accepted      │ service/socket failure
      ▼                    │
paired ──────────────► reconnecting
      ▲                    │ bounded exponential retry
      └────────────────────┘

connecting/reconnecting ── invalid token ──► token_rejected
```

The extension sends periodic heartbeat messages containing sanitized tab state.
The backend tracks each approved system independently rather than treating one
active tab as the state of every system.

## Target registry

The registry reports only:

- approved system identity;
- sanitized HTTPS origin and path;
- detected authentication state when it can be established safely;
- page kind;
- parser version;
- heartbeat freshness;
- whether the target is active;
- `safe_for_writes: false`.

Query strings and fragments are removed because they may contain SSO tickets,
relay state, signed scopes, or other private values.

## Authentication behavior

The bridge may:

- follow an exact verified Portal service entry;
- activate a fixed SIS component route;
- choose a validated SIS term and Continue;
- activate Moodle's exact HKU Portal User SSO control;
- reuse existing authenticated downstream tabs;
- open fixed public Library routes.

The bridge may not:

- enter or retrieve usernames, passwords, PINs, recovery codes, or MFA responses;
- solve CAPTCHA;
- accept arbitrary selectors, coordinates, URLs, or scripts;
- export cookies, local storage, authentication headers, tickets, or private HTML;
- click enrollment, submission, payment, request, or booking controls.

An automatically completed Moodle SSO run means the extension activated the
allow-listed SSO entry and the browser's existing HKU identity session satisfied
the redirect. It does not mean HKU AGENTS knew or entered the user's credentials.

## Command lifecycle

```text
host tool
  → Integration API validates structured input
  → capability invokes one named browser command
  → background script selects or opens an approved target
  → origin-specific content script parses the page
  → Pydantic validates the returned snapshot
  → capability applies semantic/fail-closed checks
  → sanitized result is returned and audited
```

Pollers require stable page-state signatures before returning dynamic results.
Known login and error pages produce stable error codes instead of partial data.

## Important error codes

| Code | Meaning | Recovery |
|---|---|---|
| `BROWSER_NOT_CONNECTED` | No paired command channel is available | Start HKU AGENTS and inspect the popup retry state |
| `PAIRING_TOKEN_REJECTED` | Extension and backend tokens differ | Enter the configured pairing token again |
| `PAGE_SCRIPT_UNAVAILABLE` | The open tab lacks the current content script | Reload the extension and refresh the page |
| `BROWSER_TIMEOUT` | No command response arrived before the bridge deadline | Keep the verified page open and retry |
| `NAVIGATION_TIMEOUT` | The target page did not reach its verified ready state | Inspect the resulting tab and parser diagnostics |
| `PORTAL_LOGIN_REQUIRED` | Portal session is unavailable | Log into Portal manually |
| `SIS_LOGIN_REQUIRED` | SIS rejected or lost its session | Complete SIS authentication manually, then retry |
| `SSO_MANUAL_ACTION_REQUIRED` | A human authentication challenge remains | Complete the visible prompt yourself |
| `EXTENSION_UPDATE_REQUIRED` | Parser or command version is stale | Reload the extension and refresh the affected page |

## Updating content scripts

Reloading an unpacked extension does not inject the new content script into tabs
that were already open. After every extension upgrade, refresh each relevant
HKU tab. A stale page commonly produces `PAGE_SCRIPT_UNAVAILABLE` even though
the popup itself is paired.

## Why fixed routes are used

Fixed routes keep the effective authority of a model-visible tool small. A tool
can express intent such as “open Enrollment Add Classes for this term,” but it
cannot transform that intent into an arbitrary navigation or interaction. New
routes require an origin contract, page-kind detector, parser, typed protocol,
tests, and live acceptance.
