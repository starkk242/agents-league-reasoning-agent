"""
EngagementAgent
Monitors learner progress, sends adaptive reminders, and escalates to manager
when learners are stuck or have failed assessments repeatedly.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from agents.base_agent import BaseAgent
from tools.work_iq_signals import WorkIQSignals


class EngagementAgent(BaseAgent):
    AGENT_NAME = "EngagementAgent"

    _INSTRUCTIONS = """You are an adaptive engagement coach for enterprise learning programs.

Your job:
1. Monitor learner progress data and Work IQ signals
2. Generate personalized reminder messages timed to the learner's preferred learning slot
3. Escalate to the manager when a learner is at risk (no activity > 7 days, or 2+ failed assessments)
4. Adjust reminder tone: encouraging for on-track learners, urgent for at-risk learners
5. Never send reminders during identified high-meeting periods

Rules:
- Reference the learner's actual progress percentage and last activity date
- Mention specific next study sessions from their plan
- Escalation messages must be professional and constructive
- Always offer a path forward, never just criticism"""

    # Escalation threshold: 2 or more failed assessments below pass threshold
    _FAIL_THRESHOLD = 70
    _ESCALATION_FAIL_COUNT = 2

    def __init__(self) -> None:
        super().__init__()
        self._work_iq = WorkIQSignals()

    def run(
        self,
        employee_id: str,
        certification_goal: str,
        completion_percentage: float,
        last_activity_date: str,
        assessment_scores: list[float] | None = None,
        study_plan_week: int = 1,
        failed_assessment_count: int = 0,
    ) -> dict[str, Any]:
        """Generate engagement actions (reminders, escalations) for a learner."""
        assessment_scores = assessment_scores or []

        self._validate_input({
            "employee_id": employee_id,
            "certification_goal": certification_goal,
        })

        record = self._start_record(f"{employee_id} → {certification_goal}")

        try:
            # Step 1: Fetch Work IQ signals
            self._log_step(record, "Loading Work IQ signals to personalize engagement timing")
            signals = self._work_iq.get_signals(employee_id)
            reminder_schedule = self._work_iq.get_reminder_schedule(employee_id)

            # Step 2: Compute staleness
            self._log_step(record, "Computing days since last activity")
            days_inactive = self._days_since(last_activity_date)

            # Step 3: Determine learner status
            self._log_step(record, "Evaluating learner status and risk level")
            status = self._assess_status(
                completion_percentage, days_inactive, assessment_scores, failed_assessment_count
            )

            # Step 4: Decide action
            self._log_step(record, f"Deciding engagement action for status: {status['category']}")
            escalate_to_manager = (
                failed_assessment_count >= self._ESCALATION_FAIL_COUNT
                or (days_inactive >= 14 and completion_percentage < 50)
            )

            # Step 5: Generate messages
            self._log_step(record, "Generating personalized reminder and/or escalation message")
            reminder = self._generate_reminder(
                signals, certification_goal, completion_percentage,
                days_inactive, status, study_plan_week, reminder_schedule,
            )

            escalation_msg = None
            if escalate_to_manager:
                self._log_step(record, "ESCALATION triggered — generating manager notification")
                escalation_msg = self._generate_escalation(
                    signals, certification_goal, completion_percentage,
                    days_inactive, failed_assessment_count, assessment_scores,
                )

            result = {
                "agent": self.AGENT_NAME,
                "employee_id": employee_id,
                "employee_name": signals["name"],
                "certification_goal": certification_goal,
                "status": status,
                "days_inactive": days_inactive,
                "completion_percentage": completion_percentage,
                "work_iq_reminder_schedule": reminder_schedule,
                "reminder_message": reminder,
                "escalation_to_manager": escalation_msg,
                "escalation_triggered": escalate_to_manager,
                "next_reminder_days": reminder_schedule["reminder_days"],
                "next_reminder_time": reminder_schedule["reminder_time"],
            }
            result["reminder_message"] = self._apply_guardrails(result["reminder_message"])

            # Live mode: call GPT-4o for a more personalized, contextual reminder
            if not self._demo_mode:
                self._log_step(record, "Calling GPT-4o to generate personalized engagement message")
                result, tokens = self._enhance_reminder_live(result, signals, reminder_schedule)
                record.finish(token_count=tokens, success=True)
            else:
                record.finish(token_count=len(json.dumps(result)) // 4, success=True)

        except Exception as exc:
            record.finish(success=False)
            raise RuntimeError(f"[{self.AGENT_NAME}] Failed: {exc}") from exc
        finally:
            self._emit_telemetry(record)

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _days_since(self, date_str: str) -> int:
        try:
            last = datetime.fromisoformat(date_str).date()
            return (date.today() - last).days
        except (ValueError, TypeError):
            return 0

    def _assess_status(
        self,
        completion_pct: float,
        days_inactive: int,
        scores: list[float],
        fail_count: int,
    ) -> dict:
        avg_score = sum(scores) / len(scores) if scores else None
        recent_fail = fail_count >= self._ESCALATION_FAIL_COUNT

        if completion_pct >= 85:
            category = "exam_ready"
            message = "Nearly complete — book your exam!"
        elif recent_fail:
            category = "assessment_struggling"
            message = f"Struggling with assessments — avg score: {avg_score:.0f}%"
        elif days_inactive >= 14:
            category = "disengaged"
            message = f"No activity in {days_inactive} days"
        elif days_inactive >= 7:
            category = "at_risk"
            message = f"Inactive for {days_inactive} days — needs nudge"
        elif completion_pct >= 60:
            category = "on_track"
            message = "Good progress — keep the momentum"
        else:
            category = "early_stage"
            message = "In early stages — build the habit"

        return {
            "category": category,
            "message": message,
            "average_assessment_score": round(avg_score, 1) if avg_score else None,
            "days_inactive": days_inactive,
            "completion_percentage": completion_pct,
        }

    def _generate_reminder(
        self, signals, cert_goal, completion_pct,
        days_inactive, status, week_num, reminder_schedule,
    ) -> str:
        name = signals["name"]
        slot = signals["preferred_learning_slot"]
        slot_time = reminder_schedule["reminder_time"]
        category = status["category"]

        if category == "exam_ready":
            tone = f"Hi {name}! You're at {completion_pct:.0f}% — you're ready to book your {cert_goal} exam! 🎯"
        elif category in ("disengaged", "at_risk"):
            tone = (
                f"Hi {name}, we noticed you haven't studied {cert_goal} in {days_inactive} days. "
                f"You're {completion_pct:.0f}% done — don't let that hard work go to waste! "
                f"Even 30 minutes during your {slot} slot ({slot_time}) will keep you on track."
            )
        elif category == "assessment_struggling":
            tone = (
                f"Hi {name}, the practice assessments for {cert_goal} show some areas to strengthen. "
                f"Let's revisit the topics where you scored below 70%. "
                f"Schedule a focused review session during your {slot} slot ({slot_time})."
            )
        else:
            tone = (
                f"Hi {name}! Great progress on {cert_goal} — you're {completion_pct:.0f}% done! "
                f"You're in Week {week_num} of your study plan. "
                f"Your next {slot} slot session is scheduled for {slot_time} "
                f"on {reminder_schedule['reminder_days'][0]}."
            )

        tone += (
            f"\n\nWork IQ context: You have {signals['focus_hours_per_week']}h/week of focus time "
            f"and {signals['meeting_hours_per_week']}h in meetings. "
            f"Study session length: {reminder_schedule['study_session_length_minutes']} minutes."
        )
        return tone

    def _generate_escalation(
        self, signals, cert_goal, completion_pct,
        days_inactive, fail_count, scores,
    ) -> str:
        avg_score = sum(scores) / len(scores) if scores else 0
        return (
            f"**Manager Escalation — {signals['name']} ({signals['role']})**\n\n"
            f"Certification: {cert_goal}\n"
            f"Current progress: {completion_pct:.0f}%\n"
            f"Days since last activity: {days_inactive}\n"
            f"Failed assessments (below 70%): {fail_count}\n"
            f"Average assessment score: {avg_score:.0f}%\n\n"
            f"**Recommended actions:**\n"
            f"1. Schedule a 1:1 to discuss learning blockers\n"
            f"2. Consider reducing meeting load "
            f"(current: {signals['meeting_hours_per_week']}h/week) to free up focus time\n"
            f"3. Evaluate if the certification timeline needs adjustment\n"
            f"4. Check if additional study resources or a mentor are needed\n\n"
            f"Work IQ signals: engagement risk = {signals['engagement_risk']} | "
            f"focus hours = {signals['focus_hours_per_week']}h/week\n\n"
            f"This escalation was triggered automatically per team learning policy.\n"
            + self._RAI_DISCLAIMER
        )

    def _enhance_reminder_live(self, result: dict, signals: dict, reminder_schedule: dict) -> tuple[dict, int]:
        """Call GPT-4o to generate a personalized, context-aware engagement message."""
        try:
            agent_id = self._create_or_get_agent(self._INSTRUCTIONS)
            status = result["status"]
            prompt = (
                f"Generate a personalized learning engagement message for:\n"
                f"Name: {signals['name']}, Role: {signals['role']}\n"
                f"Certification: {result['certification_goal']}\n"
                f"Status: {status['category']} — {status['message']}\n"
                f"Completion: {result['completion_percentage']}%, "
                f"Inactive: {result['days_inactive']} days\n"
                f"Work context: {signals['meeting_hours_per_week']}h meetings/week, "
                f"{signals['focus_hours_per_week']}h focus/week\n"
                f"Preferred slot: {signals['preferred_learning_slot']} "
                f"({reminder_schedule['reminder_time']})\n"
                f"Session length: {reminder_schedule['study_session_length_minutes']} minutes\n\n"
                f"Write a warm, motivating reminder that references their specific work context "
                f"and suggests the exact next action they should take today."
                + (" Also include a constructive manager escalation note." if result.get("escalation_triggered") else "")
            )
            response_text, token_count = self._run_thread(agent_id, prompt)
            if response_text:
                result["reminder_message"] = self._apply_guardrails(response_text)
            return result, token_count
        except Exception as exc:
            logger.warning("[%s] Live reminder enhancement failed: %s", self.AGENT_NAME, exc)
            return result, 0
