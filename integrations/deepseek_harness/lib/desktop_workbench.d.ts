import type { Context } from '@deepseek-ai/cordis';
import { type HKUAgentsClient } from './client.js';
import { type TestHistory } from './history.js';
export declare const RELEASE = "0.19.2";
export declare const REQUIRED_EXTENSION = "0.17.25";
type Client = Pick<HKUAgentsClient, 'status' | 'listLibraryFacilities' | 'libraryOperator'>;
type Route = {
    path: string;
    methods: string[];
    requestBody: 'buffered';
    fetch(request: Request): Promise<Response>;
};
export declare function compatibleExtension(value: unknown): boolean | null;
export declare function localChecks(client: Client, signal?: AbortSignal): Promise<{
    ok: boolean;
    local_only: boolean;
    browser_interactions_performed: boolean;
    domain_writes_performed: number;
    plugin_version: string;
    host_runtime: string;
    observed_at: string;
    checks: Record<string, unknown>[];
    live_acceptance: string;
    connection: {
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
        connections: Record<string, import("./client.js").JsonValue>[];
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
    };
}>;
export declare function taskRow(value: unknown, kind: string, ruleContext?: unknown): {
    kind: string;
    id: string;
    rule_id: string | null;
    state: string | null;
    phase: string | null;
    error_code: string | null;
    next_run_at: string | null;
    scheduled_at: string | null;
    scheduled_time_basis: string;
    started_at: string | null;
    prepare_at: string | null;
    stop_at: string | null;
    date_check_count: number | null;
    completed_at: string | null;
    armed: boolean | null;
    dry_run: boolean | null;
    attempt_count: number | null;
    success_count: number | null;
    read_only: boolean | null;
    run_count: number | null;
    max_runs: number | null;
    booking_writes_performed: string | number | null;
    target: {
        date: string | null;
        facility_type: string | null;
        room: string | null;
        start_time: string | null;
        end_time: string | null;
        preference_summary_only: boolean;
        suggested_candidate_verified: boolean;
    };
} | null;
export declare function taskSnapshot(client: Client, signal?: AbortSignal): Promise<{
    ok: boolean;
    read_only: boolean;
    observed_at: string;
    groups: ({
        kind: string | undefined;
        ok: boolean;
        rows: {
            kind: string;
            id: string;
            rule_id: string | null;
            state: string | null;
            phase: string | null;
            error_code: string | null;
            next_run_at: string | null;
            scheduled_at: string | null;
            scheduled_time_basis: string;
            started_at: string | null;
            prepare_at: string | null;
            stop_at: string | null;
            date_check_count: number | null;
            completed_at: string | null;
            armed: boolean | null;
            dry_run: boolean | null;
            attempt_count: number | null;
            success_count: number | null;
            read_only: boolean | null;
            run_count: number | null;
            max_runs: number | null;
            booking_writes_performed: string | number | null;
            target: {
                date: string | null;
                facility_type: string | null;
                room: string | null;
                start_time: string | null;
                end_time: string | null;
                preference_summary_only: boolean;
                suggested_candidate_verified: boolean;
            };
        }[];
        returned_count: number;
        bounded_snapshot: boolean;
        error_code?: never;
    } | {
        kind: string | undefined;
        ok: boolean;
        rows: never[];
        error_code: string;
        returned_count?: never;
        bounded_snapshot?: never;
    })[];
    scope: string;
    changes_performed: boolean;
}>;
export declare function acceptanceReport(client: Client, history: Pick<TestHistory, 'list'>, signal?: AbortSignal): Promise<{
    schema_version: number;
    generated_at: string;
    plugin_version: string;
    local_only: boolean;
    browser_interactions_performed: boolean;
    domain_writes_performed: number;
    checks: Record<string, unknown>[];
    history_error: string | null;
    records: Record<string, unknown>[];
    review_totals: {
        [k: string]: number;
    };
    limitations: string[];
}>;
export declare function workbenchRoute(action: 'checks' | 'tasks' | 'report', client: Client, history?: Pick<TestHistory, 'list'>): Route;
export declare function installDesktopWorkbench(ctx: Context, client: Client): void;
export {};
//# sourceMappingURL=desktop_workbench.d.ts.map