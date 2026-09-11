import Schema from '@deepseek-ai/schemastery';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { HKUAgentsClient } from './client.js';
export const name = 'hku-agents';
export const inject = ['tools'];
export const Config = Schema.object({
    baseUrl: Schema.string().default('http://127.0.0.1:7860'),
    tokenEnv: Schema.string().default('INTEGRATION_API_TOKEN'),
    timeoutMs: Schema.number().default(45000),
});
const envelopeOutput = {
    schema: { type: 'json' },
    render: (_args, value) => [
        { type: 'text', text: JSON.stringify(value, null, 2) },
    ],
};
export function apply(ctx, config) {
    const client = new HKUAgentsClient(config);
    ctx.tools.register(defineTool({
        name: 'hku_sis_status',
        description: 'Check the local HKU AGENTS service, read-only SIS browser connection, and available capabilities. Use this before other HKU SIS tools or when connection state is unclear. This never logs in or writes to SIS.',
        parameters: {},
        output: envelopeOutput,
        timeoutMs: config.timeoutMs,
        async execute(_args, execution) {
            return client.status(execution.signal);
        },
    }));
    ctx.tools.register(defineTool({
        name: 'hku_sis_navigate_and_preflight',
        description: 'Preferred one-step read-only SIS check. After the user manually completes HKU Portal login and MFA, bind the available verified Portal tab, follow only the fixed Portal-to-SIS path, select the exact requested term, read the Temporary Course List, and strictly compare it with the complete expected course/section set. Check result.ready for the domain decision. Restricted navigation clicks may occur: result.navigation_interactions_performed and result.term_selection_performed report them explicitly. result.enrollment_writes_performed is always 0 because this tool cannot search, add, delete, enter Step 2/3, enroll, or submit. Do not describe zero enrollment writes as zero clicks.',
        parameters: {
            term_label: {
                type: 'string',
                required: true,
                description: 'Exact SIS term label to select, for example 2026-27 Sem 2.',
            },
            expected_courses: {
                type: 'array',
                required: true,
                description: 'Complete expected Temporary Course List as course code and section pairs.',
                items: {
                    type: 'object',
                    additionalProperties: false,
                    properties: {
                        course_code: {
                            type: 'string',
                            required: true,
                            description: 'HKU course code, for example COMP3297.',
                        },
                        section: {
                            type: 'string',
                            required: true,
                            description: 'SIS section identifier, for example 2B.',
                        },
                    },
                },
            },
        },
        output: envelopeOutput,
        timeoutMs: config.timeoutMs,
        async execute(args, execution) {
            return client.navigateAndPreflight(args, execution.signal);
        },
    }));
    ctx.tools.register(defineTool({
        name: 'hku_sis_open_enrollment_add_classes',
        description: 'After the user manually completes HKU Portal login and MFA, navigate through fixed verified Portal and SIS targets, select one exact requested SIS term when prompted, and return the read-only Enrollment Add Classes snapshot. This tool accepts no URL, selector, coordinate, script, or course input. It cannot search, add, delete, enter Step 2/3, or submit.',
        parameters: {
            term_label: {
                type: 'string',
                required: true,
                description: 'Exact SIS term label to select, for example 2026-27 Sem 2.',
            },
        },
        output: envelopeOutput,
        timeoutMs: config.timeoutMs,
        async execute(args, execution) {
            return client.navigateToEnrollmentAddClasses(args, execution.signal);
        },
    }));
    ctx.tools.register(defineTool({
        name: 'hku_sis_sync_course_lists',
        description: 'Read the current authenticated SIS Enrollment Add Classes page through the local HKU AGENTS extension. Returns Temporary Course List and Class Schedule separately. It never clicks, edits, enrolls, drops, or submits.',
        parameters: {},
        output: envelopeOutput,
        timeoutMs: config.timeoutMs,
        async execute(_args, execution) {
            return client.syncCourseLists(execution.signal);
        },
    }));
    ctx.tools.register(defineTool({
        name: 'hku_sis_preflight',
        description: 'Run a strict read-only comparison between the requested HKU term plus course/section pairs and the Temporary Course List visible in the bound SIS tab. Users do not provide class numbers. Check result.ready for the domain decision; no SIS write request is sent.',
        parameters: {
            term_label: {
                type: 'string',
                required: true,
                description: 'Exact SIS term label, for example 2026-27 Sem 2.',
            },
            expected_courses: {
                type: 'array',
                required: true,
                description: 'Complete expected Temporary Course List as course code and section pairs.',
                items: {
                    type: 'object',
                    additionalProperties: false,
                    properties: {
                        course_code: {
                            type: 'string',
                            required: true,
                            description: 'HKU course code, for example COMP3297.',
                        },
                        section: {
                            type: 'string',
                            required: true,
                            description: 'SIS section identifier, for example 2B.',
                        },
                    },
                },
            },
        },
        output: envelopeOutput,
        timeoutMs: config.timeoutMs,
        async execute(args, execution) {
            return client.preflight(args, execution.signal);
        },
    }));
}
//# sourceMappingURL=index.js.map