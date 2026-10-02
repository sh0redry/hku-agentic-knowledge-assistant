import type { Context } from '@deepseek-ai/cordis';
import { type HKUAgentsClient } from './client.js';
import { type TestHistory } from './history.js';
export declare function projectLibrary(value: unknown, depth?: number): unknown;
export declare function installDesktopLibraryBridge(ctx: Context, client: Pick<HKUAgentsClient, 'libraryOperator'>, history?: Pick<TestHistory, 'append'>): void;
//# sourceMappingURL=desktop_library.d.ts.map