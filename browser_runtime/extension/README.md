# HKU AGENTS SIS Bridge (read-only)

This unpacked Manifest V3 extension connects an already-open HKU SIS tab to the
local HKU AGENTS process. It never enters credentials, reads cookies, clicks SIS
controls, or submits forms.

## Install for local development

1. Start HKU AGENTS with `python project/app.py`.
2. Open `chrome://extensions`, enable **Developer mode**, and choose **Load unpacked**.
3. Select this `browser_runtime/extension` directory.
4. In HKU AGENTS, open **Connections** and copy the current pairing token.
5. Open the extension popup, paste the token, and select **Save and connect**.
6. Log in to HKU SIS yourself, then select **Bind open SIS tab**.
7. Open **Enrollment Add Classes** before inspecting the cart or running live preflight.

When the unpacked extension receives a new ID, restart HKU AGENTS to clear the
in-memory development pin, or set `BROWSER_EXTENSION_IDS` explicitly in
`project/.env`.

## Security contract

- Exact SIS host permission only: `https://sis-main.hku.hk/*`.
- Local companion permission only: `http://127.0.0.1/*`.
- No `tabs`, cookies, downloads, clipboard, debugger, webRequest, or form-control permissions.
- Named read-only commands only; arbitrary JavaScript and arbitrary selectors are rejected.
- Live preflight reads and compares the current cart but cannot modify it.
- Only structured page state leaves the content script. Full HTML is never sent.
- Real SIS POSTs and enrollment actions are outside this version.
