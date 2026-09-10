import type { Context } from '@deepseek-ai/cordis';
import Schema from '@deepseek-ai/schemastery';
export declare const name = "hku-agents";
export declare const inject: string[];
export interface Config {
    baseUrl: string;
    tokenEnv: string;
    timeoutMs: number;
}
export declare const Config: Schema<Config>;
export declare function apply(ctx: Context, config: Config): void;
//# sourceMappingURL=index.d.ts.map