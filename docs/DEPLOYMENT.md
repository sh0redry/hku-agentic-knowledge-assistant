# Deployment and Upgrade Guide

This guide covers local Windows development, Browser Bridge pairing, DeepSeek
Harness installation, and version upgrades. HKU AGENTS is designed to bind only
to loopback services; do not expose port `7860` publicly.

## Prerequisites

- Python 3.11 or newer
- Google Chrome or another Chromium browser that supports unpacked Manifest V3 extensions
- Node.js `^22.19.0` or `>=24.0.0` for the Harness adapter
- `pnpm` for the DeepSeek `dsh` CLI
- an HKU account and permission to use the connected HKU services
- Windows Developer Mode or an elevated terminal if Harness profile symlink creation fails

## First installation

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item project\.env.example project\.env
```

Generate two different random secrets. Each must contain at least 32 characters:

```powershell
$integration = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$pairing = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

Place them in `project/.env`:

```dotenv
INTEGRATION_API_TOKEN=first-random-value
BROWSER_PAIRING_TOKEN=second-random-value
```

These tokens serve different trust boundaries:

| Token | Used by | Purpose | Storage |
|---|---|---|---|
| `INTEGRATION_API_TOKEN` | GUI API client and Harness | Authorizes localhost Integration API calls | ignored `.env` and host-process environment |
| `BROWSER_PAIRING_TOKEN` | Browser Bridge extension | Pairs the extension WebSocket with the local service | ignored `.env` and Chrome extension local storage |

Never put either token in source control, screenshots, prompts, logs, or issue reports.

## Model configuration

The deterministic HKU tools can start without an LLM key. The knowledge assistant
requires the configured provider:

```dotenv
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=your-key
```

Gemini can be enabled as a fallback with `GEMINI_API_KEY`. Ollama remains an
optional local provider; see `project/.env.example`.

## Start the local application

```powershell
.\.venv\Scripts\Activate.ps1
python project\app.py
```

Expected surfaces:

- `http://127.0.0.1:7860` — Gradio workbench
- `http://127.0.0.1:7860/docs` — FastAPI documentation
- `http://127.0.0.1:7860/api/v1/health` — application health
- `http://127.0.0.1:7860/api/v1/capabilities` — runtime capability inventory

## Install the Browser Bridge

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Choose `browser_runtime/extension`.
5. Confirm the displayed version matches the root README.
6. Open the extension popup and enter `BROWSER_PAIRING_TOKEN`.
7. Keep the bridge port at `7860` unless `APP_PORT` was deliberately changed.

Log into HKU Portal and complete password, MFA, CAPTCHA, consent, and recovery
steps manually. HKU AGENTS may use verified fixed SSO controls after login, but
it never enters or reads authentication factors.

## Install DeepSeek Harness support

```powershell
npm install --global pnpm@11.7.0
cd integrations\deepseek_harness
npm install
npm test
npm pack
$env:INTEGRATION_API_TOKEN = "the-integration-token"
npx.cmd --yes @deepseek-ai/dsh@0.1.2-rc.1 plugin --profile web add .\dsh-hku-agents-0.16.1.tgz
npx.cmd --yes @deepseek-ai/dsh@0.1.2-rc.1 --profile web --dump-config
npx.cmd --yes @deepseek-ai/dsh@0.1.2-rc.1 --profile web
```

`INTEGRATION_API_TOKEN` belongs in the Harness process. Do not put the browser
pairing token there.

## Upgrade procedure

Use this sequence whenever browser code, parser contracts, or Harness tools change:

1. Stop HKU AGENTS and Harness.
2. Update the repository without deleting `project/.env` or unrelated local data.
3. Run the automated tests.
4. Open `chrome://extensions` and reload the unpacked Browser Bridge.
5. Confirm its new version.
6. Refresh already-open Portal, SIS, Moodle, timetable, and Library pages so the
   new content scripts are installed.
7. Restart HKU AGENTS.
8. Check the extension popup for `paired`.
9. Rebuild and pack the Harness adapter.
10. Install the newly generated `.tgz`; an old archive is not updated in place.
11. Use `--dump-config` to confirm the installed package and tool registration.
12. Perform the relevant live acceptance check and inspect parser versions and
    zero-write counters.

## Token rotation and recovery

If `BROWSER_PAIRING_TOKEN` changes while the extension retains the old value,
the popup reports `token_rejected`. Enter the new value or use the GUI pairing
controls. If the service is stopped, the extension reports `reconnecting` and
continues with bounded backoff.

If `INTEGRATION_API_TOKEN` changes, restart Harness with the new environment
variable. An HTTP `401` normally means the host token is missing or incorrect;
it does not indicate a browser-pairing failure.

## Uninstallation

- Remove the unpacked extension from `chrome://extensions`.
- Remove the Harness plugin from its profile using the matching `dsh plugin` command.
- Delete `project/.env` only if you intend to discard local secrets.
- The default SQLite database is `hku_agents.db`; remove it only when its local
  task/audit history is no longer required.
