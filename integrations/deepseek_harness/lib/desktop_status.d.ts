import type { Context } from '@deepseek-ai/cordis';
import { type HKUAgentsClient, type JsonValue } from './client.js';
import { type LaunchResult } from './core_launcher.js';
export declare const DESKTOP_STATUS_PATH = "/api/hku-agents/status";
export declare const DESKTOP_CONNECT_PATH = "/api/hku-agents/connect";
export declare const DESKTOP_START_PATH = "/api/hku-agents/start";
interface ExactFetchRoute {
    path: string;
    methods: string[];
    requestBody: 'buffered';
    fetch(request: Request): Promise<Response>;
}
export declare function readDesktopStatus(client: Pick<HKUAgentsClient, 'status'>, signal?: AbortSignal): Promise<{
    correlation_id: string | null;
    binding?: {
        state: string | null;
        logged_in: boolean;
        page_kind: string | null;
        error_code: string | null;
    };
    read_only: boolean;
    core: {
        state: string;
        version: string | null;
        error_code?: never;
        recovery?: never;
    };
    connections: Record<string, JsonValue>[];
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
export declare function desktopStatusRoute(client: Pick<HKUAgentsClient, 'status'>, connect?: boolean): ExactFetchRoute;
export declare function desktopStartRoute(client: Pick<HKUAgentsClient, 'status'>, launcher: {
    ensureStarted(): Promise<LaunchResult>;
}): ExactFetchRoute;
export declare function installDesktopStatusBridge(ctx: Context, client: Pick<HKUAgentsClient, 'status' | 'connectHku'>, baseUrl?: string): void;
export {};
//# sourceMappingURL=desktop_status.d.ts.map