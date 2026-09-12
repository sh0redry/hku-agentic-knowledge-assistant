# HKU AGENTS Multi-System Browser Bridge

This unpacked Manifest V3 extension discovers approved HKU Portal, SIS, Moodle,
and Library tabs and reports a sanitized per-system connection registry to the
local HKU AGENTS process. Existing Portal/SIS commands still use the compatible
single active binding. The extension can follow only two fixed navigation
targets: the Portal SIS sign-on entry and the exact SIS `Enrollment Add Classes`
component route. Moodle and Library support is discovery-only in Phase A: there
are no content scripts, parsers, navigation commands, or domain actions for
those systems. The extension never enters credentials, reads cookies, searches
courses, enters Step 2/3, or submits forms.

## Install for local development

1. Start HKU AGENTS with `python project/app.py`.
2. Open `chrome://extensions`, enable **Developer mode**, and choose **Load unpacked**.
3. Select this `browser_runtime/extension` directory.
4. In HKU AGENTS, open **Connections** and copy the current pairing token. For
   stable local development, set the same random value as `BROWSER_PAIRING_TOKEN`
   in the ignored `project/.env` file before starting the app.
5. Open the extension popup, paste the token once, and select **Save and connect**.
   The extension stores it in Chrome local extension storage and reconnects
   automatically after browser or HKU AGENTS restarts.
6. Log in to HKU Portal and complete MFA yourself. The authenticated modern
   Portal is served from `https://studentportal.hku.hk`; the legacy
   `https://hkuportal.hku.hk` redirect origin is also allowed.
7. Keep the authenticated Portal tab active and select **Bind active HKU tab**.
8. In the GUI or Harness, run **Open Enrollment Add Classes**. The extension
   activates the Portal's exact verified SIS entry so its SSO flow is preserved,
   binds only the newly opened verified SIS tab (or the bound tab if it navigates
   in place), opens the hard-coded Add Classes component route after SIS
   authentication, then verifies the cart page before returning.

When the unpacked extension receives a new ID, restart HKU AGENTS to clear the
in-memory development pin, or set `BROWSER_EXTENSION_IDS` explicitly in
`project/.env`.

## Multi-system diagnostics

The popup and the GUI **Connections** tab show one record for each supported
system: `portal`, `sis`, `moodle`, and `library`. Each record contains only an
approved origin, a path without query string or fragment, inferred
authentication/page state, parser version where available, and heartbeat
freshness. Complete authentication URLs, tickets, relay state, and tokens are
not sent to the local service.

Only Portal and SIS can be bound for existing commands. Opening Moodle or My
Library in Chrome makes them discoverable, but does not grant HKU AGENTS a read
or write capability for either page.

## Security contract

- Exact approved host permissions only: `https://studentportal.hku.hk/*`,
  `https://hkuportal.hku.hk/*`, `https://sis-main.hku.hk/*`,
  `https://moodle.hku.hk/*`, `https://julac-hku.primo.exlibrisgroup.com/*`, and
  `https://lib.hku.hk/*`.
- Local companion permission only: `http://127.0.0.1/*`.
- No `tabs`, cookies, downloads, clipboard, debugger, webRequest, or form-control permissions.
- Named commands only; arbitrary JavaScript, selectors, URLs, coordinates, and
  course values are rejected. A term must match an exact SIS term label.
- The Portal entry click is restricted to a uniquely resolved, allow-listed SIS
  sign-on destination; unrelated Portal controls cannot be clicked.
- Navigation stops when login is incomplete, the target is missing or ambiguous,
  an origin differs, or the verified destination does not become ready in time.
- Live preflight reads and compares the current cart but cannot modify it.
- Only structured page state leaves Portal/SIS content scripts. Full HTML is never sent.
- Moodle and Library have no content scripts in Phase A; tab discovery strips
  query strings and fragments before reporting state.
- Temporary Course List rows and Class Schedule rows are returned in separate fields.
- The SIS listener loads at `document_start` so legacy PeopleSoft frame pages can
  be observed even when their top-level document does not promptly become idle.
- Only an exact validated term exposed by the SIS Select Term page may be
  selected. Course search, delete, Step 2/3, and all enrollment writes remain absent.

## Connection lifecycle

- Retry delay uses bounded exponential backoff: 1, 2, 4, 8, 16, then 30 seconds.
- The popup distinguishes `not_configured`, `connecting`, `reconnecting`,
  `paired`, `portal_bound`, `sis_bound`, `token_rejected`,
  `extension_rejected`, and `bridge_disabled` states.
- **Reconnect now** resets the retry delay without changing the saved token.
- Rotating the server token immediately disconnects the current extension and
  rejects its old token. Revoking also clears the dynamically pinned extension ID.
- Runtime rotation does not edit `project/.env`; update that ignored file
  manually when the new token should survive the next app restart.
