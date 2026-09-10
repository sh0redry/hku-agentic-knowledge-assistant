# HKU AGENTS for DeepSeek Harness

This package contributes three read-only HKU SIS tools to DeepSeek Harness:

- `hku_sis_status`
- `hku_sis_sync_course_lists`
- `hku_sis_preflight`

It is a thin adapter over the authenticated HKU AGENTS Integration API. It does
not parse SIS HTML, hold browser cookies, navigate Portal, or perform SIS writes.
The local HKU AGENTS app and Chrome extension must be running separately.

## Prerequisites

1. Use Node.js `^22.19.0` or `>=24.0.0`, matching the current Harness runtime.
2. On Windows, enable Developer Mode or run Harness from an elevated terminal.
   Harness uses directory symbolic links while composing profiles; without that
   Windows privilege the CLI can report `EISDIR` before any plugin is loaded.
3. Start HKU AGENTS at `http://127.0.0.1:7860`.
4. In the HKU AGENTS GUI, open **Connections** and copy the Integration API token.
   This is not the browser-extension pairing token.
5. Export the same token in the environment that starts DeepSeek Harness:

   ```powershell
   $env:INTEGRATION_API_TOKEN = "paste-the-local-token-here"
   ```

   Optionally set `HKU_AGENTS_API_BASE_URL` when the local app uses a different
   loopback port. Remote API origins are intentionally rejected.

## Local build and test

```powershell
cd integrations/deepseek_harness
npm install
npm test
```

## Install into a Harness profile

From the repository root, with the `dsh` CLI installed:

```powershell
cd integrations/deepseek_harness
npm run build
npm pack
dsh plugin --profile web add ./dsh-hku-agents-0.1.0.tgz
dsh --profile web --dump-config
dsh --profile web
```

Packing avoids a development-time link from the profile to this source tree.
For a DeepSeek Harness source checkout, use the equivalent `pnpm dsh` commands.
The package declares a `dsh.bundle` whose `cordis.patch.yml` mounts the plugin.

## Configuration

The bundle defaults are:

```yaml
baseUrl: http://127.0.0.1:7860
tokenEnv: INTEGRATION_API_TOKEN
timeoutMs: 15000
```

Override the complete `hku-agents` row in the profile or home
`cordis.patch.yml` when needed. Store only the environment-variable name in
Cordis configuration; do not put the token value in YAML.

## Safety boundary

- Only HTTP(S) loopback hosts (`127.0.0.1`, `localhost`, or `::1`) are accepted.
- Redirects are rejected so the bearer token cannot cross origins.
- Responses are size-limited and must match Integration API v1.
- Harness cancellation is forwarded to the local HTTP request.
- The tool set contains no click, form-fill, add, drop, enroll, or submit command.
