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
                lambda: safe_call(api_client.integration_status),
                outputs=connections_output,
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
