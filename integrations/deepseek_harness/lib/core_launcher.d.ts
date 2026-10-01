type Probe = 'core' | 'absent' | 'occupied';
export interface LaunchResult {
    state: 'ready' | 'failed';
    code: string;
    started: boolean;
}
export declare function probeCore(baseUrl: string): Promise<Probe>;
export declare function createCoreLauncher(baseUrl: string, options?: {
    descriptor?: string;
    platform?: string;
    probe?: () => Promise<Probe>;
    launch?: (python: string, app: string, root: string) => Promise<void>;
    wait?: () => Promise<void>;
    attempts?: number;
}): {
    ensureStarted(): Promise<LaunchResult>;
};
export {};
//# sourceMappingURL=core_launcher.d.ts.map