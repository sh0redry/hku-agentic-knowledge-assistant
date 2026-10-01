import type { ToolCallView, ToolResult, ToolResultView } from '@deepseek-ai/dsh-tools';
export declare function compactProjection(value: unknown): Record<string, string | number | boolean | null>;
export declare function toolPresentation(name: string): {
    presentCall(): ToolCallView;
    presentResult(_args: unknown, result: ToolResult): ToolResultView;
};
//# sourceMappingURL=presentation.d.ts.map