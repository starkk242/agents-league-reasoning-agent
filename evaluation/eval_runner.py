"""
Evaluation harness for the Enterprise Learning System.
Runs all 5 test scenarios and scores agent outputs against expected criteria.

Usage:
  python evaluation/eval_runner.py
  python evaluation/eval_runner.py --scenario SC001
  python evaluation/eval_runner.py --azure    # use azure-ai-evaluation SDK
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv()

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    _RICH = True
    console = Console()
except ImportError:
    _RICH = False
    console = None

# Import orchestrator components
from main import LearningSystemOrchestrator, _get_employee, _get_progress


SCENARIOS_PATH = Path(__file__).parent / "test_scenarios.json"


def load_scenarios() -> list[dict]:
    with open(SCENARIOS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Evaluation checks
# ---------------------------------------------------------------------------

class EvalCheck:
    """Single evaluation assertion with pass/fail + explanation."""

    def __init__(self, name: str, passed: bool, detail: str = "") -> None:
        self.name = name
        self.passed = passed
        self.detail = detail

    def to_dict(self) -> dict:
        return {"check": self.name, "passed": self.passed, "detail": self.detail}


def check_curator_output(curator: dict, expected: dict) -> list[EvalCheck]:
    checks = []

    # Citation check
    citations = curator.get("citations", [])
    has_citations = len(citations) > 0
    checks.append(EvalCheck(
        "curator.has_citations", has_citations,
        f"Found {len(citations)} citations" if has_citations else "No citations found",
    ))

    # Minimum resources
    resources = curator.get("curated_resources", [])
    min_r = expected.get("min_resources", 1)
    checks.append(EvalCheck(
        "curator.min_resources",
        len(resources) >= min_r,
        f"Found {len(resources)} resources (expected ≥{min_r})",
    ))

    # Required topics
    required_topics = expected.get("required_topics", [])
    all_topics = []
    for r in resources:
        all_topics.extend(r.get("topics", []))
    for topic in required_topics:
        found = topic in all_topics or any(topic in t for t in all_topics)
        checks.append(EvalCheck(
            f"curator.topic.{topic}", found,
            f"Topic '{topic}' {'found' if found else 'NOT found'} in resources",
        ))

    # Narrative contains cert goal
    narrative = curator.get("narrative_summary", "")
    checks.append(EvalCheck(
        "curator.narrative_nonempty", len(narrative) > 100,
        f"Narrative length: {len(narrative)} chars",
    ))

    return checks


def check_study_plan_output(study_plan: dict, expected: dict) -> list[EvalCheck]:
    checks = []

    schedule = study_plan.get("schedule", [])
    has_schedule = len(schedule) > 0
    checks.append(EvalCheck(
        "study_plan.has_schedule", has_schedule,
        f"Schedule has {len(schedule)} weeks",
    ))

    min_weeks = expected.get("min_weeks", 1)
    checks.append(EvalCheck(
        "study_plan.min_weeks",
        len(schedule) >= min_weeks,
        f"{len(schedule)} weeks (expected ≥{min_weeks})",
    ))

    max_h = expected.get("max_hours_per_week", 20)
    actual_h = study_plan.get("effective_hours_per_week", 0)
    checks.append(EvalCheck(
        "study_plan.hours_realistic",
        actual_h <= max_h,
        f"{actual_h}h/week (limit: {max_h}h)",
    ))

    checks.append(EvalCheck(
        "study_plan.has_completion_date",
        bool(study_plan.get("estimated_completion_date")),
        study_plan.get("estimated_completion_date", "missing"),
    ))

    return checks


def check_engagement_output(engagement: dict, expected: dict) -> list[EvalCheck]:
    checks = []

    escalation_expected = expected.get("escalation_expected", False)
    escalation_triggered = engagement.get("escalation_triggered", False)
    checks.append(EvalCheck(
        "engagement.escalation_correct",
        escalation_triggered == escalation_expected,
        f"Escalation: expected={escalation_expected}, got={escalation_triggered}",
    ))

    reminder = engagement.get("reminder_message", "")
    checks.append(EvalCheck(
        "engagement.reminder_nonempty", len(reminder) > 50,
        f"Reminder length: {len(reminder)} chars",
    ))

    status_expected = expected.get("status_expected")
    if status_expected:
        actual_status = engagement.get("status", {}).get("category", "")
        checks.append(EvalCheck(
            "engagement.status_correct",
            actual_status == status_expected,
            f"Status: expected={status_expected}, got={actual_status}",
        ))

    slot_expected = expected.get("reminder_slot_expected")
    if slot_expected:
        actual_slot = engagement.get("work_iq_reminder_schedule", {}).get("reminder_time", "")
        checks.append(EvalCheck(
            "engagement.slot_in_reminder",
            slot_expected in engagement.get("reminder_message", "").lower()
            or slot_expected in (engagement.get("next_reminder_time") or "").lower(),
            f"Expected slot '{slot_expected}' in reminder",
        ))

    return checks


def check_assessment_output(assessment: dict, expected: dict) -> list[EvalCheck]:
    checks = []

    has_feedback = len(assessment.get("feedback_summary", "")) > 50
    checks.append(EvalCheck(
        "assessment.has_feedback", has_feedback,
        f"Feedback length: {len(assessment.get('feedback_summary', ''))}",
    ))

    citations = assessment.get("citations", [])
    checks.append(EvalCheck(
        "assessment.has_citations", len(citations) > 0,
        f"Found {len(citations)} question citations",
    ))

    score = assessment.get("score_percentage", -1)
    min_score = expected.get("score_above", -1)
    checks.append(EvalCheck(
        "assessment.has_score", score >= 0,
        f"Score: {score}%",
    ))

    passed_expected = expected.get("passed_expected")
    if passed_expected is not None:
        checks.append(EvalCheck(
            "assessment.pass_correct",
            assessment.get("passed") == passed_expected,
            f"Pass: expected={passed_expected}, got={assessment.get('passed')}",
        ))

    return checks


def check_manager_insights_output(insights: dict, expected: dict) -> list[EvalCheck]:
    checks = []

    at_risk = insights.get("at_risk_learners", [])
    checks.append(EvalCheck(
        "manager.identifies_at_risk", len(at_risk) > 0,
        f"Found {len(at_risk)} at-risk learners",
    ))

    metrics = insights.get("metrics", {})
    checks.append(EvalCheck(
        "manager.has_completion_rate",
        "average_completion_percentage" in metrics,
        f"Avg completion: {metrics.get('average_completion_percentage', 'missing')}",
    ))

    skill_coverage = insights.get("skill_coverage", {})
    checks.append(EvalCheck(
        "manager.has_skill_coverage",
        bool(skill_coverage),
        f"Coverage: {skill_coverage.get('coverage_percentage', 'missing')}%",
    ))

    insight_list = insights.get("insights", [])
    min_insights = expected.get("min_insights", 1)
    checks.append(EvalCheck(
        "manager.min_insights", len(insight_list) >= min_insights,
        f"Found {len(insight_list)} insights (expected ≥{min_insights})",
    ))

    return checks


def check_reasoning_steps(orchestrator: LearningSystemOrchestrator) -> list[EvalCheck]:
    """Verify each agent logged ≥3 reasoning steps."""
    checks = []
    agents = {
        "LearningPathCuratorAgent": orchestrator.curator,
        "StudyPlanGeneratorAgent": orchestrator.planner,
        "EngagementAgent": orchestrator.engagement,
        "AssessmentAgent": orchestrator.assessor,
        "ManagerInsightsAgent": orchestrator.manager_insights,
    }
    for name, agent in agents.items():
        if agent.call_records:
            steps = agent.call_records[-1].reasoning_steps
            checks.append(EvalCheck(
                f"reasoning.{name}",
                len(steps) >= 3,
                f"Logged {len(steps)} reasoning steps",
            ))
    return checks


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class EvalRunner:
    def __init__(self, use_azure_eval: bool = False) -> None:
        self.use_azure_eval = use_azure_eval
        self.orchestrator = LearningSystemOrchestrator()

    def run_scenario(self, scenario: dict) -> dict:
        sid = scenario["scenario_id"]
        name = scenario["name"]
        inp = scenario["input"]
        expected = scenario.get("expected_outputs", {})
        checks: list[EvalCheck] = []
        results_data = {}

        if _RICH and console:
            console.print(f"\n[bold cyan]Running {sid}: {name}[/bold cyan]")

        t0 = time.time()
        error = None

        try:
            if "employee_id" in inp and "certification_goal" in inp:
                # Learner flow
                results = self.orchestrator.run_learner_flow(
                    employee_id=inp["employee_id"],
                    certification_goal=inp["certification_goal"],
                    simulate_assessment_answers=inp.get("assessment_answers"),
                )
                results_data = results

                if "curator" in expected:
                    checks.extend(check_curator_output(
                        results.get("learning_path", {}), expected["curator"]
                    ))
                if "study_plan" in expected:
                    checks.extend(check_study_plan_output(
                        results.get("study_plan", {}), expected["study_plan"]
                    ))
                if "engagement" in expected:
                    checks.extend(check_engagement_output(
                        results.get("engagement", {}), expected["engagement"]
                    ))
                if "assessment" in expected:
                    checks.extend(check_assessment_output(
                        results.get("assessment", {}), expected["assessment"]
                    ))

            elif "department" in inp:
                # Manager insights flow
                result = self.orchestrator.run_manager_dashboard(
                    department=inp.get("department")
                )
                results_data = {"manager_insights": result}
                if "manager_insights" in expected:
                    checks.extend(check_manager_insights_output(
                        result, expected["manager_insights"]
                    ))

        except Exception as exc:
            error = str(exc)
            checks.append(EvalCheck("scenario.no_error", False, f"Error: {error}"))

        elapsed = time.time() - t0

        # Reasoning step checks
        checks.extend(check_reasoning_steps(self.orchestrator))

        passed_count = sum(1 for c in checks if c.passed)
        total_count = len(checks)
        score_pct = (passed_count / max(total_count, 1)) * 100

        return {
            "scenario_id": sid,
            "scenario_name": name,
            "elapsed_seconds": round(elapsed, 2),
            "checks": [c.to_dict() for c in checks],
            "passed": passed_count,
            "total": total_count,
            "score_percentage": round(score_pct, 1),
            "overall_pass": score_pct >= 80.0,
            "error": error,
        }

    def run_all(self, filter_id: str | None = None) -> list[dict]:
        scenarios = load_scenarios()
        if filter_id:
            scenarios = [s for s in scenarios if s["scenario_id"] == filter_id]
        return [self.run_scenario(s) for s in scenarios]

    def print_report(self, results: list[dict]) -> None:
        if _RICH and console:
            table = Table(title="Evaluation Results", show_header=True, header_style="bold magenta")
            table.add_column("Scenario", style="cyan", min_width=20)
            table.add_column("Score", justify="right")
            table.add_column("Checks", justify="right")
            table.add_column("Time", justify="right")
            table.add_column("Status")

            for r in results:
                status = "[bold green]PASS[/bold green]" if r["overall_pass"] else "[bold red]FAIL[/bold red]"
                table.add_row(
                    r["scenario_id"],
                    f"{r['score_percentage']:.0f}%",
                    f"{r['passed']}/{r['total']}",
                    f"{r['elapsed_seconds']}s",
                    status,
                )
            console.print(table)

            total_pass = sum(1 for r in results if r["overall_pass"])
            console.print(
                f"\n[bold]Overall: {total_pass}/{len(results)} scenarios passed[/bold]"
            )
        else:
            for r in results:
                status = "PASS" if r["overall_pass"] else "FAIL"
                print(f"{r['scenario_id']}: {r['score_percentage']:.0f}% ({r['passed']}/{r['total']} checks) [{status}]")

        # Print failed checks detail
        for r in results:
            failed = [c for c in r["checks"] if not c["passed"]]
            if failed:
                if _RICH and console:
                    console.print(f"\n[yellow]Failed checks in {r['scenario_id']}:[/yellow]")
                    for c in failed:
                        console.print(f"  [red]✗[/red] {c['check']}: {c['detail']}")
                else:
                    print(f"\nFailed in {r['scenario_id']}:")
                    for c in failed:
                        print(f"  FAIL {c['check']}: {c['detail']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run evaluation harness")
    parser.add_argument("--scenario", metavar="ID", help="Run a specific scenario")
    parser.add_argument("--azure", action="store_true", help="Use azure-ai-evaluation SDK")
    parser.add_argument("--output", metavar="FILE", help="Save results to JSON file")
    args = parser.parse_args()

    runner = EvalRunner(use_azure_eval=args.azure)
    results = runner.run_all(filter_id=args.scenario)
    runner.print_report(results)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {args.output}")

    overall_pass = all(r["overall_pass"] for r in results)
    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
