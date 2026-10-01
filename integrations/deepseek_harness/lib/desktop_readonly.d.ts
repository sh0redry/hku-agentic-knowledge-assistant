import type { Context } from '@deepseek-ai/cordis';
import { type HKUAgentsClient } from './client.js';
export declare const ADMIN_READ_OPERATIONS: readonly ["timetable_sync", "next_class", "moodle_dashboard", "moodle_courses", "moodle_assignments", "portal_notices", "briefing", "library_hours", "library_dates", "library_availability", "library_research"];
export type AdminReadOperation = typeof ADMIN_READ_OPERATIONS[number];
type ReadClient = Pick<HKUAgentsClient, 'syncWeeklyTimetable' | 'nextClass' | 'inspectMoodleDashboard' | 'listMoodleCourses' | 'listUpcomingMoodleAssignments' | 'listPortalNotices' | 'dailyBriefing' | 'libraryHoursAndLocations' | 'listLibrarySpaceDates' | 'searchLibrarySpaceAvailability' | 'searchLibraryResearch'>;
interface ExactFetchRoute {
    path: string;
    methods: string[];
    requestBody: 'buffered';
    fetch(request: Request): Promise<Response>;
}
export declare function readDesktopOperation(client: ReadClient, operation: AdminReadOperation, payload: Record<string, unknown>, signal: AbortSignal): Promise<{
    ok: boolean;
    read_only: boolean;
    task_id: string | null;
    diagnostics: Record<string, string | number | boolean>;
    error: {
        code: string;
        recovery: string;
    };
    correlation_id: string | null;
} | {
    ok: boolean;
    read_only: boolean;
    domain_writes_performed: number;
    operation: "timetable_sync" | "next_class" | "moodle_dashboard" | "moodle_courses" | "moodle_assignments" | "portal_notices" | "briefing" | "library_hours" | "library_dates" | "library_availability" | "library_research";
    summary: Record<string, unknown>;
    diagnostics: Record<string, string | number | boolean>;
    task_id: string | null;
    correlation_id: string | null;
}>;
export declare function desktopReadRoute(client: ReadClient, operation: AdminReadOperation): ExactFetchRoute;
export declare function installDesktopReadBridge(ctx: Context, client: ReadClient): void;
export {};
//# sourceMappingURL=desktop_readonly.d.ts.map