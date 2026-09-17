import type { Context } from '@deepseek-ai/cordis'
import Schema from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'

import { HKUAgentsClient } from './client.js'

export const name = 'hku-agents'
export const inject = ['tools']

export interface Config {
  baseUrl: string
  tokenEnv: string
  timeoutMs: number
}

export const Config: Schema<Config> = Schema.object({
  baseUrl: Schema.string().default('http://127.0.0.1:7860'),
  tokenEnv: Schema.string().default('INTEGRATION_API_TOKEN'),
  timeoutMs: Schema.number().default(45000),
})

const envelopeOutput = {
  schema: { type: 'json' as const },
  render: (_args: unknown, value: unknown) => [
    { type: 'text' as const, text: JSON.stringify(value, null, 2) },
  ],
}

export function apply(ctx: Context, config: Config): void {
  const client = new HKUAgentsClient(config)

  ctx.tools.register(
    defineTool({
      name: 'hku_sis_status',
      description:
        'Check the local HKU AGENTS service, read-only SIS browser connection, and available capabilities. Use this before other HKU SIS tools or when connection state is unclear. This never logs in or writes to SIS.',
      parameters: {},
      output: envelopeOutput,
      timeoutMs: config.timeoutMs,
      async execute(_args, execution) {
        return client.status(execution.signal)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_sis_navigate_and_preflight',
      description:
        'Preferred one-step read-only SIS check. After the user manually completes HKU Portal login and MFA, bind the available verified Portal tab, follow only the fixed Portal-to-SIS path, select the exact requested term, read the Temporary Course List, and strictly compare it with the complete expected course/section set. Check result.ready for the domain decision. Restricted navigation clicks may occur: result.navigation_interactions_performed and result.term_selection_performed report them explicitly. result.enrollment_writes_performed is always 0 because this tool cannot search, add, delete, enter Step 2/3, enroll, or submit. Do not describe zero enrollment writes as zero clicks.',
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
        return client.navigateAndPreflight(args, execution.signal)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_sis_open_enrollment_add_classes',
      description:
        'After the user manually completes HKU Portal login and MFA, navigate through fixed verified Portal and SIS targets, select one exact requested SIS term when prompted, and return the read-only Enrollment Add Classes snapshot. This tool accepts no URL, selector, coordinate, script, or course input. It cannot search, add, delete, enter Step 2/3, or submit.',
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
        return client.navigateToEnrollmentAddClasses(args, execution.signal)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_sis_sync_course_lists',
      description:
        'Read the current authenticated SIS Enrollment Add Classes page through the local HKU AGENTS extension. Returns Temporary Course List and Class Schedule separately. It never clicks, edits, enrolls, drops, or submits.',
      parameters: {},
      output: envelopeOutput,
      timeoutMs: config.timeoutMs,
      async execute(_args, execution) {
        return client.syncCourseLists(execution.signal)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_sis_preflight',
      description:
        'Run a strict read-only comparison between the requested HKU term plus course/section pairs and the Temporary Course List visible in the bound SIS tab. Users do not provide class numbers. Check result.ready for the domain decision; no SIS write request is sent.',
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
        return client.preflight(args, execution.signal)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_sis_timetable_sync',
      description:
        'Synchronize the weekly class timetable for one exact HKU term from the dedicated sweb.hku.hk My Weekly Schedule application. The only accepted input is term_label; never copy navigation result fields into the input. Restricted Portal/CAS navigation may occur, but the tool performs zero timetable or enrollment writes.',
      parameters: {
        term_label: {
          type: 'string',
          required: true,
          description: 'Exact SIS term label, for example 2026-27 Sem 1.',
        },
      },
      output: envelopeOutput,
      timeoutMs: config.timeoutMs,
      async execute(args, execution) {
        return client.syncWeeklyTimetable(
          { term_label: args.term_label },
          execution.signal,
        )
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_sis_next_class',
      description:
        'Find the next recurring weekly class from the process-local timetable created by hku_sis_timetable_sync. This performs no browser interaction and no write. Treat its warning about teaching weeks and holidays as mandatory.',
      parameters: {
        term_label: { type: 'string' },
        as_of: {
          type: 'string',
          description: 'Optional ISO-8601 timestamp; defaults to current Hong Kong time.',
        },
        days_ahead: { type: 'number', description: 'Search horizon, 1 to 28 days.' },
      },
      output: envelopeOutput,
      timeoutMs: config.timeoutMs,
      async execute(args, execution) {
        return client.nextClass(args, execution.signal)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_sis_find_free_slots',
      description:
        'Calculate recurring weekday free periods from the process-local synchronized timetable. This performs no browser interaction and no write.',
      parameters: {
        term_label: { type: 'string' },
        weekdays: {
          type: 'array',
          items: { type: 'string' },
          description: 'Lowercase weekday names; defaults to Monday through Friday.',
        },
        window_start: { type: 'string', description: 'HH:MM, default 09:00.' },
        window_end: { type: 'string', description: 'HH:MM, default 18:00.' },
        minimum_minutes: { type: 'number', description: 'Minimum free duration.' },
      },
      output: envelopeOutput,
      timeoutMs: config.timeoutMs,
      async execute(args, execution) {
        return client.findFreeSlots(args, execution.signal)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_sis_check_timetable_conflicts',
      description:
        'Compare explicit candidate class meetings with the process-local synchronized timetable. It never searches, selects, adds, or enrolls in a course.',
      parameters: {
        term_label: { type: 'string' },
        candidate_meetings: {
          type: 'array',
          required: true,
          items: {
            type: 'object',
            additionalProperties: false,
            properties: {
              course_code: { type: 'string', required: true },
              section: { type: 'string', required: true },
              weekday: { type: 'string', required: true },
              start_time: { type: 'string', required: true },
              end_time: { type: 'string', required: true },
              room: { type: 'string' },
            },
          },
        },
      },
      output: envelopeOutput,
      timeoutMs: config.timeoutMs,
      async execute(args, execution) {
        return client.checkTimetableConflicts(args, execution.signal)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_sis_exam_status',
      description:
        'Inspect an already-open and bound SIS Examination Timetables page. Reports unavailable, not_published, partially_published, or published plus visible entries; performs no navigation and no write.',
      parameters: {
        term_label: { type: 'string' },
      },
      output: envelopeOutput,
      timeoutMs: config.timeoutMs,
      async execute(args, execution) {
        return client.examStatus(args, execution.signal)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_moodle_inspect_dashboard',
      description:
        'Open Moodle through an authenticated HKU Portal tab and verify only login state and Dashboard diagnostics. It does not read course names, assignments, grades, messages, or submissions, and performs no Moodle write.',
      parameters: {},
      output: envelopeOutput,
      timeoutMs: config.timeoutMs,
      async execute(_args, execution) {
        return client.inspectMoodleDashboard(execution.signal)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_moodle_list_courses',
      description:
        'Open the authenticated HKU Moodle Dashboard and list only visible course membership identifiers and names. Private course rows remain process-local and are not persisted in task history. It does not read assignments, grades, participants, messages, or submissions, and performs no Moodle write.',
      parameters: {},
      output: envelopeOutput,
      timeoutMs: config.timeoutMs,
      async execute(_args, execution) {
        return client.listMoodleCourses(execution.signal)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_moodle_upcoming_assignments',
      description:
        'Read assignment and activity deadlines currently visible in the authenticated Moodle Dashboard for a bounded 1-90 day future window. Private titles and dates remain process-local and are not persisted in task history. It does not open activity pages or read grades, participants, submissions, or submission status, and performs no Moodle write.',
      parameters: {
        days_ahead: {
          type: 'number',
          description: 'Future window in days, from 1 through 90. Defaults to 14.',
        },
      },
      output: envelopeOutput,
      timeoutMs: config.timeoutMs,
      async execute(args, execution) {
        return client.listUpcomingMoodleAssignments(args, execution.signal)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'hku_daily_briefing',
      description:
        'Build a read-only daily briefing solely from the process-local timetable and Moodle deadline caches. This tool performs no browser interaction and no write. Inspect result.complete and each result.source_status entry; missing, stale, term-mismatched, or insufficiently covered sources are omitted rather than treated as empty. Synchronize both source tools first without restarting HKU AGENTS.',
      parameters: {
        term_label: {
          type: 'string',
          description: 'Optional exact term label used to validate the timetable cache.',
        },
        as_of: {
          type: 'string',
          description: 'Optional ISO-8601 timestamp; defaults to the current time.',
        },
        days_ahead: {
          type: 'number',
          description: 'Briefing deadline and next-class horizon, from 1 through 14 days.',
        },
        max_cache_age_minutes: {
          type: 'number',
          description: 'Maximum accepted age of either process-memory cache; defaults to 120 minutes.',
        },
      },
      output: envelopeOutput,
      timeoutMs: config.timeoutMs,
      async execute(args, execution) {
        return client.dailyBriefing(args, execution.signal)
      },
    }),
  )
}
