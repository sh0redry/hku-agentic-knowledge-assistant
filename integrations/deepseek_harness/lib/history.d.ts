export interface TestRecord {
    id: string;
    operation: string;
    recorded_at: string;
    plugin_version: string;
    outcome: string;
    task_id: string | null;
    correlation_id: string | null;
    error_code: string | null;
    verdict: string;
    diagnostics: Record<string, string | number | boolean>;
    domain_writes: string;
    host_runtime: string;
    core_version: null;
    extension_version: null;
}
export declare function safeDiagnostics(value: unknown): Record<string, string | number | boolean>;
export declare class TestHistory {
    private path;
    private queue;
    constructor(path?: string);
    private serial;
    private read;
    private save;
    list(): Promise<TestRecord[]>;
    append(operation: string, value: unknown): Promise<string>;
    review(recordId: string, verdict: string): Promise<void>;
}
export declare const testHistory: TestHistory;
interface Route {
    path: string;
    methods: string[];
    requestBody: 'buffered';
    fetch(request: Request): Promise<Response>;
}
export declare function recordRoute(route: Route, operation: string, history?: TestHistory): Route;
export declare function historyRoute(action: 'list' | 'review', history?: TestHistory): Route;
export {};
//# sourceMappingURL=history.d.ts.map