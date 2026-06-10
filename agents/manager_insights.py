"""
ManagerInsightsAgent
Aggregates team-level certification data to surface actionable insights
for engineering managers: completion rates, at-risk learners, readiness scores.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from agents.base_agent import BaseAgent

DATA_DIR = Path(__file__).parent.parent / "data"


class ManagerInsightsAgent(BaseAgent):
    AGENT_NAME = "ManagerInsightsAgent"

    _INSTRUCTIONS = """You are an enterprise learning analytics advisor for managers.

Your job:
1. Aggregate team certification progress data across all employees
2. Identify at-risk learners and surface root cause hypotheses
3. Compute team-level readiness scores per certification domain
4. Highlight skill coverage gaps across the team
5. Provide actionable recommendations for managers

Rules:
- Present data at team level, not individual level where possible (privacy-aware)
- Always contextualize metrics (e.g., 'below industry average of 70%')
- Prioritize actionable insights over raw numbers
- Flag learners at-risk of missing certification deadlines
- Recommend structural interventions (meeting load reduction, cohort learning, etc.)"""

    def __init__(self) -> None:
        super().__init__()
        self._employees = self._load_json("employees.json")
        self._certifications = self._load_json("certifications.json")
        self._progress = self._load_json("team_progress.json")

    def _load_json(self, filename: str) -> list[dict]:
        with open(DATA_DIR / filename) as f:
            return json.load(f)

    def run(
        self,
        department: str | None = None,
        certification_filter: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate manager insights dashboard.

        Args:
            department: Filter to a specific department (None = all)
            certification_filter: Filter to a specific certification
            query: Natural language query about team learning (e.g., 'who is at risk?')
        """
        self._validate_input({"query_or_filter": department or certification_filter or query or "all"})

        record = self._start_record(f"dept={department} cert={certification_filter}")

        try:
            # Step 1: Filter employees
            self._log_step(record, "Filtering employee dataset by department")
            employees = self._filter_employees(department)

            # Step 2: Build progress map
            self._log_step(record, "Building progress map from team_progress.json")
            progress_map = {
                (p["employee_id"], p["certification_id"]): p
                for p in self._progress
            }

            # Step 3: Compute metrics
            self._log_step(record, "Computing team-level completion rates and risk metrics")
            metrics = self._compute_team_metrics(employees, progress_map, certification_filter)

            # Step 4: Identify at-risk learners
            self._log_step(record, "Identifying at-risk learners and root causes")
            at_risk = self._identify_at_risk(employees, progress_map)

            # Step 5: Skill coverage analysis
            self._log_step(record, "Analysing team skill coverage gaps")
            skill_coverage = self._skill_coverage_analysis(employees)

            # Step 6: Generate insights
            self._log_step(record, "Generating actionable insights and recommendations")
            insights = self._generate_insights(metrics, at_risk, skill_coverage, employees)

            result = {
                "agent": self.AGENT_NAME,
                "department_filter": department or "All Departments",
                "certification_filter": certification_filter,
                "team_size": len(employees),
                "metrics": metrics,
                "at_risk_learners": at_risk,
                "skill_coverage": skill_coverage,
                "insights": insights,
                "narrative_summary": self._compose_narrative(
                    metrics, at_risk, skill_coverage, insights, employees, department
                ),
            }
            result["narrative_summary"] = self._apply_guardrails(result["narrative_summary"])
            result["narrative_summary"] += self._RAI_DISCLAIMER

            # Live mode: GPT-4o generates executive-quality manager narrative
            if not self._demo_mode:
                self._log_step(record, "Calling GPT-4o to generate executive-level insights narrative")
                result, tokens = self._enhance_insights_live(result)
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

    def _filter_employees(self, department: str | None) -> list[dict]:
        if not department:
            return self._employees
        return [e for e in self._employees if e["department"] == department]

    def _compute_team_metrics(
        self,
        employees: list[dict],
        progress_map: dict,
        cert_filter: str | None,
    ) -> dict:
        completion_rates: list[float] = []
        cert_counts: dict[str, int] = defaultdict(int)
        domain_scores: dict[str, list[float]] = defaultdict(list)

        for emp in employees:
            eid = emp["employee_id"]
            in_progress = emp.get("certifications_in_progress", [])
            completed = emp.get("certifications_completed", [])

            for cert_id in (in_progress + completed):
                if cert_filter and cert_id != cert_filter:
                    continue
                key = (eid, cert_id)
                if key in progress_map:
                    pct = progress_map[key]["completion_percentage"]
                    completion_rates.append(pct)
                    scores = progress_map[key].get("assessment_scores", [])
                    if scores:
                        domain_scores[cert_id].extend(scores)
                elif cert_id in completed:
                    completion_rates.append(100.0)
                cert_counts[cert_id] += 1

        avg_completion = sum(completion_rates) / max(len(completion_rates), 1)
        cert_readiness = {
            cid: round(sum(scores) / len(scores), 1)
            for cid, scores in domain_scores.items()
        }

        return {
            "average_completion_percentage": round(avg_completion, 1),
            "total_active_certifications": sum(cert_counts.values()),
            "certifications_in_progress": dict(cert_counts),
            "certification_readiness_scores": cert_readiness,
            "completion_distribution": self._completion_distribution(completion_rates),
        }

    def _completion_distribution(self, rates: list[float]) -> dict:
        buckets = {"0-25%": 0, "26-50%": 0, "51-75%": 0, "76-100%": 0}
        for r in rates:
            if r <= 25:
                buckets["0-25%"] += 1
            elif r <= 50:
                buckets["26-50%"] += 1
            elif r <= 75:
                buckets["51-75%"] += 1
            else:
                buckets["76-100%"] += 1
        return buckets

    def _identify_at_risk(
        self, employees: list[dict], progress_map: dict
    ) -> list[dict]:
        at_risk = []
        for emp in employees:
            eid = emp["employee_id"]
            for cert_id in emp.get("certifications_in_progress", []):
                key = (eid, cert_id)
                prog = progress_map.get(key, {})
                if prog.get("at_risk"):
                    scores = prog.get("assessment_scores", [])
                    avg_score = sum(scores) / max(len(scores), 1) if scores else 0
                    at_risk.append({
                        "employee_id": eid,
                        "employee_name": emp["name"],
                        "role": emp["role"],
                        "certification_id": cert_id,
                        "completion_percentage": prog.get("completion_percentage", 0),
                        "average_assessment_score": round(avg_score, 1),
                        "last_activity_date": prog.get("last_activity_date", "unknown"),
                        "meeting_hours_per_week": emp["meeting_hours_per_week"],
                        "risk_factors": self._diagnose_risk(emp, prog),
                    })
        return at_risk

    def _diagnose_risk(self, emp: dict, prog: dict) -> list[str]:
        factors = []
        if emp["meeting_hours_per_week"] >= 18:
            factors.append("High meeting load (≥18h/week) limiting study time")
        scores = prog.get("assessment_scores", [])
        if scores and sum(scores) / len(scores) < 70:
            factors.append("Assessment scores below passing threshold (70%)")
        if prog.get("completion_percentage", 0) < 40:
            factors.append("Less than 40% complete — pace too slow for deadline")
        if not factors:
            factors.append("Flagged at-risk in progress tracking system")
        return factors

    def _skill_coverage_analysis(self, employees: list[dict]) -> dict:
        all_completed = []
        for emp in employees:
            all_completed.extend(emp.get("certifications_completed", []))

        cert_lookup = {c["id"]: c for c in self._certifications}
        covered_skills: set[str] = set()
        for cert_id in all_completed:
            if cert_id in cert_lookup:
                covered_skills.update(cert_lookup[cert_id].get("skills", []))

        all_skills: set[str] = set()
        for cert in self._certifications:
            all_skills.update(cert.get("skills", []))

        gaps = all_skills - covered_skills
        return {
            "total_skills_in_catalog": len(all_skills),
            "skills_covered_by_team": len(covered_skills),
            "coverage_percentage": round(len(covered_skills) / max(len(all_skills), 1) * 100, 1),
            "skill_gaps": sorted(list(gaps))[:15],
            "well_covered_domains": self._top_covered_domains(covered_skills),
        }

    def _top_covered_domains(self, skills: set[str]) -> list[str]:
        domain_keywords = {
            "Azure Core": ["azure_functions", "cosmos_db", "app_service", "blob_storage"],
            "DevOps": ["ci_cd_pipelines", "infrastructure_as_code", "monitoring"],
            "Security": ["zero_trust", "identity_management", "compliance"],
            "AI/ML": ["azure_openai", "cognitive_services", "azure_machine_learning"],
            "Power Platform": ["power_apps", "power_automate", "dataverse"],
        }
        covered_domains = [
            domain
            for domain, domain_skills in domain_keywords.items()
            if len(set(domain_skills) & skills) >= 2
        ]
        return covered_domains

    def _generate_insights(
        self, metrics: dict, at_risk: list, skill_coverage: dict, employees: list
    ) -> list[dict]:
        insights = []

        avg = metrics["average_completion_percentage"]
        if avg < 50:
            insights.append({
                "type": "warning",
                "title": "Low team completion rate",
                "detail": (
                    f"Team average completion is {avg:.0f}% — below the recommended 60% midpoint. "
                    "Consider a team learning sprint or reducing meeting load."
                ),
                "priority": "high",
            })

        if at_risk:
            insights.append({
                "type": "action_required",
                "title": f"{len(at_risk)} learner(s) at risk",
                "detail": (
                    f"{len(at_risk)} team members are flagged at-risk. "
                    "Primary causes: high meeting load, low assessment scores, inactivity."
                ),
                "affected": [r["employee_name"] for r in at_risk],
                "priority": "high",
            })

        if skill_coverage["coverage_percentage"] < 60:
            insights.append({
                "type": "gap",
                "title": "Skill coverage gap detected",
                "detail": (
                    f"Team covers {skill_coverage['coverage_percentage']:.0f}% of skills in the catalog. "
                    f"Top missing areas: {', '.join(skill_coverage['skill_gaps'][:5])}."
                ),
                "priority": "medium",
            })

        high_meeting_count = sum(
            1 for e in employees if e["meeting_hours_per_week"] >= 18
        )
        if high_meeting_count > 0:
            insights.append({
                "type": "structural",
                "title": "Meeting overload affecting learning capacity",
                "detail": (
                    f"{high_meeting_count} team member(s) have ≥18h/week in meetings. "
                    "This significantly limits available study time. "
                    "Recommend audit of recurring meetings."
                ),
                "priority": "medium",
            })

        return insights

    def _compose_narrative(
        self, metrics, at_risk, skill_coverage, insights, employees, department
    ) -> str:
        dept_label = department or "Entire Organization"
        narrative = (
            f"**Manager Insights Dashboard — {dept_label}**\n\n"
            f"Team size: {len(employees)} | "
            f"Active certifications: {metrics['total_active_certifications']} | "
            f"Average completion: {metrics['average_completion_percentage']:.0f}%\n\n"
        )

        narrative += "**Certification Readiness Scores (Practice Assessments):**\n"
        for cert_id, score in metrics["certification_readiness_scores"].items():
            status = "✅" if score >= 75 else "⚠️"
            narrative += f"  {status} {cert_id}: {score:.0f}% avg score\n"
        narrative += "\n"

        narrative += "**Completion Distribution:**\n"
        for bucket, count in metrics["completion_distribution"].items():
            bar = "█" * count
            narrative += f"  {bucket}: {bar} ({count})\n"
        narrative += "\n"

        if at_risk:
            narrative += f"**At-Risk Learners ({len(at_risk)}):**\n"
            for r in at_risk:
                narrative += (
                    f"  • {r['employee_name']} ({r['certification_id']}) — "
                    f"{r['completion_percentage']}% complete, "
                    f"score: {r['average_assessment_score']:.0f}%\n"
                    f"    Risk factors: {'; '.join(r['risk_factors'])}\n"
                )
            narrative += "\n"

        narrative += (
            f"**Team Skill Coverage:** {skill_coverage['coverage_percentage']:.0f}% "
            f"({skill_coverage['skills_covered_by_team']}/{skill_coverage['total_skills_in_catalog']} skills)\n"
        )
        narrative += f"Well-covered: {', '.join(skill_coverage['well_covered_domains']) or 'N/A'}\n\n"

        narrative += "**Recommended Actions:**\n"
        for ins in insights:
            priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(ins["priority"], "•")
            narrative += f"  {priority_icon} [{ins['type'].upper()}] {ins['title']}: {ins['detail']}\n\n"

        return narrative

    def _enhance_insights_live(self, result: dict) -> tuple[dict, int]:
        """Call GPT-4o to produce executive-quality, actionable manager insights."""
        try:
            agent_id = self._create_or_get_agent(self._INSTRUCTIONS)
            metrics = result["metrics"]
            at_risk = result["at_risk_learners"]
            insights = result["insights"]
            skill_gaps = result["skill_coverage"].get("skill_gaps", [])[:8]

            prompt = (
                f"Generate an executive-level team learning dashboard summary for a manager.\n\n"
                f"Department: {result['department_filter']} | Team size: {result['team_size']}\n"
                f"Avg completion: {metrics['average_completion_percentage']}% | "
                f"Active certifications: {metrics['total_active_certifications']}\n\n"
                f"Certification readiness scores: {metrics.get('certification_readiness_scores', {})}\n\n"
                f"At-risk learners ({len(at_risk)}):\n"
                + "\n".join(
                    f"- {r['employee_name']} ({r['role']}): {r['completion_percentage']}% complete, "
                    f"score {r['average_assessment_score']}%, risk: {'; '.join(r['risk_factors'][:2])}"
                    for r in at_risk
                )
                + f"\n\nTop skill gaps: {', '.join(skill_gaps)}\n\n"
                f"Key issues identified:\n"
                + "\n".join(f"- [{i['priority'].upper()}] {i['title']}: {i['detail']}" for i in insights)
                + "\n\nProvide: (1) a 2-sentence executive summary, (2) the top 3 most impactful actions "
                "the manager should take THIS WEEK with specific reasoning, "
                "(3) a 30-day forecast if current trajectory continues. "
                "Be direct, data-driven, and actionable."
            )
            response_text, token_count = self._run_thread(agent_id, prompt)
            if response_text:
                result["narrative_summary"] = self._apply_guardrails(response_text) + self._RAI_DISCLAIMER
            return result, token_count
        except Exception as exc:
            logger.warning("[%s] Live insights enhancement failed: %s", self.AGENT_NAME, exc)
            return result, 0
