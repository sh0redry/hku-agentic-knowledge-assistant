import type { Context } from '@deepseek-ai/cordis';
import { type HKUAgentsClient } from './client.js';
export declare const DESKTOP_SIS_SYNC_PATH = "/api/hku-agents/admin/sis/sync";
export declare const DESKTOP_SIS_PREFLIGHT_PATH = "/api/hku-agents/admin/sis/preflight";
interface ExactFetchRoute {
    path: string;
    methods: string[];
    requestBody: 'buffered';
    fetch(request: Request): Promise<Response>;
}
type SISClient = Pick<HKUAgentsClient, 'syncCourseLists' | 'preflight'>;
type ExpectedCourse = {
    course_code: string;
    section: string;
};
export declare function readDesktopSISSync(client: Pick<SISClient, 'syncCourseLists'>, signal?: AbortSignal): Promise<{
    ok: boolean;
    read_only: boolean;
    error: {
        code: string;
        recovery: string;
    };
    correlation_id: null;
} | {
    ok: boolean;
    read_only: boolean;
    sis_write_requests_sent: number;
    term_label: string | null;
    temporary_course_count: number;
    schedule_course_count: number;
    temporary_courses: ({
        course_code: string;
        section: string;
        class_number: string;
    } | {
        course_code: string;
        section: string;
        class_number?: never;
    } | null)[];
    schedule_courses: ({
        course_code: string;
        section: string;
        class_number: string;
    } | {
        course_code: string;
        section: string;
        class_number?: never;
    } | null)[];
    diagnostics: {
        parser_version: string | null;
        temporary_candidate_count: number | null;
        schedule_candidate_count: number | null;
        unclassified_candidate_count: number;
    };
    correlation_id: string | null;
}>;
export declare function readDesktopSISPreflight(client: Pick<SISClient, 'preflight'>, input: {
    term_label: string;
    expected_courses: ExpectedCourse[];
}, signal?: AbortSignal): Promise<{
    ok: boolean;
    read_only: boolean;
    error: {
        code: string;
        recovery: string;
    };
    correlation_id: null;
} | {
    ok: boolean;
    read_only: boolean;
    sis_write_requests_sent: number;
    ready: boolean;
    term_match: boolean;
    requested_term_label: string;
    observed_term_label: string | null;
    matched_courses: ({
        course_code: string;
        section: string;
        class_number: string;
    } | {
        course_code: string;
        section: string;
        class_number?: never;
    } | null)[];
    missing_courses: ({
        course_code: string;
        section: string;
        class_number: string;
    } | {
        course_code: string;
        section: string;
        class_number?: never;
    } | null)[];
    unexpected_courses: ({
        course_code: string;
        section: string;
        class_number: string;
    } | {
        course_code: string;
        section: string;
        class_number?: never;
    } | null)[];
    issues: import("./client.js").JsonValue[];
    task_id: string | null;
    correlation_id: string | null;
}>;
export declare function desktopSISSyncRoute(client: Pick<SISClient, 'syncCourseLists'>): ExactFetchRoute;
export declare function desktopSISPreflightRoute(client: Pick<SISClient, 'preflight'>): ExactFetchRoute;
export declare function installDesktopSISBridge(ctx: Context, client: SISClient): void;
export {};
//# sourceMappingURL=desktop_sis.d.ts.map