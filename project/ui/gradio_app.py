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


def _shadow_room_preferences(value: str) -> list[dict]:
    preferences = []
    for line_number, raw_line in enumerate((value or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) == 1 and parts[0]:
            preferences.append({"room": parts[0]})
        elif len(parts) == 2 and all(parts):
            preferences.append({"floor": parts[0], "room": parts[1]})
        else:
            raise ValueError(
                f"Room preference line {line_number} must be ROOM or FLOOR | ROOM."
            )
    if not preferences:
        raise ValueError("Enter at least one exact room preference.")
    return preferences


def _shadow_sessions(value: str) -> list[dict]:
    intervals = []
    for part in (value or "").replace("\n", ",").split(","):
        if not part.strip():
            continue
        pair = [item.strip() for item in part.split("-")]
        if len(pair) != 2 or not all(pair):
            raise ValueError("Use full intervals, for example 10:00-11:00, 11:00-12:00.")
        intervals.append({"start_time": pair[0], "end_time": pair[1]})
    if not intervals:
        raise ValueError("Enter at least one exact preferred interval.")
    return intervals


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
            if not date:
                raise ValueError("Read this facility's live Date options, then select a date before searching.")
            return _pretty(await asyncio.to_thread(
                api_client.library_space_availability, facility_type, date
            ))
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def library_dates_handler(facility_type, selected_date):
        try:
            response = await asyncio.to_thread(api_client.library_space_dates, facility_type)
            result = response.get("result") or {}
            dates = result.get("offered_dates", []) if response.get("ok") else []
            selected = selected_date if selected_date in dates else next(iter(dates), None)
            return (
                _pretty(response),
                gr.update(choices=dates, value=selected, interactive=bool(dates)),
                gr.update(interactive=bool(dates)),
            )
        except Exception as exc:
            return (
                _pretty({"ok": False, "read_only": True, "message": str(exc)}),
                gr.update(choices=[], value=None, interactive=False),
                gr.update(interactive=False),
            )

    async def library_booking_preview_handler(
        facility_type, date, floor, room, start_time, end_time, eligibility_category
    ):
        try:
            response = await asyncio.to_thread(
                api_client.library_space_booking_preview,
                facility_type,
                date,
                floor,
                room,
                start_time,
                end_time,
                eligibility_category,
            )
            digest = ((response.get("result") or {}).get("preview_digest")
                      if isinstance(response, dict) else None)
            return _pretty(response), digest or ""
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)}), ""

    def library_booking_draft_handler(
        preview_digest, accept_policy, discussion_room_rules_acknowledged, facility_rules_acknowledged, selected_facility_type
    ):
        try:
            if not preview_digest:
                raise ValueError("Create a fresh exact-slot preview first.")
            if accept_policy is not True:
                raise ValueError("Review the exact target and check the HKUL policy acknowledgment before preparing the action.")
            draft = api_client.action_draft(
                "library.spaces.book",
                {
                    "preview_digest": preview_digest,
                    "policy_acceptance_acknowledged": True,
                    "discussion_room_rules_acknowledged": (
                        True
                        if selected_facility_type == "discussion_room"
                        and discussion_room_rules_acknowledged is True
                        else None
                    ),
                    "facility_rules_acknowledged": (
                        True if selected_facility_type not in {"single_study_room", "discussion_room"}
                        and facility_rules_acknowledged is True else None
                    ),
                },
            )
            facility_type = ((draft.get("preview") or {}).get("exact_target") or {}).get("facility_type", "")
            return _pretty(draft), draft["id"], draft["preview_digest"], "", facility_type
        except Exception as exc:
            return _pretty({"ok": False, "message": str(exc)}), "", "", "", ""

    def library_booking_validate_handler(draft_id, facility_type):
        try:
            if not draft_id:
                raise ValueError("Prepare an action draft first.")
            draft = api_client.action_validate(draft_id)
            verified_facility_type = ((draft.get("preview") or {}).get("exact_target") or {}).get("facility_type", facility_type)
            return _pretty(draft), draft["id"], draft["preview_digest"], "", verified_facility_type
        except Exception as exc:
            return _pretty({"ok": False, "message": str(exc)}), draft_id or "", "", "", facility_type or ""

    def library_booking_confirm_handler(
        draft_id, preview_digest, accept_policy, discussion_rules_ack, facility_rules_ack, facility_type
    ):
        try:
            if not draft_id or not preview_digest:
                raise ValueError("Validate an action draft before confirmation.")
            if accept_policy is not True:
                raise ValueError("The HKUL policy acknowledgment must remain checked at confirmation time.")
            if facility_type == "discussion_room" and discussion_rules_ack is not True:
                raise ValueError("The Discussion Room group-size and daily/interleaving attestation must remain checked at confirmation time.")
            if facility_type not in {"single_study_room", "discussion_room"} and facility_rules_ack is not True:
                raise ValueError("The facility-specific HKUL rules acknowledgment must remain checked at confirmation time.")
            confirmation = api_client.action_confirm(draft_id, preview_digest)
            verified_facility_type = ((confirmation["draft"].get("preview") or {}).get("exact_target") or {}).get("facility_type", facility_type)
            return _pretty(confirmation["draft"]), confirmation["draft"]["id"], confirmation["draft"]["preview_digest"], confirmation["confirmation_token"], verified_facility_type
        except Exception as exc:
            return _pretty({"ok": False, "message": str(exc)}), draft_id or "", preview_digest or "", "", facility_type or ""

    async def library_booking_execute_handler(draft_id, confirmation_token):
        try:
            if not draft_id or not confirmation_token:
                raise ValueError("Confirm the exact action preview before execution.")
            accepted = await asyncio.to_thread(
                api_client.action_execute,
                draft_id,
                confirmation_token,
                "library-f2-gui",
            )
            task_id = accepted["id"]
            latest = None
            for _ in range(210):
                latest = await asyncio.to_thread(api_client.task, task_id)
                if latest.get("status") in {"completed", "failed", "unknown", "cancelled"}:
                    break
                await asyncio.sleep(1)
            status = (latest or {}).get("status")
            note = (
                "If status is unknown, inspect My Booking Record manually and do not retry the booking."
                if status == "unknown"
                else "If the task is still running, refresh Tasks and inspect My Booking Record before taking any further action."
                if status not in {"completed", "failed", "cancelled"}
                else "The one-time confirmation token was discarded after this execution attempt."
            )
            return (
                _pretty({"task_id": task_id, **(latest or {}), "gui_note": note}),
                "",
                "",
                "",
            )
        except Exception as exc:
            return (
                _pretty({"ok": False, "message": str(exc),
                         "gui_note": "If the browser reported a disconnected/unknown result after Submit, inspect My Booking Record and do not retry."}),
                "",
                "",
                "",
            )

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

    def _f4_draft_payload(
        target_date, prepare_at, execution_at, stop_at, room,
        start_time, end_time, eligibility_category,
    ):
        return {
            "facility_type": "discussion_room",
            "target_date": (target_date or "").strip(),
            "prepare_at": (prepare_at or "").strip(),
            "execution_at": (execution_at or "").strip(),
            "stop_at": (stop_at or "").strip(),
            "floor": "Level 3",
            "room": (room or "").strip(),
            "start_time": (start_time or "").strip(),
            "end_time": (end_time or "").strip(),
            "eligibility_category": eligibility_category,
        }

    async def library_autobook_pilot_preview_handler(
        target_date, prepare_at, execution_at, stop_at, room,
        start_time, end_time, eligibility_category,
    ):
        draft = _f4_draft_payload(target_date, prepare_at, execution_at, stop_at, room,
                                  start_time, end_time, eligibility_category)
        try:
            return _pretty(await asyncio.to_thread(api_client.library_autobook_pilot_preview, draft))
        except Exception as exc:
            return _pretty({"ok": False, "read_only": True, "message": str(exc)})

    async def library_autobook_draft_preview_handler(*values):
        try:
            result = await asyncio.to_thread(api_client.library_autobook_draft_preview, _f4_draft_payload(*values))
            return _pretty(result), result.get("preview_digest", "")
        except Exception as exc:
            return _pretty({"ok": False, "booking_authority": False, "message": str(exc)}), ""

    async def library_autobook_draft_create_handler(digest, acknowledged):
        try:
            if not acknowledged:
                raise ValueError("Acknowledge that this saved draft grants no booking authority.")
            return _pretty(await asyncio.to_thread(api_client.library_autobook_draft_create, digest, acknowledged))
        except Exception as exc:
            return _pretty({"ok": False, "booking_authority": False, "message": str(exc)})

    async def library_autobook_drafts_handler():
        try:
            return _pretty(await asyncio.to_thread(api_client.library_autobook_drafts))
        except Exception as exc:
            return _pretty({"ok": False, "booking_authority": False, "message": str(exc)})

    async def library_autobook_draft_revoke_handler(draft_id):
        try:
            return _pretty(await asyncio.to_thread(api_client.library_autobook_draft_revoke, (draft_id or "").strip()))
        except Exception as exc:
            return _pretty({"ok": False, "booking_authority": False, "message": str(exc)})

    async def library_autobook_authorization_preview_handler(*values):
        try:
            result = await asyncio.to_thread(api_client.library_autobook_authorization_preview,
                                             _f4_draft_payload(*values))
            return _pretty(result), result.get("preview_digest", "")
        except Exception as exc:
            return _pretty({"ok": False, "execution_enabled": False, "message": str(exc)}), ""

    async def library_autobook_authorization_create_handler(digest, acknowledged, policy_ack, rules_ack):
        try:
            if not (acknowledged and policy_ack and rules_ack):
                raise ValueError("Review the exact target and acknowledge all three F4 conditions.")
            return _pretty(await asyncio.to_thread(api_client.library_autobook_authorization_create,
                                                   digest, acknowledged, policy_ack, rules_ack))
        except Exception as exc:
            return _pretty({"ok": False, "execution_enabled": False, "message": str(exc)})

    async def library_autobook_authorizations_handler():
        try:
            return _pretty(await asyncio.to_thread(api_client.library_autobook_authorizations))
        except Exception as exc:
            return _pretty({"ok": False, "execution_enabled": False, "message": str(exc)})

    async def library_autobook_authorization_action_handler(authorization_id, action):
        try:
            return _pretty(await asyncio.to_thread(api_client.library_autobook_authorization_action,
                                                   (authorization_id or "").strip(), action))
        except Exception as exc:
            return _pretty({"ok": False, "execution_enabled": False, "message": str(exc)})

    async def library_shadow_status_handler():
        try:
            status, rules, runs = await asyncio.gather(
                asyncio.to_thread(api_client.library_shadow_status),
                asyncio.to_thread(api_client.library_shadow_rules),
                asyncio.to_thread(api_client.library_shadow_runs),
            )
            return _pretty(status), _pretty(rules), _pretty(runs)
        except Exception as exc:
            error = _pretty({"ok": False, "mode": "shadow_only", "message": str(exc)})
            return error, error, error

    async def library_shadow_preview_handler(
        facility_type,
        target_date,
        execution_at,
        room_preferences,
        start_time_preferences,
        allow_room_fallback,
        allow_time_fallback,
        eligibility_category,
        prepare_at="",
        stop_at="",
        poll_interval_seconds=15,
        max_date_checks=1,
    ):
        try:
            rule = {
                "facility_type": facility_type,
                "target_date": (target_date or "").strip(),
                "execution_at": (execution_at or "").strip(),
                "prepare_at": (prepare_at or "").strip() or None,
                "stop_at": (stop_at or "").strip() or None,
                "poll_interval_seconds": int(poll_interval_seconds),
                "max_date_checks": int(max_date_checks),
                "room_preference_order": _shadow_room_preferences(room_preferences),
                "session_preference_order": _shadow_sessions(start_time_preferences),
                "allow_room_fallback": bool(allow_room_fallback),
                "allow_time_fallback": bool(allow_time_fallback),
                "eligibility_category": eligibility_category,
                "max_runs": 1,
                "shadow_only": True,
            }
            result = await asyncio.to_thread(api_client.library_shadow_rule_preview, rule)
            return _pretty(result), result.get("rule_preview_digest", ""), False
        except Exception as exc:
            return _pretty({"ok": False, "shadow_only": True, "message": str(exc)}), "", False

    async def library_shadow_create_handler(preview_digest, acknowledged):
        if preview_digest and acknowledged is not True:
            gr.Warning("Check the shadow-only acknowledgment, then click Create again. Your preview is retained.")
            return gr.skip(), preview_digest, False
        try:
            if not preview_digest:
                raise ValueError("Create and review a fresh F3 rule preview first.")
            if acknowledged is not True:
                raise ValueError("Confirm that this is a one-time read-only task with no booking authority.")
            result = await asyncio.to_thread(
                api_client.library_shadow_rule_create, preview_digest, True
            )
            return _pretty(result), "", False
        except Exception as exc:
            return _pretty({"ok": False, "shadow_only": True, "message": str(exc), "recovery": "Review the error, make any needed rule change, then create a fresh preview."}), "", False

    async def library_shadow_rule_action_handler(rule_id, action, revoke_acknowledged):
        try:
            if not rule_id:
                raise ValueError("Enter a rule ID from the current F3 rules list.")
            if action == "revoke" and revoke_acknowledged is not True:
                raise ValueError("Check the permanent-revocation acknowledgment before revoking a rule.")
            result = await asyncio.to_thread(
                api_client.library_shadow_rule_action,
                rule_id.strip(), action, action == "revoke" and revoke_acknowledged is True,
            )
            rules = await asyncio.to_thread(api_client.library_shadow_rules)
            return _pretty(result), _pretty(rules), False
        except Exception as exc:
            return _pretty({"ok": False, "shadow_only": True, "message": str(exc)}), _pretty({"ok": False, "message": str(exc)}), False

    async def library_shadow_refresh_runs_handler(rule_id):
        try:
            result = await asyncio.to_thread(
                api_client.library_shadow_runs, (rule_id or "").strip() or None
            )
            return _pretty(result)
        except Exception as exc:
            return _pretty({"ok": False, "shadow_only": True, "message": str(exc)})

    async def library_shadow_feedback_handler(run_id, candidate_id, no_slot_would_be_booked):
        try:
            if not run_id:
                raise ValueError("Enter a completed run ID from the F3 run history.")
            result = await asyncio.to_thread(
                api_client.library_shadow_run_feedback,
                run_id.strip(),
                (candidate_id or "").strip() or None,
                bool(no_slot_would_be_booked),
            )
            return _pretty(result)
        except Exception as exc:
            return _pretty({"ok": False, "shadow_only": True, "message": str(exc)})

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
                "## HKU Libraries\n"
                "Research search opens only the fixed Find@HKUL route and reads visible "
                "bibliographic results. It does not open licensed full text or save/request "
                "items. Use the sub-tabs for space availability, an exact read-only preview, "
                "supervised one-shot F2 booking, read-only F3 scheduling, and the F4 design preview. "
                "F2 requires its separate local write gate; the F4 preview grants no booking authority."
            )
            with gr.Tabs():
                with gr.Tab("Research & hours"):
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
                with gr.Tab("Space availability"):
                    library_space_output = gr.Code(value="Read live Date options, then search.", language="json", label="Availability result")
                    gr.Markdown(
                        "### Book a Space availability\n"
                        "List the supported facilities and verified policy summary locally before "
                        "opening an authenticated availability page."
                    )
                    library_facilities_button = gr.Button("List supported facilities and policies")
                    library_facilities_button.click(
                        library_facilities_handler,
                        outputs=library_space_output,
                        show_progress="minimal",
                        queue=False,
                    )
                    gr.Markdown(
                        "Availability covers the Main Library facility types shown below plus the "
                        "verified Chi Wah Study Room route. This is read-only: it does not select "
                        "a slot. Read the live Date options for the selected facility before searching. "
                        "The first run can open HKUL authentication; "
                        "complete it manually in Chrome and retry."
                    )
                    library_facility = gr.Dropdown(
                        choices=[
                            ("Single Study Room (3 sessions) — Main Library", "single_study_room"),
                            ("AV Group Viewing Room — Main Library", "av_group_viewing_room"),
                            ("Communal Virtual PC — Main Library", "communal_virtual_pc"),
                            ("Computer — Main Library", "computer"),
                            ("Computer in LIC — Main Library", "computer_in_lic"),
                            ("Engraving/cutting computer — Main Library", "engraving_cutting_computer"),
                            ("Concept and Creation Room — Main Library", "concept_and_creation_room"),
                            ("Discussion Room — Main Library", "discussion_room"),
                            ("Microform Scanner — Special Collections", "microform_scanner"),
                            ("Overhead Scanner — Special Collections", "overhead_scanner"),
                            ("Research Desk — Special Collections", "research_desk"),
                            ("Studio and Editing Room — Main Library", "studio_editing_room"),
                            ("Study Table — Main Library", "study_table"),
                            ("Study Table (Deep Quiet) — Main Library", "study_table_deep_quiet"),
                            ("Study Room — Chi Wah Learning Commons", "study_room"),
                        ],
                        value="single_study_room",
                        label="Facility type",
                    )
                    library_dates_button = gr.Button("1. Read this facility's live Date options")
                    library_availability_date = gr.Dropdown(
                        choices=[], value=None, interactive=False,
                        label="2. Select an offered date (YYYY-MM-DD)",
                        info="Reading dates fills this list and selects the first option. Choose your date, then click Search below.",
                    )
                    library_space_button = gr.Button("3. Search availability for selected date", interactive=False)
                    library_dates_button.click(
                        library_dates_handler, inputs=[library_facility, library_availability_date],
                        outputs=[library_space_output, library_availability_date, library_space_button],
                        show_progress="minimal", queue=False,
                    )
                    library_facility.input(
                        lambda: (
                            gr.update(choices=[], value=None, interactive=False),
                            gr.update(interactive=False),
                        ),
                        outputs=[library_availability_date, library_space_button], queue=False,
                    )
                    library_space_button.click(
                        library_space_handler,
                        inputs=[library_facility, library_availability_date],
                        outputs=library_space_output,
                        show_progress="minimal",
                        queue=False,
                    )
                with gr.Tab("Exact preview"):
                    library_preview_output = gr.Code(value="Copy an exact slot from availability.", language="json", label="Exact booking preview")
                    gr.Markdown(
                        "### Exact booking preview (Phase F1, read-only)\n"
                        "All 15 availability-supported facility types can be previewed. Each preview re-reads "
                        "the exact live date and slot. Some facility-specific rules are not account-verified; "
                        "review the linked HKUL policy and live form before a real booking.\n"
                        "Copy one exact slot from the availability result. The preview re-reads the "
                        "live page, checks the displayed date and published eligibility category, "
                        "and expires quickly. Date is intentionally not defaulted: copy the returned "
                        "`date` value exactly. It does not click a slot or authorize a reservation."
                    )
                    library_preview_facility = gr.Dropdown(
                        choices=["single_study_room", "av_group_viewing_room", "communal_virtual_pc", "computer", "computer_in_lic", "engraving_cutting_computer", "concept_and_creation_room", "discussion_room", "microform_scanner", "overhead_scanner", "research_desk", "studio_editing_room", "study_table", "study_table_deep_quiet", "study_room"],
                        value="single_study_room",
                        label="Preview-enabled facility type",
                    )
                    with gr.Row():
                        library_preview_date = gr.Textbox(value="", label="Date (YYYY-MM-DD)")
                        library_preview_floor = gr.Textbox(value="", label="Floor (optional)")
                        library_preview_room = gr.Textbox(value="", label="Exact room")
                    with gr.Row():
                        library_preview_start = gr.Textbox(value="", label="Start (HH:MM)")
                        library_preview_end = gr.Textbox(value="", label="End (HH:MM)")
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
                    library_preview_digest = gr.State("")
                    library_preview_button.click(
                        library_booking_preview_handler,
                        inputs=[
                            library_preview_facility,
                            library_preview_date,
                            library_preview_floor,
                            library_preview_room,
                            library_preview_start,
                            library_preview_end,
                            library_preview_eligibility,
                        ],
                        outputs=[library_preview_output, library_preview_digest],
                        show_progress="minimal",
                        queue=False,
                    )
                with gr.Tab("Supervised booking (F2)"):
                    gr.Markdown(
                        "### F2 — supervised one-shot booking\n"
                        "F2 allows a supervised one-shot attempt for the 15 listed facility types. "
                        "No live write is guaranteed: missing facility rules, stale slots, extra required form fields, or an unverifiable result stop submission. "
                        "For a discussion room, the extra attestation below is mandatory: you must confirm "
                        "at least two patrons, no more than two sessions/120 minutes for that day, "
                        "and compliance with the interleaving rule. HKUL account bookings and group size "
                        "are not independently verified by this tool. "
                        "The action re-reads the exact slot, selects only that slot, checks every "
                        "booking-form field, and verifies one matching My Booking Record row. It will "
                        "never retry an ambiguous Submit. Preparation, validation, and confirmation "
                        "do not submit. The final Execute button sends the single external request. "
                        "Keep `LIBRARY_BOOKING_WRITES_ENABLED=false` for dry tests; only enable it "
                        "temporarily for an explicitly approved low-impact live test."
                    )
                    library_policy_ack = gr.Checkbox(
                        value=False,
                            label="I reviewed the exact target in the Exact preview tab and accept the displayed HKUL booking policy for this one reservation.",
                    )
                    library_discussion_rules_ack = gr.Checkbox(
                        value=False,
                        label=(
                            "Discussion rooms only: I confirm at least two patrons will use the room, "
                            "and my bookings for that day will comply with the two-session/120-minute limit "
                            "and the interleaving rule."
                        ),
                    )
                    library_facility_rules_ack = gr.Checkbox(
                        value=False,
                        label="Other facilities: I reviewed the specific HKUL rules, including group size, daily limits and special-use restrictions where applicable, for this exact type and date.",
                    )
                    library_f2_output = gr.Code(
                        value="No booking action draft prepared.", language="json", label="F2 action review / outcome"
                    )
                    library_f2_draft_id = gr.State("")
                    library_f2_preview_digest = gr.State("")
                    library_f2_confirmation_token = gr.State("")
                    library_f2_facility_type = gr.State("")
                    library_f2_prepare_button = gr.Button("1. Prepare one-shot action (no booking yet)")
                    library_f2_prepare_button.click(
                        library_booking_draft_handler,
                        inputs=[library_preview_digest, library_policy_ack, library_discussion_rules_ack, library_facility_rules_ack, library_preview_facility],
                        outputs=[library_f2_output, library_f2_draft_id, library_f2_preview_digest, library_f2_confirmation_token, library_f2_facility_type],
                        show_progress="minimal",
                        queue=False,
                    )
                    library_f2_validate_button = gr.Button("2. Revalidate action preview")
                    library_f2_validate_button.click(
                        library_booking_validate_handler,
                        inputs=[library_f2_draft_id, library_f2_facility_type],
                        outputs=[library_f2_output, library_f2_draft_id, library_f2_preview_digest, library_f2_confirmation_token, library_f2_facility_type],
                        show_progress="minimal",
                        queue=False,
                    )
                    library_f2_confirm_button = gr.Button("3. Confirm exact reservation")
                    library_f2_confirm_button.click(
                        library_booking_confirm_handler,
                        inputs=[library_f2_draft_id, library_f2_preview_digest, library_policy_ack, library_discussion_rules_ack, library_facility_rules_ack, library_f2_facility_type],
                        outputs=[library_f2_output, library_f2_draft_id, library_f2_preview_digest, library_f2_confirmation_token, library_f2_facility_type],
                        show_progress="minimal",
                        queue=False,
                    )
                    library_f2_execute_button = gr.Button("4. Execute exactly once", variant="stop")
                    library_f2_execute_button.click(
                        library_booking_execute_handler,
                        inputs=[library_f2_draft_id, library_f2_confirmation_token],
                        outputs=[library_f2_output, library_f2_draft_id, library_f2_preview_digest, library_f2_confirmation_token],
                        show_progress="full",
                        queue=False,
                    )

                with gr.Tab("Scheduled read-only checks (F3)"):
                    gr.Markdown(
                        "### F3 — exact-date shadow scheduler (read-only; no booking authority)\n"
                        "F3 stores a one-time task, can prepare its facility page in advance, then performs bounded live Date checks from the specified start time. "
                        "It makes at most one read-only F1 availability Search for your exact target date. It ranks exact rooms/intervals from "
                        "your ordered preferences, records the suggestion, and waits for your later feedback. It never "
                        "selects a slot, opens a booking form, calls F2, or submits/cancels a booking. The run time is "
                        "an observation time—not an assumed HKUL release time. Rules and run details are protected with "
                        "Windows current-user DPAPI; at most five rules can be active at once. F3 is unavailable if that "
                        "protection or loopback-only hosting is unavailable."
                    )
                    library_shadow_status_button = gr.Button("Refresh F3 status, rules, and run history")
                    with gr.Row():
                        library_shadow_status_output = gr.Code(
                            value="F3 scheduler status not loaded.", language="json", label="F3 status"
                        )
                        library_shadow_rules_output = gr.Code(
                            value="No rules loaded.", language="json", label="F3 rules"
                        )
                    library_shadow_runs_output = gr.Code(
                        value="No runs loaded.", language="json", label="F3 shadow runs / agreement"
                    )
                    library_shadow_status_button.click(
                        library_shadow_status_handler,
                        outputs=[library_shadow_status_output, library_shadow_rules_output, library_shadow_runs_output],
                        show_progress="minimal",
                        queue=False,
                    )
                    gr.Markdown(
                        "#### Prepare and wait for an exact-date observation (F3.2b)\n"
                        "Set the full execution date/time in Hong Kong time and the exact facility-use date. "
                        "Each task runs once and checks that date against the facility's live options; it never substitutes another date. "
                        "Preparation opens the facility page; complete any login manually. Date checks start only at the checking time. "
                        "Checks stop at the deadline or attempt limit. At most one availability Search is performed, with no booking. "
                        "Room lines use `FLOOR | exact room` (or just an exact room). Preferred intervals are comma-separated "
                        "`HH:MM-HH:MM` values. If fallback is off, only the first room and first interval are eligible. "
                        "No task can be created until you review its preview and acknowledge that it creates a one-time "
                        "read-only rule—not permission to book."
                    )
                    library_shadow_facility = gr.Dropdown(
                        choices=[
                            ("Single Study Room (3 sessions) — Main Library", "single_study_room"),
                            ("Studio and Editing Room — Main Library", "studio_editing_room"),
                            ("Study Table — Main Library", "study_table"),
                            ("Study Room — Chi Wah Learning Commons", "study_room"),
                            ("Discussion Room — Main Library", "discussion_room"),
                        ],
                        value="single_study_room",
                        label="F3 facility type (F1 preview-supported only)",
                    )
                    library_shadow_target_date = gr.Textbox(
                        value="", label="Facility-use date (YYYY-MM-DD, Hong Kong)",
                    )
                    with gr.Row():
                        library_shadow_run_time = gr.Textbox(
                            value="", label="Start Date checks at (YYYY-MM-DD HH:MM:SS, Hong Kong)",
                            placeholder="2026-09-29 00:00:00",
                        )
                        library_shadow_eligibility = gr.Dropdown(
                            choices=[
                                "current_hku_students", "current_hku_staff",
                                "current_hku_space_students", "current_hku_space_staff", "hku_alumni",
                            ],
                            value="current_hku_students",
                            label="Self-declared eligibility category",
                        )
                    with gr.Row():
                        library_shadow_prepare = gr.Textbox(
                            value="", label="Prepare at (Hong Kong; blank = checking start)",
                            placeholder="2026-09-28 23:59:00",
                        )
                        library_shadow_stop = gr.Textbox(
                            value="", label="Stop at (Hong Kong; blank = start + 2 minutes)",
                            placeholder="2026-09-29 00:02:00",
                        )
                    with gr.Row():
                        library_shadow_poll = gr.Number(value=15, minimum=15, maximum=120, precision=0,
                                                        label="Seconds between completed Date checks (15–120)")
                        library_shadow_attempts = gr.Number(value=8, minimum=1, maximum=20, precision=0,
                                                            label="Maximum Date checks after start (1–20)")
                    library_shadow_rooms = gr.Textbox(
                        value="",
                        lines=4,
                        placeholder="4/F | Single Study Room (3 sessions) Room 424\n4/F | Single Study Room (3 sessions) Room 428",
                        label="Exact room preference order (one per line)",
                    )
                    library_shadow_times = gr.Textbox(
                        value="",
                        placeholder="10:00-11:00, 11:00-12:00",
                        label="Preferred exact intervals (HH:MM-HH:MM, in preference order)",
                    )
                    with gr.Row():
                        library_shadow_room_fallback = gr.Checkbox(
                            value=False, label="Allow lower-ranked room preferences if the first is unavailable"
                        )
                        library_shadow_time_fallback = gr.Checkbox(
                            value=False, label="Allow lower-ranked intervals if the first is unavailable"
                        )
                    library_shadow_preview_button = gr.Button("1. Preview exact-date shadow task")
                    library_shadow_preview_output = gr.Code(
                        value="No F3 rule preview prepared.", language="json", label="F3 rule preview"
                    )
                    library_shadow_preview_digest = gr.Textbox(
                        value="", interactive=False,
                        label="F3 preview reference (filled after a successful preview)",
                    )
                    library_shadow_create_ack = gr.Checkbox(
                        value=False,
                        label="I reviewed preparation, checking start, stop time, check limits, target date and intervals. This task is read-only; it cannot book, select a slot, or call F2.",
                    )
                    library_shadow_create_button = gr.Button("2. Confirm and create shadow-only rule")
                    library_shadow_preview_button.click(
                        library_shadow_preview_handler,
                        inputs=[
                            library_shadow_facility, library_shadow_target_date, library_shadow_run_time,
                            library_shadow_rooms, library_shadow_times, library_shadow_room_fallback,
                            library_shadow_time_fallback, library_shadow_eligibility,
                            library_shadow_prepare, library_shadow_stop, library_shadow_poll, library_shadow_attempts,
                        ],
                        outputs=[library_shadow_preview_output, library_shadow_preview_digest, library_shadow_create_ack],
                        show_progress="minimal",
                        queue=False,
                    )
                    library_shadow_create_button.click(
                        library_shadow_create_handler,
                        inputs=[library_shadow_preview_digest, library_shadow_create_ack],
                        outputs=[library_shadow_preview_output, library_shadow_preview_digest, library_shadow_create_ack],
                        show_progress="minimal",
                        queue=False,
                    )
                    gr.Markdown(
                        "#### Pause or permanently revoke a rule\n"
                        "Use the rule ID shown above. Revocation is terminal and cannot be undone; it prevents future scheduled reads."
                    )
                    with gr.Row():
                        library_shadow_rule_id = gr.Textbox(value="", label="F3 rule ID")
                        library_shadow_rule_action = gr.Dropdown(
                            choices=[("Pause", "pause"), ("Resume paused rule", "resume"), ("Revoke permanently", "revoke")],
                            value="pause",
                            label="Rule action",
                        )
                    library_shadow_revoke_ack = gr.Checkbox(
                        value=False, label="I understand revoke is permanent and ends future scheduled checks."
                    )
                    library_shadow_action_button = gr.Button("Apply rule action")
                    library_shadow_action_output = gr.Code(
                        value="No F3 rule action performed.", language="json", label="F3 rule action result"
                    )
                    library_shadow_action_button.click(
                        library_shadow_rule_action_handler,
                        inputs=[library_shadow_rule_id, library_shadow_rule_action, library_shadow_revoke_ack],
                        outputs=[library_shadow_action_output, library_shadow_rules_output, library_shadow_revoke_ack],
                        show_progress="minimal",
                        queue=False,
                    )
                    gr.Markdown(
                        "#### Compare suggestions with your actual choice\n"
                        "After a run, refresh history, then record either one candidate ID or that you would book none. "
                        "Feedback is immutable and updates the exact-choice agreement summary."
                    )
                    with gr.Row():
                        library_shadow_runs_rule_filter = gr.Textbox(value="", label="Rule ID filter (optional)")
                        library_shadow_runs_refresh_button = gr.Button("Refresh shadow runs")
                    library_shadow_filtered_runs_output = gr.Code(
                        value="Click Refresh shadow runs to load results for the rule ID above.",
                        language="json", label="Refreshed shadow runs / agreement",
                    )
                    library_shadow_runs_refresh_button.click(
                        library_shadow_refresh_runs_handler,
                        inputs=library_shadow_runs_rule_filter,
                        outputs=library_shadow_filtered_runs_output,
                        show_progress="minimal",
                        queue=False,
                    )
                    with gr.Row():
                        library_shadow_feedback_run_id = gr.Textbox(value="", label="Completed run ID")
                        library_shadow_feedback_candidate_id = gr.Textbox(value="", label="Candidate ID (leave blank if choosing none)")
                    library_shadow_feedback_none = gr.Checkbox(
                        value=False, label="I would book none of the candidates (or there were no matching slots)."
                    )
                    library_shadow_feedback_button = gr.Button("Record my comparison")
                    library_shadow_feedback_output = gr.Code(
                        value="No human comparison recorded.", language="json", label="F3 comparison result"
                    )
                    library_shadow_feedback_button.click(
                        library_shadow_feedback_handler,
                        inputs=[library_shadow_feedback_run_id, library_shadow_feedback_candidate_id, library_shadow_feedback_none],
                        outputs=library_shadow_feedback_output,
                        show_progress="minimal",
                        queue=False,
                    )

                with gr.Tab("Scheduled booking (F4)"):
                    gr.Markdown(
                        "### F4 pilot design preview — no authorization yet\n"
                        "Review one exact Main Library Discussion Room target and the blockers before "
                        "any delegated-booking feature is enabled. This preview is local and read-only: "
                        "it does not check availability, create a rule, grant standing authority, "
                        "or book a room. The supervised F2 flow remains in its own tab."
                    )
                    f4_target_date = gr.Textbox(label="Exact facility-use date (YYYY-MM-DD)")
                    with gr.Row():
                        f4_prepare = gr.Textbox(label="Prepare at (Hong Kong YYYY-MM-DD HH:MM:SS)")
                        f4_check = gr.Textbox(label="Start Date checks at (Hong Kong YYYY-MM-DD HH:MM:SS)")
                        f4_stop = gr.Textbox(label="Stop at (Hong Kong YYYY-MM-DD HH:MM:SS)")
                    with gr.Row():
                        f4_room = gr.Textbox(label="Exact Level 3 Discussion Room", placeholder="Discussion Room 2")
                        f4_start = gr.Textbox(label="Start (HH:MM)")
                        f4_end = gr.Textbox(label="End (HH:MM)")
                    f4_eligibility = gr.Dropdown(
                        choices=["current_hku_students", "current_hku_staff",
                                 "current_hku_space_students", "current_hku_space_staff"],
                        value="current_hku_students", label="Self-declared eligibility category",
                    )
                    f4_preview_button = gr.Button("Preview F4 pilot scope and unmet gates")
                    f4_preview_output = gr.Code(
                        value="No F4 design preview prepared. Unattended booking is disabled.",
                        language="json", label="F4 design review (no authorization)",
                    )
                    f4_preview_button.click(
                        library_autobook_pilot_preview_handler,
                        inputs=[f4_target_date, f4_prepare, f4_check, f4_stop,
                                f4_room, f4_start, f4_end, f4_eligibility],
                        outputs=f4_preview_output, show_progress="minimal", queue=False,
                    )
                    gr.Markdown(
                        "### Save an inert F4 draft\n"
                        "This is a local planning record only. Saving it does **not** schedule checks, "
                        "authorize a future booking, or enable Submit. A future live F4 feature would require "
                        "a fresh, separate authorization after the remaining gates are satisfied."
                    )
                    f4_draft_preview_button = gr.Button("1. Preview non-authorizing draft")
                    f4_draft_preview_output = gr.Code(language="json", label="F4 draft preview")
                    f4_draft_digest = gr.Textbox(label="One-time draft preview digest", interactive=False)
                    f4_draft_preview_button.click(
                        library_autobook_draft_preview_handler,
                        inputs=[f4_target_date, f4_prepare, f4_check, f4_stop,
                                f4_room, f4_start, f4_end, f4_eligibility],
                        outputs=[f4_draft_preview_output, f4_draft_digest],
                        show_progress="minimal", queue=False,
                    )
                    f4_draft_ack = gr.Checkbox(
                        label="I understand this saved draft grants no booking authority and performs no booking."
                    )
                    f4_draft_save = gr.Button("2. Save inert draft")
                    f4_draft_save_output = gr.Code(language="json", label="Saved draft result")
                    f4_draft_save.click(
                        library_autobook_draft_create_handler,
                        inputs=[f4_draft_digest, f4_draft_ack], outputs=f4_draft_save_output,
                        show_progress="minimal", queue=False,
                    )
                    f4_drafts_button = gr.Button("List F4 drafts")
                    f4_drafts_output = gr.Code(language="json", label="Inert F4 drafts")
                    f4_drafts_button.click(library_autobook_drafts_handler, outputs=f4_drafts_output,
                                           show_progress="minimal", queue=False)
                    f4_revoke_id = gr.Textbox(label="Draft ID to revoke")
                    f4_revoke_button = gr.Button("Revoke inert draft")
                    f4_revoke_output = gr.Code(language="json", label="Revocation result")
                    f4_revoke_button.click(library_autobook_draft_revoke_handler,
                                           inputs=f4_revoke_id, outputs=f4_revoke_output,
                                           show_progress="minimal", queue=False)
                    gr.Markdown(
                        "### One-time F4 authorization (executor not connected)\n"
                        "This records consent for one exact future booking attempt, but **will not run** "
                        "until a separately tested F4 executor is enabled. It cannot use F2's confirmation "
                        "token or turn an F3 rule into a booking. Review the target and date carefully."
                    )
                    f4_auth_preview_button = gr.Button("1. Preview exact F4 authorization")
                    f4_auth_preview_output = gr.Code(language="json", label="F4 authorization review")
                    f4_auth_digest = gr.Textbox(label="One-time authorization preview digest", interactive=False)
                    f4_auth_preview_button.click(
                        library_autobook_authorization_preview_handler,
                        inputs=[f4_target_date, f4_prepare, f4_check, f4_stop,
                                f4_room, f4_start, f4_end, f4_eligibility],
                        outputs=[f4_auth_preview_output, f4_auth_digest],
                        show_progress="minimal", queue=False,
                    )
                    f4_auth_ack = gr.Checkbox(label="I authorize one future booking attempt for exactly the reviewed target.")
                    f4_policy_ack = gr.Checkbox(label="I accept the applicable HKUL booking policy for this target.")
                    f4_rules_ack = gr.Checkbox(
                        label="At least two patrons will use this Discussion Room; I will comply with the daily session and interleaving rules."
                    )
                    f4_auth_create_button = gr.Button("2. Record one-time authorization (no execution yet)")
                    f4_auth_create_output = gr.Code(language="json", label="F4 authorization result")
                    f4_auth_create_button.click(
                        library_autobook_authorization_create_handler,
                        inputs=[f4_auth_digest, f4_auth_ack, f4_policy_ack, f4_rules_ack],
                        outputs=f4_auth_create_output, show_progress="minimal", queue=False,
                    )
                    f4_auth_list_button = gr.Button("List F4 authorizations")
                    f4_auth_list_output = gr.Code(language="json", label="F4 authorizations")
                    f4_auth_list_button.click(library_autobook_authorizations_handler,
                                              outputs=f4_auth_list_output, show_progress="minimal", queue=False)
                    f4_auth_id = gr.Textbox(label="Authorization ID to pause or revoke")
                    f4_auth_action = gr.Dropdown(choices=["pause", "revoke"], value="revoke", label="Action")
                    f4_auth_action_button = gr.Button("Apply F4 authorization action")
                    f4_auth_action_output = gr.Code(language="json", label="Authorization action result")
                    f4_auth_action_button.click(library_autobook_authorization_action_handler,
                                                inputs=[f4_auth_id, f4_auth_action],
                                                outputs=f4_auth_action_output,
                                                show_progress="minimal", queue=False)

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
                "## Pair the restricted browser extension\n"
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
