from __future__ import annotations

import asyncio
import json
import html
import uuid
from datetime import datetime, timezone

import gradio as gr

import config
from ui.api_client import HKUAgentsAPIClient


def _pretty(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _course_rows(value: str) -> list[dict]:
    rows = []
    for line_number, raw_line in enumerate(value.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 3 or not all(parts):
            raise ValueError(
                f"Line {line_number} must use COURSE_CODE | SECTION | CLASS_NUMBER."
            )
        rows.append(
            {"course_code": parts[0], "section": parts[1], "class_number": parts[2]}
        )
    if not rows:
        raise ValueError("At least one course entry is required.")
    return rows


def _expected_course_rows(value: str) -> list[dict]:
    rows = []
    for line_number, raw_line in enumerate(value.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"Line {line_number} must use COURSE_CODE | SECTION.")
        rows.append({"course_code": parts[0], "section": parts[1]})
    if not rows:
        raise ValueError("At least one expected course is required.")
    return rows


def _meeting_rows(value: str) -> list[dict]:
    rows = []
    for line_number, raw_line in enumerate(value.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) not in {5, 6} or not all(parts[:5]):
            raise ValueError(
                f"Line {line_number} must use COURSE | SECTION | WEEKDAY | START | END | ROOM(optional)."
            )
        rows.append(
            {
                "course_code": parts[0],
                "section": parts[1],
                "weekday": parts[2].lower(),
                "start_time": parts[3],
                "end_time": parts[4],
                "room": parts[5] if len(parts) == 6 and parts[5] else None,
            }
        )
    if not rows:
        raise ValueError("At least one candidate meeting is required.")
    return rows


def create_gradio_ui(container):
    knowledge_capability = container.registry.get("knowledge.answer")
    sis_browser = container.connectors["sis_browser"]
    api_client = HKUAgentsAPIClient(
        config.API_BASE_URL,
        integration_token=config.INTEGRATION_API_TOKEN,
    )

    def bridge_websocket_url():
        base = config.API_BASE_URL.rstrip("/")
        scheme = "wss" if base.startswith("https://") else "ws"
        address = base.split("://", 1)[-1]
        return f"{scheme}://{address}/api/v1/browser/ws"

    def pairing_info():
        return container.browser_bridge.pairing_info(bridge_websocket_url())

    def safe_call(call):
        try:
            return _pretty(call())
        except Exception as exc:
            return _pretty({"status": "error", "message": str(exc)})

    async def chat_handler(message, history, session_id):
        try:
            normalized_history = [item for item in (history or []) if isinstance(item, dict)]
            response = await asyncio.to_thread(
                api_client.chat,
                message,
                normalized_history,
                session_id,
            )
            return response.get("answer") or "No answer was returned."
        except Exception as exc:
            return f"Knowledge Agent error: {exc}"

    def initialization_view(snapshot):
        status = snapshot["status"]
        percent = round(snapshot["progress"] * 100)
        description = html.escape(snapshot["description"])
        progress_markup = (
            '<div class="agent-progress" role="progressbar" '
            f'aria-valuenow="{percent}" aria-valuemin="0" aria-valuemax="100">'
            f'<div class="agent-progress-fill" style="width:{percent}%"></div>'
            "</div>"
            f'<div class="agent-progress-label">{percent}%</div>'
        )

        if status == "ready":
            return (
                gr.update(visible=False),
                gr.update(visible=True),
                gr.update(value="Knowledge Agent is ready."),
                gr.update(value=progress_markup),
                gr.update(visible=False),
                gr.update(active=False),
            )
        if status == "failed":
            error = html.escape(snapshot["error"] or "Unknown initialization error")
            return (
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(
                    value=(
                        "### Initialization failed\n"
                        f"`{error}`\n\nCheck the terminal log and retry."
                    )
                ),
                gr.update(value=progress_markup),
                gr.update(visible=True),
                gr.update(active=False),
            )
        return (
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(value=f"**{description}**"),
            gr.update(value=progress_markup),
            gr.update(visible=False),
            gr.update(active=True),
        )

    def begin_chat_initialization():
        return initialization_view(knowledge_capability.start_initialize())

    def poll_chat_initialization():
        return initialization_view(knowledge_capability.initialization_snapshot())

    async def preflight_handler(term_label, current_term, expected_text, visible_text):
        try:
            payload = {
                "origin": "https://sis-main.hku.hk",
                "logged_in": True,
                "page_kind": "cart",
                "term_label": term_label.strip(),
                "current_term_label": current_term.strip(),
                "expected_courses": _course_rows(expected_text),
                "visible_courses": _course_rows(visible_text),
            }
            response = await asyncio.to_thread(
                api_client.sis_preflight,
                payload,
            )
            return _pretty(response)
        except Exception as exc:
            return _pretty({"ok": False, "simulated": True, "error": str(exc)})

    async def live_preflight_handler(term_label, expected_text):
        try:
            response = await asyncio.to_thread(
                api_client.integration_sis_preflight,
                {
                    "term_label": term_label.strip(),
                    "expected_courses": _expected_course_rows(expected_text),
                },
            )
            return _pretty(response)
        except Exception as exc:
            return _pretty(
                {
                    "ok": False,
                    "read_only": True,
                    "error": getattr(exc, "code", type(exc).__name__),
                    "message": str(exc),
                }
            )

    async def navigate_and_preflight_handler(term_label, expected_text):
        try:
            response = await asyncio.to_thread(
                api_client.integration_sis_navigate_and_preflight,
                {
                    "term_label": term_label.strip(),
                    "expected_courses": _expected_course_rows(expected_text),
                },
            )
            return _pretty(response)
        except Exception as exc:
            return _pretty(
                {
                    "api_version": "v1",
                    "ok": False,
                    "read_only": True,
                    "result": None,
                    "task": None,
                    "error": {
                        "code": getattr(exc, "code", type(exc).__name__),
                        "message": str(exc),
                    },
                }
            )

    async def timetable_sync_handler(term_label):
        try:
            return _pretty(
                await asyncio.to_thread(api_client.timetable_sync_weekly, term_label.strip())
            )
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def timetable_next_handler(term_label):
        try:
            return _pretty(
                await asyncio.to_thread(
                    api_client.timetable_next_class,
                    {"term_label": term_label.strip()},
                )
            )
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def timetable_free_handler(term_label, window_start, window_end, minimum_minutes):
        try:
            return _pretty(
                await asyncio.to_thread(
                    api_client.timetable_free_slots,
                    {
                        "term_label": term_label.strip(),
                        "window_start": window_start.strip(),
                        "window_end": window_end.strip(),
                        "minimum_minutes": int(minimum_minutes),
                    },
                )
            )
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def timetable_conflict_handler(term_label, candidate_text):
        try:
            return _pretty(
                await asyncio.to_thread(
                    api_client.timetable_check_conflicts,
                    {
                        "term_label": term_label.strip(),
                        "candidate_meetings": _meeting_rows(candidate_text),
                    },
                )
            )
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def timetable_exam_handler(term_label):
        try:
            return _pretty(
                await asyncio.to_thread(
                    api_client.timetable_exam_status,
                    {"term_label": term_label.strip()},
                )
            )
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def moodle_dashboard_handler():
        try:
            return _pretty(
                await asyncio.to_thread(api_client.moodle_inspect_dashboard)
            )
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def moodle_courses_handler():
        try:
            return _pretty(await asyncio.to_thread(api_client.moodle_list_courses))
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def moodle_assignments_handler(days_ahead):
        try:
            return _pretty(
                await asyncio.to_thread(
                    api_client.moodle_upcoming_assignments,
                    int(days_ahead),
                )
            )
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def daily_briefing_handler(term_label, days_ahead, max_cache_age_minutes):
        try:
            return _pretty(
                await asyncio.to_thread(
                    api_client.daily_briefing,
                    term_label,
                    int(days_ahead),
                    int(max_cache_age_minutes),
                )
            )
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def portal_notices_handler():
        try:
            return _pretty(await asyncio.to_thread(api_client.portal_notices))
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def library_research_handler(query, field, scope, limit):
        try:
            return _pretty(await asyncio.to_thread(
                api_client.library_research_search,
                query.strip(), field, scope, int(limit),
            ))
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def library_item_handler(record_id):
        try:
            return _pretty(await asyncio.to_thread(
                api_client.library_research_item, record_id.strip()
            ))
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def library_access_handler(record_id):
        try:
            return _pretty(await asyncio.to_thread(
                api_client.library_research_access_options, record_id.strip()
            ))
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def library_space_handler(facility_type, date):
        try:
            return _pretty(await asyncio.to_thread(
                api_client.library_space_availability, facility_type, date
            ))
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def library_booking_preview_handler(
        facility_type, date, floor, room, start_time, end_time, eligibility_category
    ):
        try:
            return _pretty(await asyncio.to_thread(
                api_client.library_space_booking_preview,
                facility_type,
                date,
                floor,
                room,
                start_time,
                end_time,
                eligibility_category,
            ))
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def library_facilities_handler():
        try:
            return _pretty(await asyncio.to_thread(api_client.library_list_facilities))
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def library_hours_handler():
        try:
            return _pretty(await asyncio.to_thread(api_client.library_hours_and_locations))
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def live_sis_call(action, operation):
        completed_at = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            result = await asyncio.to_thread(operation)
            response = {
                "ok": True,
                "read_only": True,
                "action": action,
                "completed_at": completed_at(),
                "result": result,
            }
            if action == "inspect_cart":
                response["cart_state"] = (
                    "empty"
                    if result.get("temporary_course_count", result.get("course_count", 0)) == 0
                    else "courses_found"
                )
            return _pretty(response)
        except Exception as exc:
            return _pretty(
                {
                    "ok": False,
                    "read_only": True,
                    "action": action,
                    "completed_at": completed_at(),
                    "error": getattr(exc, "code", type(exc).__name__),
                    "message": str(exc),
                }
            )

    async def bind_hku_tab():
        return await live_sis_call("bind_hku_tab", api_client.bind_hku_tab)

    async def open_enrollment_add_classes(term_label: str):
        try:
            # This call already returns the versioned Integration API envelope.
            # Return it directly so a domain/API failure is not hidden under an
            # outer GUI-level `ok: true` wrapper.
            return _pretty(
                await asyncio.to_thread(
                    api_client.open_enrollment_add_classes,
                    term_label,
                )
            )
        except Exception as exc:
            return _pretty(
                {
                    "api_version": "v1",
                    "ok": False,
                    "read_only": True,
                    "result": None,
                    "task": None,
                    "error": {
                        "code": getattr(exc, "code", type(exc).__name__),
                        "message": str(exc),
                    },
                }
            )

    async def inspect_sis_page():
        return await live_sis_call("inspect_page", api_client.inspect_sis_page)

    async def inspect_sis_cart():
        try:
            return _pretty(await asyncio.to_thread(api_client.integration_sis_sync))
        except Exception as exc:
            return _pretty(
                {
                    "api_version": "v1",
                    "ok": False,
                    "read_only": True,
                    "error": {
                        "code": getattr(exc, "code", type(exc).__name__),
                        "message": str(exc),
                    },
                }
            )

    with gr.Blocks(title="HKU AGENTS") as demo:
        # A concrete value is deep-copied per browser session. Using a callable
        # creates a hidden queued load event that can stall the first UI action
        # in some mounted Gradio/FastAPI browser sessions.
        session_id = gr.State(str(uuid.uuid4()))
        gr.Markdown("# HKU AGENTS\nLocal-first, capability-based HKU assistant framework.")

        with gr.Tab("Dashboard"):
            gr.Markdown(
                "The platform API is the system boundary. SIS browser access is read-only."
            )
            health_output = gr.Code(value="Press Refresh", language="json", label="Platform health")
            browser_health_output = gr.Code(
                value=_pretty(sis_browser.health()),
                language="json",
                label="SIS browser connection",
            )
            health_button = gr.Button("Refresh health", variant="primary")
            health_button.click(
                lambda: (
                    safe_call(api_client.health),
                    safe_call(api_client.browser_status),
                ),
                outputs=[health_output, browser_health_output],
                queue=False,
            )

        with gr.Tab("Daily Briefing"):
            gr.Markdown(
                "Combines only the current process-memory timetable, Moodle deadline, "
                "and Portal notice "
                "caches. This does not navigate the browser or refresh any source. "
                "Synchronize all three sources first; missing, stale, mismatched, and "
                "insufficiently covered caches are reported explicitly."
            )
            briefing_term = gr.Textbox(
                label="Optional exact term label",
                placeholder="2026-27 Sem 1",
            )
            briefing_days = gr.Number(
                value=7, minimum=1, maximum=14, precision=0, label="Days ahead"
            )
            briefing_max_age = gr.Number(
                value=120,
                minimum=1,
                maximum=10080,
                precision=0,
                label="Maximum cache age (minutes)",
            )
            briefing_button = gr.Button("Build local daily briefing", variant="primary")
            briefing_output = gr.Code(
                value="Synchronize the timetable, Moodle deadlines, and Portal notices first.",
                language="json",
                label="Daily briefing",
            )
            briefing_button.click(
                daily_briefing_handler,
                inputs=[briefing_term, briefing_days, briefing_max_age],
                outputs=briefing_output,
                show_progress="minimal",
                queue=False,
            )

        with gr.Tab("Chat") as chat_tab:
            with gr.Group(elem_id="chat-initialization") as initialization_panel:
                gr.Markdown("## Preparing Chat")
                initialization_status = gr.Markdown(
                    "The knowledge agent will initialize when you enter this tab. "
                    "Model loading can take longer on the first run."
                )
                initialization_progress = gr.HTML(
                    '<div class="agent-progress" role="progressbar" '
                    'aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">'
                    '<div class="agent-progress-fill" style="width:0%"></div></div>'
                    '<div class="agent-progress-label">0%</div>'
                )
                retry_initialization = gr.Button(
                    "Retry initialization", variant="primary", visible=False
                )

            initialization_timer = gr.Timer(value=0.4, active=False)

            with gr.Group(visible=False) as chat_panel:
                chatbot = gr.Chatbot(
                    height=650,
                    placeholder="Ask the registered HKU Knowledge Agent.",
                    show_label=False,
                    layout="bubble",
                )
                gr.ChatInterface(
                    fn=chat_handler,
                    chatbot=chatbot,
                    additional_inputs=[session_id],
                )

            initialization_outputs = [
                initialization_panel,
                chat_panel,
                initialization_status,
                initialization_progress,
                retry_initialization,
                initialization_timer,
            ]
            chat_tab.select(
                begin_chat_initialization,
                outputs=initialization_outputs,
                api_name="initialize_chat",
                api_visibility="private",
                show_progress="hidden",
                queue=False,
            )
            retry_initialization.click(
                begin_chat_initialization,
                outputs=initialization_outputs,
                api_name="retry_chat_initialization",
                api_visibility="private",
                show_progress="hidden",
                queue=False,
            )
            initialization_timer.tick(
                poll_chat_initialization,
                outputs=initialization_outputs,
                api_name="poll_chat_initialization",
                api_visibility="private",
                show_progress="hidden",
                queue=False,
            )

        with gr.Tab("SIS Preflight"):
            gr.Markdown(
                "## Restricted Portal navigation and live inspection\n"
                "After you complete Portal login and MFA, bind the active HKU tab. "
                "HKU AGENTS may open only the fixed SIS and Enrollment Add Classes "
                "targets. It cannot search courses, enter Step 2/3, or submit forms."
            )
            live_term_label = gr.Textbox(
                value="2026-27 Sem 2",
                label="Target SIS term",
            )
            with gr.Row():
                bind_hku_button = gr.Button("Bind active HKU tab", variant="primary")
                navigate_sis_button = gr.Button("Open Enrollment Add Classes")
                inspect_sis_button = gr.Button("Inspect current SIS page")
                inspect_cart_button = gr.Button("Inspect cart")
            live_sis_output = gr.Code(
                value="Pair the extension in Connections first.",
                language="json",
                label="Live read-only result",
            )
            bind_hku_button.click(
                bind_hku_tab,
                outputs=live_sis_output,
                queue=False,
            )
            navigate_sis_button.click(
                open_enrollment_add_classes,
                inputs=live_term_label,
                outputs=live_sis_output,
                show_progress="minimal",
                queue=False,
            )
            inspect_sis_button.click(
                inspect_sis_page,
                outputs=live_sis_output,
                queue=False,
            )
            inspect_cart_button.click(
                inspect_sis_cart,
                outputs=live_sis_output,
                show_progress="minimal",
                queue=False,
            )

            gr.Markdown(
                "## One-step enrollment preflight (read-only)\n"
                "Enter only the courses you expect. The preferred action starts from the "
                "authenticated Portal, binds it automatically, opens the requested SIS term, reads the Temporary "
                "Course List, and performs strict comparison in one task."
            )
            with gr.Row():
                live_expected = gr.Textbox(
                    value="COMP2119 | 1A",
                    lines=5,
                    label="Expected: COURSE | SECTION",
                )
            navigate_and_preflight_button = gr.Button(
                "Navigate from Portal and run preflight", variant="primary"
            )
            navigate_and_preflight_output = gr.Code(
                value=(
                    "Keep the authenticated Portal tab active, then run the combined "
                    "read-only check."
                ),
                language="json",
                label="Automatic navigation and preflight result",
            )
            navigate_and_preflight_button.click(
                navigate_and_preflight_handler,
                inputs=[live_term_label, live_expected],
                outputs=navigate_and_preflight_output,
                show_progress="minimal",
                queue=False,
            )

            gr.Markdown(
                "Use the manual preflight below only when Enrollment Add Classes is "
                "already open and bound."
            )
            live_preflight_button = gr.Button(
                "Run preflight on current SIS page"
            )
            live_preflight_output = gr.Code(
                value="Bind the SIS tab and open Enrollment Add Classes first.",
                language="json",
                label="Live preflight result",
            )
            live_preflight_button.click(
                live_preflight_handler,
                inputs=[live_term_label, live_expected],
                outputs=live_preflight_output,
                show_progress="minimal",
                queue=False,
            )

            gr.Markdown(
                "## Offline simulator\n"
                "This validates exact course, section, and class-number sets. "
                "It does not connect to Chrome or HKU SIS and sends no requests."
            )
            with gr.Row():
                term_label = gr.Textbox(value="2026-27 Sem 1", label="Requested term")
                current_term = gr.Textbox(value="2026-27 Sem 1", label="Simulated current term")
            with gr.Row():
                expected = gr.Textbox(
                    value="COMP2119 | 1A | 12345",
                    lines=5,
                    label="Expected: COURSE | SECTION | CLASS NUMBER",
                )
                visible = gr.Textbox(
                    value="COMP2119 | 1A | 12345",
                    lines=5,
                    label="Visible cart: COURSE | SECTION | CLASS NUMBER",
                )
            preflight_button = gr.Button("Run simulated preflight", variant="primary")
            preflight_output = gr.Code(language="json", label="Preflight result")
            preflight_button.click(
                preflight_handler,
                inputs=[term_label, current_term, expected, visible],
                outputs=preflight_output,
                queue=False,
            )

        with gr.Tab("Timetable"):
            gr.Markdown(
                "## Read-only HKU weekly timetable\n"
                "Sync uses the fixed Portal/CAS → sweb My Weekly Schedule route. "
                "Enrollment Add Classes is not used as the timetable source. Derived tools "
                "use process-memory data and do not "
                "interact with Chrome."
            )
            timetable_term = gr.Textbox(value="2026-27 Sem 1", label="SIS term")
            with gr.Row():
                timetable_sync_button = gr.Button("Sync weekly timetable", variant="primary")
                timetable_next_button = gr.Button("Find next class")
            timetable_output = gr.Code(
                value="Bind an authenticated Portal or My Weekly Schedule tab before synchronization.",
                language="json",
                label="Timetable result",
            )
            timetable_sync_button.click(
                timetable_sync_handler,
                inputs=timetable_term,
                outputs=timetable_output,
                show_progress="minimal",
                queue=False,
            )
            timetable_next_button.click(
                timetable_next_handler,
                inputs=timetable_term,
                outputs=timetable_output,
                queue=False,
            )
            with gr.Row():
                free_start = gr.Textbox(value="09:00", label="Free-time window start")
                free_end = gr.Textbox(value="18:00", label="Free-time window end")
                free_minimum = gr.Number(value=60, precision=0, label="Minimum minutes")
            free_button = gr.Button("Find weekday free slots")
            free_button.click(
                timetable_free_handler,
                inputs=[timetable_term, free_start, free_end, free_minimum],
                outputs=timetable_output,
                queue=False,
            )
            candidate_meetings = gr.Textbox(
                value="COMP3297 | 2B | thursday | 10:00 | 11:50 | CYCP1",
                lines=4,
                label="Candidate: COURSE | SECTION | WEEKDAY | START | END | ROOM(optional)",
            )
            conflict_button = gr.Button("Check candidate conflicts")
            conflict_button.click(
                timetable_conflict_handler,
                inputs=[timetable_term, candidate_meetings],
                outputs=timetable_output,
                queue=False,
            )
            gr.Markdown(
                "Exam status currently inspects an already-open, bound SIS Examination "
                "Timetables page; it performs no navigation or write."
            )
            exam_button = gr.Button("Inspect examination timetable status")
            exam_button.click(
                timetable_exam_handler,
                inputs=timetable_term,
                outputs=timetable_output,
                queue=False,
            )

        with gr.Tab("Moodle"):
            gr.Markdown(
                "## Moodle Dashboard discovery (read-only)\n"
                "Keep the authenticated HKU Portal tab active. The diagnostic action "
                "opens Moodle through the exact Portal service entry and verifies only "
                "login state and Dashboard markers. The separate course-list action "
                "below has its own explicit private-data contract."
            )
            moodle_dashboard_button = gr.Button(
                "Open and inspect Moodle Dashboard", variant="primary"
            )
            moodle_dashboard_output = gr.Code(
                value="Keep the authenticated HKU Portal tab active, then run inspection.",
                language="json",
                label="Moodle Dashboard diagnostics",
            )
            moodle_dashboard_button.click(
                moodle_dashboard_handler,
                outputs=moodle_dashboard_output,
                show_progress="minimal",
                queue=False,
            )
            gr.Markdown(
                "### Visible course membership\n"
                "Reads only course IDs, names, normalized course codes/sections when "
                "present, and explicit current/past/future markers. Private rows remain "
                "in process memory and are excluded from SQLite task history. It does "
                "not read assignments, grades, participants, messages, or submissions."
            )
            moodle_courses_button = gr.Button("List visible Moodle courses")
            moodle_courses_output = gr.Code(
                value="Open the authenticated Moodle Dashboard before listing courses.",
                language="json",
                label="Moodle visible courses",
            )
            moodle_courses_button.click(
                moodle_courses_handler,
                outputs=moodle_courses_output,
                show_progress="minimal",
                queue=False,
            )
            gr.Markdown(
                "### Upcoming assignments and activities\n"
                "Reads only machine-dated items currently visible in the Moodle Dashboard "
                "Timeline/Upcoming DOM. It does not open activity pages or read grades, "
                "participants, submission content, or submission status. Private rows are "
                "excluded from SQLite task history."
            )
            moodle_assignment_days = gr.Number(
                value=14,
                minimum=1,
                maximum=90,
                precision=0,
                label="Days ahead",
            )
            moodle_assignments_button = gr.Button("List upcoming Moodle assignments")
            moodle_assignments_output = gr.Code(
                value="Choose a 1-90 day window, then read visible Dashboard deadlines.",
                language="json",
                label="Moodle upcoming assignments",
            )
            moodle_assignments_button.click(
                moodle_assignments_handler,
                inputs=moodle_assignment_days,
                outputs=moodle_assignments_output,
                show_progress="minimal",
                queue=False,
            )

        with gr.Tab("Portal Notices"):
            gr.Markdown(
                "## HKU Portal News (read-only)\n"
                "Reads only verifiable News cards currently exposed in the authenticated "
                "Portal home-page DOM. It does not open notice detail pages. Notice rows "
                "are cached in process memory and excluded from SQLite task history."
            )
            portal_notices_button = gr.Button(
                "Read visible Portal notices", variant="primary"
            )
            portal_notices_output = gr.Code(
                value="Keep the authenticated HKU Portal home page open.",
                language="json",
                label="Portal notices",
            )
            portal_notices_button.click(
                portal_notices_handler,
                outputs=portal_notices_output,
                show_progress="minimal",
                queue=False,
            )

        with gr.Tab("Library"):
            gr.Markdown(
                "## HKU Libraries (read-only)\n"
                "Research search opens only the fixed Find@HKUL route and reads visible "
                "bibliographic results. It does not open licensed full text or save/request "
                "items. Space availability may require manual HKUL authentication; it never "
                "selects a slot or submits a reservation."
            )
            library_query = gr.Textbox(value="artificial intelligence", label="Research query")
            with gr.Row():
                library_field = gr.Dropdown(
                    choices=["any", "title", "author", "subject"], value="any", label="Field"
                )
                library_scope = gr.Dropdown(
                    choices=["hku", "everything"], value="hku", label="Scope"
                )
                library_limit = gr.Number(value=10, minimum=1, maximum=20, precision=0, label="Limit")
            library_search_button = gr.Button("Search Find@HKUL", variant="primary")
            library_output = gr.Code(
                value="Run a bounded public Find@HKUL search.", language="json", label="Library result"
            )
            library_search_button.click(
                library_research_handler,
                inputs=[library_query, library_field, library_scope, library_limit],
                outputs=library_output,
                show_progress="minimal",
                queue=False,
            )
            gr.Markdown(
                "### Item details and access options\n"
                "Paste a stable `record_id` returned by the search above. Access checks "
                "return labels only; proxy, SSO, and licensed full-text URLs are suppressed."
            )
            library_record_id = gr.Textbox(
                value="alma991000375969703414", label="Find@HKUL record ID"
            )
            with gr.Row():
                library_item_button = gr.Button("Read item details")
                library_access_button = gr.Button("Read access options")
            library_item_button.click(
                library_item_handler,
                inputs=library_record_id,
                outputs=library_output,
                show_progress="minimal",
                queue=False,
            )
            library_access_button.click(
                library_access_handler,
                inputs=library_record_id,
                outputs=library_output,
                show_progress="minimal",
                queue=False,
            )
            gr.Markdown(
                "### HKUL opening hours and locations\n"
                "Open the official current-hours page and read its visible time-period rows. "
                "An unavailable future date is reported as unknown, not as closed."
            )
            library_hours_button = gr.Button("Read current opening hours")
            library_hours_button.click(
                library_hours_handler,
                outputs=library_output,
                show_progress="minimal",
                queue=False,
            )
            gr.Markdown(
                "### Book a Space availability\n"
                "List the supported facilities and verified policy summary locally before "
                "opening an authenticated availability page."
            )
            library_facilities_button = gr.Button("List supported facilities and policies")
            library_facilities_button.click(
                library_facilities_handler,
                outputs=library_output,
                show_progress="minimal",
                queue=False,
            )
            gr.Markdown(
                "The first availability run can open the HKUL authentication page. Complete "
                "it manually in Chrome, then run the same check again."
            )
            library_facility = gr.Dropdown(
                choices=["single_study_room", "studio_editing_room", "study_table", "study_room"],
                value="single_study_room",
                label="Facility type",
            )
            library_availability_date = gr.Textbox(value="", label="Exact availability date (YYYY-MM-DD)")
            library_space_button = gr.Button("Read visible space availability")
            library_space_button.click(
                library_space_handler,
                inputs=[library_facility, library_availability_date],
                outputs=library_output,
                show_progress="minimal",
                queue=False,
            )
            gr.Markdown(
                "### Exact booking preview (Phase F1, read-only)\n"
                "Copy one exact slot from the availability result. The preview re-reads the "
                "live page, checks the displayed date and published eligibility category, "
                "and expires quickly. Date is intentionally not defaulted: copy the returned "
                "`date` value exactly. It does not click a slot or authorize a reservation."
            )
            with gr.Row():
                library_preview_date = gr.Textbox(value="", label="Date (YYYY-MM-DD)")
                library_preview_floor = gr.Textbox(value="4/F", label="Floor (optional)")
                library_preview_room = gr.Textbox(
                    value="Single Study Room (3 sessions) Room 424",
                    label="Exact room",
                )
            with gr.Row():
                library_preview_start = gr.Textbox(value="13:00", label="Start (HH:MM)")
                library_preview_end = gr.Textbox(value="17:00", label="End (HH:MM)")
                library_preview_eligibility = gr.Dropdown(
                    choices=[
                        "current_hku_students",
                        "current_hku_staff",
                        "current_hku_space_students",
                        "current_hku_space_staff",
                        "hku_alumni",
                    ],
                    value="current_hku_students",
                    label="Self-declared eligibility category",
                )
            library_preview_button = gr.Button("Create read-only booking preview")
            library_preview_button.click(
                library_booking_preview_handler,
                inputs=[
                    library_facility,
                    library_preview_date,
                    library_preview_floor,
                    library_preview_room,
                    library_preview_start,
                    library_preview_end,
                    library_preview_eligibility,
                ],
                outputs=library_output,
                show_progress="minimal",
                queue=False,
            )

        with gr.Tab("Tasks"):
            tasks_output = gr.Code(value="Press Refresh", language="json", label="Local tasks")
            tasks_button = gr.Button("Refresh tasks")
            tasks_button.click(
                lambda: safe_call(api_client.tasks),
                outputs=tasks_output,
                queue=False,
            )

        with gr.Tab("Connections"):
            gr.Markdown(
                "## Pair the read-only extension\n"
                "Load `browser_runtime/extension` as an unpacked Chrome extension, then copy "
                "this local token into its popup once. Configure `BROWSER_PAIRING_TOKEN` in "
                "the ignored `project/.env` file to preserve pairing across app restarts. "
                "Do not share the token."
            )
            current_pairing = pairing_info()
            pairing_token = gr.Textbox(
                value=current_pairing["pairing_token"],
                label="Pairing token",
                interactive=False,
            )
            websocket_address = gr.Textbox(
                value=current_pairing["websocket_url"],
                label="Local bridge address",
                interactive=False,
            )
            pairing_token_source = gr.Textbox(
                value=current_pairing["pairing_token_source"],
                label=(
                    "Pairing token source"
                    + (" (persistent)" if current_pairing["persistent_across_restarts"] else "")
                ),
                interactive=False,
            )
            integration_api_token = gr.Textbox(
                value=config.INTEGRATION_API_TOKEN,
                label=f"Integration API token ({config.INTEGRATION_API_TOKEN_SOURCE})",
                type="password",
                interactive=False,
            )
            gr.Markdown(
                "Use this separate bearer token only for trusted local DeepSeek Harness "
                "or Hermes adapters. It is not the browser-extension pairing token."
            )
            rotate_pairing_button = gr.Button("Rotate pairing token")
            revoke_pairing_button = gr.Button(
                "Revoke connection and extension pin", variant="stop"
            )
            connections_output = gr.Code(
                value=_pretty({"connections": container.connection_status()}),
                language="json",
                label="Connector status",
            )
            browser_targets_output = gr.Code(
                value=_pretty(
                    {
                        "read_only": True,
                        "targets": container.browser_bridge.status()["targets"],
                    }
                ),
                language="json",
                label="Browser target registry (sanitized origin/path only)",
            )
            connections_button = gr.Button("Refresh connections")
            rotate_pairing_button.click(
                lambda: (
                    api_client.rotate_browser_pairing()["pairing_token"],
                    "runtime_rotated",
                ),
                outputs=[pairing_token, pairing_token_source],
                queue=False,
            )
            revoke_pairing_button.click(
                lambda: (
                    api_client.revoke_browser_pairing()["pairing_token"],
                    "runtime_revoked",
                ),
                outputs=[pairing_token, pairing_token_source],
                queue=False,
            )
            connections_button.click(
                lambda: (
                    safe_call(api_client.integration_status),
                    safe_call(api_client.browser_targets),
                ),
                outputs=[connections_output, browser_targets_output],
                queue=False,
            )

        with gr.Tab("Capabilities"):
            capabilities_output = gr.Code(
                value="Press Refresh", language="json", label="Registered capabilities"
            )
            capabilities_button = gr.Button("Refresh capabilities")
            capabilities_button.click(
                lambda: safe_call(api_client.capabilities),
                outputs=capabilities_output,
                queue=False,
            )

        with gr.Tab("Knowledge Base"):
            gr.Markdown(
                "Knowledge-base expansion is paused. Existing retrieval remains available through "
                "the `knowledge.answer` capability."
            )

    return demo
