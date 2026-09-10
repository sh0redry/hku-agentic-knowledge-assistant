export type JsonValue = null | boolean | number | string | JsonValue[] | {
    [key: string]: JsonValue;
};
export interface IntegrationError {
    [key: string]: JsonValue;
    code: string;
    message: string;
    recovery?: string | null;
    details?: Array<{
        [key: string]: JsonValue;
    }> | null;
}
export interface IntegrationTaskSummary {
    [key: string]: JsonValue;
    id: string;
    capability: string;
    status: string;
    phase: string;
    correlation_id: string;
    error?: {
        [key: string]: JsonValue;
    } | null;
}
export interface IntegrationEnvelope {
    [key: string]: JsonValue;
    api_version: 'v1';
    ok: boolean;
    read_only: true;
    correlation_id: string;
    result: {
        [key: string]: JsonValue;
    } | null;
    task: IntegrationTaskSummary | null;
    error: IntegrationError | null;
}
export interface HKUAgentsClientOptions {
    baseUrl: string;
    tokenEnv: string;
    timeoutMs: number;
    maxResponseBytes?: number;
}
export declare class HKUAgentsAPIError extends Error {
    readonly code: string;
    readonly status: number | null;
    readonly recovery: string | null;
    constructor(code: string, message: string, options?: {
        status?: number | null;
        recovery?: string | null;
        cause?: unknown;
    });
}
export declare class HKUAgentsClient {
    readonly baseUrl: string;
    readonly tokenEnv: string;
    readonly timeoutMs: number;
    readonly maxResponseBytes: number;
    constructor(options: HKUAgentsClientOptions);
    status(signal?: AbortSignal): Promise<IntegrationEnvelope>;
    syncCourseLists(signal?: AbortSignal): Promise<IntegrationEnvelope>;
    preflight(input: {
        term_label: string;
        expected_courses: Array<{
            course_code: string;
            section: string;
        }>;
    }, signal?: AbortSignal): Promise<IntegrationEnvelope>;
    private request;
}
//# sourceMappingURL=client.d.ts.map