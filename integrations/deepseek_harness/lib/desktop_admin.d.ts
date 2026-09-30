import type { Context } from '@deepseek-ai/cordis';
import { type HKUAgentsClient } from './client.js';
export declare const DESKTOP_FACILITIES_PATH = "/api/hku-agents/admin/facilities";
interface ExactFetchRoute {
    path: string;
    methods: string[];
    requestBody: 'buffered';
    fetch(request: Request): Promise<Response>;
}
export declare function readDesktopFacilities(client: Pick<HKUAgentsClient, 'listLibraryFacilities'>, signal?: AbortSignal): Promise<{
    ok: boolean;
    read_only: boolean;
    derived_locally: boolean;
    browser_interactions_performed: boolean;
    booking_writes_performed: number;
    facility_count: number;
    availability_target_count: number;
    facilities: ({
        facility_type: string;
        name: string;
        location: string;
    } | null)[];
    availability_targets: ({
        facility_type: string;
        location: string;
        booking_facility_type: string;
        availability_search_supported: boolean;
        booking_preview_supported: boolean;
        supervised_booking_supported: boolean;
    } | null)[];
    policy_verified_on: string | null;
    correlation_id: string | null;
    error?: never;
} | {
    ok: boolean;
    read_only: boolean;
    error: {
        code: string;
        recovery: string;
    };
    correlation_id: null;
    derived_locally?: never;
    browser_interactions_performed?: never;
    booking_writes_performed?: never;
    facility_count?: never;
    availability_target_count?: never;
    facilities?: never;
    availability_targets?: never;
    policy_verified_on?: never;
}>;
export declare function desktopFacilitiesRoute(client: Pick<HKUAgentsClient, 'listLibraryFacilities'>): ExactFetchRoute;
export declare function installDesktopAdminBridge(ctx: Context, client: Pick<HKUAgentsClient, 'listLibraryFacilities'>): void;
export {};
//# sourceMappingURL=desktop_admin.d.ts.map