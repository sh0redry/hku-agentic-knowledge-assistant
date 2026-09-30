import type { Context } from '@deepseek-ai/cordis';
import { type HKUAgentsClient, type JsonValue } from './client.js';
export declare const DESKTOP_STATUS_PATH = "/api/hku-agents/status";
interface ExactFetchRoute {
    path: string;
    methods: string[];
    requestBody: 'buffered';
    fetch(request: Request): Promise<Response>;
}
export declare function readDesktopStatus(client: Pick<HKUAgentsClient, 'status'>, signal?: AbortSignal): Promise<{
    read_only: boolean;
    core: {
        state: string;
        version: string | null;
        error_code?: never;
        recovery?: never;
    };
    connections: Record<string, JsonValue>[];
    correlation_id: string | null;
} | {
    read_only: boolean;
    core: {
        state: string;
        error_code: string;
        recovery: string;
        version?: never;
    };
    connections: never[];
    correlation_id: null;
}>;
export declare function desktopStatusRoute(client: Pick<HKUAgentsClient, 'status'>): ExactFetchRoute;
export declare function installDesktopStatusBridge(ctx: Context, client: Pick<HKUAgentsClient, 'status'>): void;
export {};
//# sourceMappingURL=desktop_status.d.ts.map