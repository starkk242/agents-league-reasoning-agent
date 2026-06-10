"""
StudyPlanGeneratorAgent
Converts curated learning resources into a practical weekly study schedule.
Uses Fabric IQ semantic model for prerequisite ordering and Work IQ for hours budget.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from typing import Any

from agents.base_agent import BaseAgent
from tools.fabric_iq_semantic import FabricIQSemantic
from tools.work_iq_signals import WorkIQSignals


class StudyPlanGeneratorAgent(BaseAgent):
    AGENT_NAME = "StudyPlanGeneratorAgent"

    _INSTRUCTIONS = """You are an expert study plan generator for Microsoft Azure certifications.

Your job:
1. Take curated learning resources and a learner's work-context signals
2. Generate a realistic, week-by-week study schedule that fits within available hours
3. Sequence resources logically (fundamentals → applied → labs → practice exams)
4. Account for prerequisites identified in the Fabric IQ semantic model
5. Build in revision weeks and buffer time before the exam

Rules:
- Never schedule more hours than the learner realistically has
- Always cite why each resource is placed in a given week
- Include milestone checkpoints every 3 weeks
- Flag if the plan requires overtime hours (high engagement risk)
- Output must be structured JSON + human-readable summary"""

    def __init__(self) -> None:
        super().__init__()
        self._fabric = FabricIQSemantic()
        self._work_iq = WorkIQSignals()

    def run(
        self,
        employee_id: str,
        certification_goal: str,
        curated_resources: list[dict],
        current_completion_percentage: float = 0.0,
    ) -> dict[str, Any]:
        """Generate a weekly study plan."""
        self._validate_input({
            "employee_id": employee_id,
            "certification_goal": certification_goal,
        })

        record = self._start_record(f"{employee_id} → {certification_goal}")

        try:
            # Step 1: Get Work IQ signals
            self._log_step(record, f"Fetching Work IQ signals for {employee_id}")
            signals = self._work_iq.get_signals(employee_id)
            available_hours_per_week = signals["available_learning_hours_per_week"]

            # Step 2: Get hours budget from Fabric IQ
            self._log_step(record, "Querying Fabric IQ for hours budget and certification level")
            budget = self._fabric.get_weekly_hours_budget(
                certification_goal, available_hours_per_week
            )

            # Step 3: Adjust for completion already done
            self._log_step(record, f"Adjusting for {current_completion_percentage:.0f}% existing progress")
            remaining_hours = budget["total_recommended_hours"] * (
                1.0 - current_completion_percentage / 100.0
            )
            effective_weeks = math.ceil(remaining_hours / budget["effective_study_hours_per_week"])

            # Step 4: Sequence resources
            self._log_step(record, "Sequencing resources using difficulty and content type ordering")
            ordered = self._sequence_resources(curated_resources)

            # Step 5: Distribute across weeks
            self._log_step(record, f"Building {effective_weeks}-week study schedule")
            weeks = self._distribute_to_weeks(
                ordered, effective_weeks, budget["effective_study_hours_per_week"],
                certification_goal,
            )

            # Step 6: Compose result
            result = self._compose_result(
                employee_id, certification_goal, signals, budget,
                weeks, effective_weeks, remaining_hours,
                current_completion_percentage,
            )

            # Live mode: enhance narrative with GPT-4o
            if not self._demo_mode:
                self._log_step(record, "Calling GPT-4o to generate enhanced study plan narrative")
                result, tokens = self._enhance_narrative_live(result, signals, budget)
                record.finish(token_count=tokens, success=True)
            else:
                result["narrative_summary"] = self._apply_guardrails(result["narrative_summary"])
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

    def _sequence_resources(self, resources: list[dict]) -> list[dict]:
        """Order: beginner → intermediate → advanced; articles → videos → labs."""
        diff_order = {"beginner": 0, "intermediate": 1, "advanced": 2}
        type_order = {"article": 0, "video": 1, "lab": 2}
        return sorted(
            resources,
            key=lambda r: (
                diff_order.get(r.get("difficulty", "intermediate"), 1),
                type_order.get(r.get("content_type", "article"), 0),
            ),
        )

    def _distribute_to_weeks(
        self, resources: list[dict], total_weeks: int, hours_per_week: float,
        certification_id: str = "",
    ) -> list[dict]:
        """Distribute resources across weeks, respecting hour budget per week."""
        weeks: list[dict] = []
        week_num = 1
        current_week: dict = {"week": week_num, "theme": "", "items": [], "hours": 0.0, "milestone": False}
        minutes_budget = hours_per_week * 60

        for res in resources:
            item_minutes = res.get("estimated_minutes", 60)
            if current_week["hours"] * 60 + item_minutes > minutes_budget and current_week["items"]:
                # Milestone every 3 weeks
                if week_num % 3 == 0:
                    current_week["milestone"] = True
                    current_week["milestone_description"] = (
                        f"Week {week_num} checkpoint: review all material from weeks "
                        f"{week_num-2}–{week_num} and attempt a practice quiz."
                    )
                weeks.append(current_week)
                week_num += 1
                current_week = {
                    "week": week_num,
                    "theme": "",
                    "items": [],
                    "hours": 0.0,
                    "milestone": False,
                }

            current_week["items"].append({
                "document_id": res.get("document_id", ""),
                "title": res.get("title", ""),
                "content_type": res.get("content_type", "article"),
                "estimated_minutes": item_minutes,
                "citation": res.get("citation", ""),
            })
            current_week["hours"] += item_minutes / 60.0

        if current_week["items"]:
            weeks.append(current_week)

        # Set themes
        for w in weeks:
            types = [i["content_type"] for i in w["items"]]
            if "lab" in types:
                w["theme"] = "Hands-on Practice"
            elif "video" in types:
                w["theme"] = "Concept Deep-Dive"
            else:
                w["theme"] = "Foundational Reading"

        # Add final revision week
        weeks.append({
            "week": len(weeks) + 1,
            "theme": "Revision & Exam Prep",
            "items": [
                {
                    "document_id": "PRACTICE",
                    "title": f"Practice exam for {certification_id or resources[0].get('certification_id', '')} (Microsoft Official)",
                    "content_type": "practice_exam",
                    "estimated_minutes": 90,
                    "citation": "[Source: Microsoft Learn — Official Practice Assessment]",
                }
            ],
            "hours": 1.5,
            "milestone": True,
            "milestone_description": "Final readiness check: score ≥ 80% on practice exam before scheduling.",
        })

        return weeks

    def _compose_result(
        self,
        employee_id, cert_goal, signals, budget,
        weeks, effective_weeks, remaining_hours, current_pct,
    ) -> dict:
        start_date = date.today()
        end_date = start_date + timedelta(weeks=effective_weeks + 1)

        # Build narrative
        narrative = (
            f"**Weekly Study Plan: {cert_goal}**\n\n"
            f"Learner: {signals['name']} ({signals['role']})\n"
            f"Available study time: {budget['effective_study_hours_per_week']}h/week "
            f"(Work IQ: {signals['meeting_hours_per_week']}h/week in meetings, "
            f"engagement risk: {signals['engagement_risk']})\n"
            f"Current progress: {current_pct:.0f}% complete\n"
            f"Remaining hours needed: {remaining_hours:.0f}h over ~{effective_weeks} weeks\n"
            f"Target completion: {end_date.strftime('%B %d, %Y')}\n\n"
        )

        if signals["engagement_risk"] == "high":
            narrative += (
                "⚠️ **High meeting load detected** — plan uses micro-sessions "
                f"({signals['preferred_learning_slot']} slot). "
                "Notify manager if overtime is required.\n\n"
            )

        for w in weeks:
            milestone_marker = " ✅ MILESTONE" if w["milestone"] else ""
            narrative += f"**Week {w['week']}: {w['theme']}{milestone_marker}** ({w['hours']:.1f}h)\n"
            for item in w["items"]:
                narrative += f"  • [{item['content_type'].upper()}] {item['title']} (~{item['estimated_minutes']}min)\n"
                narrative += f"    {item['citation']}\n"
            if w.get("milestone_description"):
                narrative += f"  → {w['milestone_description']}\n"
            narrative += "\n"

        return {
            "agent": self.AGENT_NAME,
            "employee_id": employee_id,
            "certification_goal": cert_goal,
            "work_iq_signals": signals,
            "fabric_iq_budget": budget,
            "total_weeks": len(weeks),
            "effective_hours_per_week": budget["effective_study_hours_per_week"],
            "estimated_completion_date": end_date.isoformat(),
            "schedule": weeks,
            "narrative_summary": narrative + self._RAI_DISCLAIMER,
            "engagement_risk": signals["engagement_risk"],
            "preferred_slot": signals["preferred_learning_slot"],
        }

    def _enhance_narrative_live(self, result: dict, signals: dict, budget: dict) -> tuple[dict, int]:
        """Call GPT-4o to generate an enhanced, motivational study plan narrative."""
        try:
            agent_id = self._create_or_get_agent(self._INSTRUCTIONS)
            prompt = (
                f"Generate an encouraging, detailed study plan narrative for:\n"
                f"Learner: {signals['name']} ({signals['role']})\n"
                f"Certification: {result['certification_goal']}\n"
                f"Progress: {result.get('engagement_risk', 'low')} engagement risk, "
                f"{budget['effective_study_hours_per_week']}h/week available\n"
                f"Schedule: {result['total_weeks']} weeks, "
                f"completion by {result['estimated_completion_date']}\n\n"
                f"Weekly breakdown:\n"
                + "\n".join(
                    f"Week {w['week']} ({w['theme']}): "
                    + ", ".join(i['title'] for i in w['items'])
                    for w in result['schedule']
                )
                + "\n\nProvide motivational framing, explain WHY each week's theme was chosen, "
                f"and tailor advice for a {signals['role']} with {signals['engagement_risk']} engagement risk."
            )
            response_text, token_count = self._run_thread(agent_id, prompt)
            if response_text:
                result["narrative_summary"] = self._apply_guardrails(response_text) + self._RAI_DISCLAIMER
            return result, token_count
        except Exception as exc:
            logger.warning("[%s] Live narrative enhancement failed: %s — using local narrative", self.AGENT_NAME, exc)
            result["narrative_summary"] = self._apply_guardrails(result["narrative_summary"])
            return result, 0
