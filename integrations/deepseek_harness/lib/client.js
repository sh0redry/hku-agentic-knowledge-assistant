import { randomUUID } from 'node:crypto';
export class HKUAgentsAPIError extends Error {
    code;
    status;
    recovery;
    constructor(code, message, options = {}) {
        super(message, options.cause === undefined ? undefined : { cause: options.cause });
        this.name = 'HKUAgentsAPIError';
        this.code = code;
        this.status = options.status ?? null;
        this.recovery = options.recovery ?? null;
    }
}
function normalizedLoopbackBaseUrl(value) {
    let parsed;
    try {
        parsed = new URL(value);
    }
    catch (error) {
        throw new HKUAgentsAPIError('INVALID_BASE_URL', 'HKU AGENTS baseUrl is not a valid URL.', {
            cause: error,
        });
    }
    const loopbackHosts = new Set(['127.0.0.1', 'localhost', '[::1]']);
    if (!['http:', 'https:'].includes(parsed.protocol) || !loopbackHosts.has(parsed.hostname)) {
        throw new HKUAgentsAPIError('NON_LOOPBACK_BASE_URL', 'HKU AGENTS must use an HTTP(S) loopback URL; remote targets are rejected.');
    }
    if (parsed.username || parsed.password || parsed.search || parsed.hash) {
        throw new HKUAgentsAPIError('INVALID_BASE_URL', 'HKU AGENTS baseUrl must not contain credentials, query parameters, or fragments.');
    }
    if (parsed.pathname !== '/' && parsed.pathname !== '') {
        throw new HKUAgentsAPIError('INVALID_BASE_URL', 'HKU AGENTS baseUrl must not contain a path.');
    }
    return parsed.origin;
}
function isEnvelope(value) {
    if (typeof value !== 'object' || value === null || Array.isArray(value))
        return false;
    const candidate = value;
    return (candidate.api_version === 'v1' &&
        typeof candidate.ok === 'boolean' &&
        candidate.read_only === true &&
        typeof candidate.correlation_id === 'string' &&
        Object.hasOwn(candidate, 'result') &&
        Object.hasOwn(candidate, 'task') &&
        Object.hasOwn(candidate, 'error'));
}
function combinedSignal(parent, timeoutMs) {
    const controller = new AbortController();
    let didTimeout = false;
    const abortFromParent = () => controller.abort(parent?.reason);
    if (parent?.aborted)
        abortFromParent();
    else
        parent?.addEventListener('abort', abortFromParent, { once: true });
    const timer = setTimeout(() => {
        didTimeout = true;
        controller.abort(new Error('HKU AGENTS request timed out.'));
    }, timeoutMs);
    timer.unref?.();
    return {
        signal: controller.signal,
        timedOut: () => didTimeout,
        dispose: () => {
            clearTimeout(timer);
            parent?.removeEventListener('abort', abortFromParent);
        },
    };
}
export class HKUAgentsClient {
    baseUrl;
    tokenEnv;
    timeoutMs;
    maxResponseBytes;
    constructor(options) {
        this.baseUrl = normalizedLoopbackBaseUrl(options.baseUrl);
        if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(options.tokenEnv)) {
            throw new HKUAgentsAPIError('INVALID_TOKEN_ENV', 'tokenEnv must be an uppercase environment-variable name.');
        }
        if (!Number.isInteger(options.timeoutMs) || options.timeoutMs < 1000 || options.timeoutMs > 120000) {
            throw new HKUAgentsAPIError('INVALID_TIMEOUT', 'timeoutMs must be an integer between 1000 and 120000.');
        }
        this.tokenEnv = options.tokenEnv;
        this.timeoutMs = options.timeoutMs;
        this.maxResponseBytes = options.maxResponseBytes ?? 512 * 1024;
    }
    status(signal) {
        return this.request('GET', '/api/v1/integration/status', undefined, signal);
    }
    syncCourseLists(signal) {
        return this.request('POST', '/api/v1/integration/sis/sync', undefined, signal);
    }
    navigateToEnrollmentAddClasses(input, signal) {
        return this.request('POST', '/api/v1/integration/sis/navigate', input, signal);
    }
    preflight(input, signal) {
        return this.request('POST', '/api/v1/integration/sis/preflight', input, signal);
    }
    async request(method, path, body, parentSignal) {
        const token = process.env[this.tokenEnv]?.trim();
        if (!token || token.length < 32) {
            throw new HKUAgentsAPIError('TOKEN_NOT_CONFIGURED', `${this.tokenEnv} must contain the current local HKU AGENTS Integration API token.`);
        }
        const requestUrl = new URL(path, `${this.baseUrl}/`);
        if (requestUrl.origin !== this.baseUrl) {
            throw new HKUAgentsAPIError('ORIGIN_MISMATCH', 'The Integration API request left loopback.');
        }
        const cancellation = combinedSignal(parentSignal, this.timeoutMs);
        try {
            const response = await fetch(requestUrl, {
                method,
                redirect: 'error',
                signal: cancellation.signal,
                headers: {
                    Accept: 'application/json',
                    Authorization: `Bearer ${token}`,
                    'Content-Type': 'application/json',
                    'X-Correlation-ID': randomUUID(),
                },
                ...(body === undefined ? {} : { body: JSON.stringify(body) }),
            });
            const declaredLength = Number(response.headers.get('content-length') ?? '0');
            if (Number.isFinite(declaredLength) && declaredLength > this.maxResponseBytes) {
                throw new HKUAgentsAPIError('RESPONSE_TOO_LARGE', 'HKU AGENTS response exceeded the size limit.', {
                    status: response.status,
                });
            }
            const text = await response.text();
            if (Buffer.byteLength(text, 'utf8') > this.maxResponseBytes) {
                throw new HKUAgentsAPIError('RESPONSE_TOO_LARGE', 'HKU AGENTS response exceeded the size limit.', {
                    status: response.status,
                });
            }
            let value;
            try {
                value = JSON.parse(text);
            }
            catch (error) {
                throw new HKUAgentsAPIError('INVALID_RESPONSE', 'HKU AGENTS returned invalid JSON.', {
                    status: response.status,
                    cause: error,
                });
            }
            if (!isEnvelope(value)) {
                throw new HKUAgentsAPIError('INVALID_RESPONSE', 'HKU AGENTS returned an incompatible Integration API envelope.', { status: response.status });
            }
            if (!response.ok || !value.ok) {
                throw new HKUAgentsAPIError(value.error?.code ?? `HTTP_${response.status}`, value.error?.message ?? 'HKU AGENTS request failed.', { status: response.status, recovery: value.error?.recovery ?? null });
            }
            return value;
        }
        catch (error) {
            if (error instanceof HKUAgentsAPIError)
                throw error;
            if (cancellation.timedOut()) {
                throw new HKUAgentsAPIError('API_TIMEOUT', 'The local HKU AGENTS request timed out.', {
                    cause: error,
                });
            }
            if (parentSignal?.aborted) {
                throw new HKUAgentsAPIError('CANCELLED', 'The HKU AGENTS tool call was cancelled.', {
                    cause: error,
                });
            }
            throw new HKUAgentsAPIError('API_UNAVAILABLE', 'Cannot reach the local HKU AGENTS API. Start the local app and try again.', { cause: error });
        }
        finally {
            cancellation.dispose();
        }
    }
}
//# sourceMappingURL=client.js.map