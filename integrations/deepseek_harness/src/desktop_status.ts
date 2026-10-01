import type { Context } from '@deepseek-ai/cordis'

import { HKUAgentsAPIError, type HKUAgentsClient, type JsonValue } from './client.js'

export const DESKTOP_STATUS_PATH = '/api/hku-agents/status'
export const DESKTOP_CONNECT_PATH = '/api/hku-agents/connect'

interface ExactFetchRoute {
  path: string
  methods: string[]
  requestBody: 'buffered'
  fetch(request: Request): Promise<Response>
}

interface HostConnection {
  fetch: { register(route: ExactFetchRoute): () => void }
}

interface RpcRequest {
  type: 'client-request'
  rpcId: string
  method: 'hku-agents/status' | 'hku-agents/connect'
  payload: Record<string, never>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseRequest(text: string, method = 'hku-agents/status'): RpcRequest | null {
  if (Buffer.byteLength(text, 'utf8') > 2048) return null
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return null
  }
  if (!isRecord(value) || value.type !== 'client-request' || value.method !== method) return null
  if (Object.keys(value).sort().join(',') !== 'method,payload,rpcId,type') return null
  if (typeof value.rpcId !== 'string' || !/^[0-9a-f-]{36}$/i.test(value.rpcId)) return null
  if (!isRecord(value.payload) || Object.keys(value.payload).length !== 0) return null
  return value as unknown as RpcRequest
}

function narrowString(value: unknown, limit = 64): string | null {
  return typeof value === 'string' && value.length <= limit ? value : null
}

function narrowConnection(value: unknown): Record<string, JsonValue> | null {
  if (!isRecord(value)) return null
  const id = narrowString(value.id)
  const status = narrowString(value.status)
  if (id === null || status === null) return null
  return {
    id,
    status,
    lifecycle_state: narrowString(value.lifecycle_state),
    mode: narrowString(value.mode),
    extension_version: narrowString(value.extension_version),
  }
}

export async function readDesktopStatus(client: Pick<HKUAgentsClient, 'status'>, signal?: AbortSignal) {
  try {
    const envelope = await client.status(signal)
    const result = envelope.result
    if (!isRecord(result)) throw new Error('Core status response had no result.')
    const connections = Array.isArray(result.connections)
      ? result.connections.map(narrowConnection).filter((item): item is Record<string, JsonValue> => item !== null)
      : []
    return {
      read_only: true,
      core: { state: 'connected', version: narrowString(result.service_version) },
      connections,
      ...(isRecord(result.binding) ? { binding: {
        state: narrowString(result.binding.state),
        logged_in: result.binding.logged_in === true,
        page_kind: narrowString(result.binding.page_kind),
        error_code: narrowString(result.binding.error_code),
      } } : {}),
      correlation_id: narrowString(envelope.correlation_id),
    }
  } catch (error) {
    const rawCode = error instanceof HKUAgentsAPIError ? error.code : 'INVALID_STATUS_RESPONSE'
    const code = /^[A-Z][A-Z0-9_]{0,63}$/.test(rawCode) ? rawCode : 'CORE_STATUS_FAILED'
    const recovery = code === 'TOKEN_NOT_CONFIGURED'
      ? 'Restart the updated HKU AGENTS service once to initialize automatic local connection.'
      : code === 'LOCAL_CONNECTION_UNAVAILABLE'
        ? 'Restart HKU AGENTS under the same Windows account as Desktop.'
      : code === 'API_UNAVAILABLE'
        ? 'Start the local HKU AGENTS service, then refresh this panel.'
        : 'Check the HKU AGENTS local service and refresh this panel.'
    return {
      read_only: true,
      core: { state: 'unavailable', error_code: code, recovery },
      connections: [],
      correlation_id: null,
    }
  }
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  })
}

export function desktopStatusRoute(client: Pick<HKUAgentsClient, 'status'>, connect = false): ExactFetchRoute {
  return {
    path: connect ? DESKTOP_CONNECT_PATH : DESKTOP_STATUS_PATH,
    methods: ['POST'],
    requestBody: 'buffered',
    async fetch(request) {
      if (request.method !== 'POST') return jsonResponse({ error: 'method_not_allowed' }, 405)
      const declaredLength = Number(request.headers.get('content-length') ?? '0')
      if (Number.isFinite(declaredLength) && declaredLength > 2048) {
        return jsonResponse({ error: 'invalid_request' }, 400)
      }
      const parsed = parseRequest(await request.text(), connect ? 'hku-agents/connect' : 'hku-agents/status')
      if (parsed === null) return jsonResponse({ error: 'invalid_request' }, 400)
      const status = await readDesktopStatus(client, request.signal)
      return jsonResponse({
        type: 'server-response',
        rpcId: parsed.rpcId,
        result: { ok: true, value: status },
      })
    },
  }
}

export function installDesktopStatusBridge(ctx: Context, client: Pick<HKUAgentsClient, 'status' | 'connectHku'>): void {
  ctx.inject(['connection'], connectionContext => {
    const connection = (connectionContext as Context & { connection: HostConnection }).connection
    const disposeStatus = connection.fetch.register(desktopStatusRoute(client))
    const disposeConnect = connection.fetch.register(desktopStatusRoute({ status: signal => client.connectHku(signal) }, true))
    return () => { disposeConnect(); disposeStatus() }
  })
}
