"""
Enterprise Learning System Orchestrator
Microsoft Agents League Hackathon 2026 — Reasoning Agents Track

Usage:
  python main.py --demo                  # Run full end-to-end demo scenario
  python main.py --employee EMP007       # Run for a specific employee
  python main.py --manager              # Show manager insights dashboard
  python main.py --assess EMP005 AI-102 # Run assessment for employee + cert
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Rich CLI setup
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.rule import Rule
    from rich.text import Text
    from rich import print as rprint
    _RICH = True
except ImportError:
    _RICH = False

console = Console() if _RICH else None


def cprint(msg: str, style: str = "") -> None:
    if _RICH and console:
        if style:
            console.print(msg, style=style)
        else:
            console.print(msg)
    else:
        print(msg)


def print_panel(title: str, content: str, style: str = "blue") -> None:
    if _RICH and console:
        console.print(Panel(content, title=f"[bold]{title}[/bold]", border_style=style))
    else:
        print(f"\n{'='*60}\n{title}\n{'='*60}\n{content}\n")


def print_agent_handoff(from_agent: str, to_agent: str) -> None:
    if _RICH and console:
        console.print(
            f"\n[bold cyan]  ➤  {from_agent}[/bold cyan]"
            f"[dim] ──────────────────────▶[/dim]"
            f"[bold green] {to_agent}[/bold green]\n"
        )
    else:
        print(f"\n  >> {from_agent} → {to_agent}\n")


def print_reasoning_step(agent: str, step: str, step_num: int) -> None:
    if _RICH and console:
        console.print(f"  [dim]  [{step_num}][/dim] [italic]{step}[/italic]")
    else:
        print(f"  [{step_num}] {step}")


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from agents.learning_path_curator import LearningPathCuratorAgent
from agents.study_plan_generator import StudyPlanGeneratorAgent
from agents.engagement_agent import EngagementAgent
from agents.assessment_agent import AssessmentAgent
from agents.manager_insights import ManagerInsightsAgent


# ---------------------------------------------------------------------------
# Data loader helpers
# ---------------------------------------------------------------------------

def _load_json(filename: str) -> list | dict:
    with open(BASE_DIR / "data" / filename) as f:
        return json.load(f)


def _get_employee(employee_id: str) -> dict | None:
    employees = _load_json("employees.json")
    return next((e for e in employees if e["employee_id"] == employee_id), None)


def _get_progress(employee_id: str, cert_id: str) -> dict | None:
    progress = _load_json("team_progress.json")
    return next(
        (p for p in progress if p["employee_id"] == employee_id and p["certification_id"] == cert_id),
        None,
    )


# ---------------------------------------------------------------------------
# Orchestrator logic
# ---------------------------------------------------------------------------

class LearningSystemOrchestrator:
    """
    Chains all 5 agents in sequence:
    Curator → StudyPlan → Engagement → Assessment → (loop or next cert)
    ManagerInsights is available on-demand.
    """

    MAX_ASSESSMENT_RETRIES = 2

    def __init__(self) -> None:
        self.curator = LearningPathCuratorAgent()
        self.planner = StudyPlanGeneratorAgent()
        self.engagement = EngagementAgent()
        self.assessor = AssessmentAgent()
        self.manager_insights = ManagerInsightsAgent()

    def run_learner_flow(
        self,
        employee_id: str,
        certification_goal: str,
        simulate_assessment_answers: dict | None = None,
    ) -> dict:
        """
        Full pipeline for a single learner.
        Returns aggregated results from all agent stages.
        """
        emp = _get_employee(employee_id)
        if not emp:
            raise ValueError(f"Employee '{employee_id}' not found in dataset")

        progress = _get_progress(employee_id, certification_goal) or {}
        results = {}

        if _RICH and console:
            console.print(Rule(
                f"[bold magenta]Enterprise Learning System — {emp['name']} → {certification_goal}[/bold magenta]"
            ))

        # ── STAGE 1: Learning Path Curator ───────────────────────────────
        cprint("\n[bold]Stage 1: Learning Path Curation[/bold]", "bold yellow")
        print_agent_handoff("User Input", "LearningPathCuratorAgent")

        curator_result = self._run_with_spinner(
            "LearningPathCuratorAgent",
            lambda: self.curator.run(
                employee_id=employee_id,
                role=emp["role"],
                certification_goal=certification_goal,
                skill_gaps=emp.get("skill_gaps", []),
                completed_certifications=emp.get("certifications_completed", []),
            ),
        )
        results["learning_path"] = curator_result
        self._print_reasoning_steps(curator_result, "LearningPathCuratorAgent")
        print_panel(
            "Curated Learning Path",
            curator_result.get("narrative_summary", "")[:1200],
            style="green",
        )

        # ── STAGE 2: Study Plan Generator ────────────────────────────────
        print_agent_handoff("LearningPathCuratorAgent", "StudyPlanGeneratorAgent")

        study_result = self._run_with_spinner(
            "StudyPlanGeneratorAgent",
            lambda: self.planner.run(
                employee_id=employee_id,
                certification_goal=certification_goal,
                curated_resources=curator_result.get("curated_resources", []),
                current_completion_percentage=progress.get("completion_percentage", 0),
            ),
        )
        results["study_plan"] = study_result
        self._print_reasoning_steps(study_result, "StudyPlanGeneratorAgent")
        print_panel(
            "Weekly Study Plan",
            study_result.get("narrative_summary", "")[:1200],
            style="cyan",
        )

        # ── STAGE 3: Engagement Agent ─────────────────────────────────────
        print_agent_handoff("StudyPlanGeneratorAgent", "EngagementAgent")

        engagement_result = self._run_with_spinner(
            "EngagementAgent",
            lambda: self.engagement.run(
                employee_id=employee_id,
                certification_goal=certification_goal,
                completion_percentage=progress.get("completion_percentage", 0),
                last_activity_date=progress.get("last_activity_date", "2026-01-01"),
                assessment_scores=progress.get("assessment_scores", []),
                failed_assessment_count=sum(
                    1 for s in progress.get("assessment_scores", []) if s < 70
                ),
            ),
        )
        results["engagement"] = engagement_result
        self._print_reasoning_steps(engagement_result, "EngagementAgent")

        reminder = engagement_result.get("reminder_message", "")
        escalation = engagement_result.get("escalation_to_manager")
        print_panel("Engagement Reminder", reminder[:800], style="yellow")

        if escalation:
            cprint("\n[bold red]  ⚠ ESCALATION TO MANAGER TRIGGERED[/bold red]")
            print_panel("Manager Escalation", escalation[:600], style="red")

        # ── STAGE 4: Assessment ───────────────────────────────────────────
        print_agent_handoff("EngagementAgent", "AssessmentAgent")

        cprint("\n[bold]Stage 4: Assessment (simulating learner answers)[/bold]", "bold yellow")

        # Default simulated answers for demo (mix of correct/wrong)
        if simulate_assessment_answers is None:
            simulate_assessment_answers = {
                "Q01": "A", "Q02": "A", "Q03": "A", "Q04": "B", "Q05": "A",
            }

        assessment_result = self._run_with_spinner(
            "AssessmentAgent",
            lambda: self.assessor.run(
                employee_id=employee_id,
                certification_goal=certification_goal,
                learner_answers=simulate_assessment_answers,
                question_count=5,
            ),
        )
        results["assessment"] = assessment_result
        self._print_reasoning_steps(assessment_result, "AssessmentAgent")

        verdict = assessment_result.get("verdict", "")
        score = assessment_result.get("score_percentage", 0)
        passed = assessment_result.get("passed", False)

        score_style = "bold green" if passed else "bold red"
        cprint(f"\n  Assessment Score: {score:.0f}%  |  Verdict: {verdict}", score_style)
        print_panel(
            "Assessment Feedback",
            assessment_result.get("feedback_summary", "")[:1000],
            style="green" if passed else "red",
        )

        # ── Adaptive loop: failed assessment ─────────────────────────────
        if not passed:
            cprint(
                "\n[bold yellow]  ↩  Assessment failed — looping back to study plan with remediation[/bold yellow]"
            )
            remediation = assessment_result.get("readiness", {}).get("remediation_resources", [])
            if remediation:
                cprint(f"  Targeted remediation: {[r['title'] for r in remediation[:3]]}", "italic")

        # ── Next certification recommendation ─────────────────────────────
        if passed:
            self._recommend_next_cert(emp, certification_goal, results)

        return results

    def run_manager_dashboard(self, department: str | None = None) -> dict:
        """Run the manager insights agent for a team overview."""
        if _RICH and console:
            console.print(Rule("[bold magenta]Manager Insights Dashboard[/bold magenta]"))

        print_agent_handoff("Manager Query", "ManagerInsightsAgent")

        result = self._run_with_spinner(
            "ManagerInsightsAgent",
            lambda: self.manager_insights.run(department=department),
        )
        self._print_reasoning_steps(result, "ManagerInsightsAgent")
        print_panel(
            "Team Learning Insights",
            result.get("narrative_summary", "")[:2000],
            style="magenta",
        )
        return result

    def _recommend_next_cert(self, emp: dict, current_cert: str, results: dict) -> None:
        """Suggest the next certification in the learning path."""
        from tools.fabric_iq_semantic import FabricIQSemantic
        fabric = FabricIQSemantic()
        path = fabric.get_recommended_learning_path(emp["role"])
        completed = emp.get("certifications_completed", []) + [current_cert]
        next_certs = [c for c in path if c not in completed]

        if next_certs:
            cprint(
                f"\n  [bold green]✓ Cert complete! Next recommended: {next_certs[0]}[/bold green]"
            )
            results["next_certification_recommendation"] = next_certs[0]

    def _run_with_spinner(self, agent_name: str, fn) -> dict:
        if _RICH and console:
            with Progress(
                SpinnerColumn(),
                TextColumn(f"[cyan]{agent_name}[/cyan] running..."),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task("", total=None)
                t0 = time.time()
                result = fn()
                elapsed = time.time() - t0
            cprint(f"  ✓ {agent_name} completed in {elapsed:.2f}s", "dim")
            return result
        return fn()

    def _print_reasoning_steps(self, result: dict, agent_name: str) -> None:
        """Print the agent's logged reasoning steps to console."""
        agent_obj = getattr(self, _agent_attr(agent_name), None)
        steps: list[str] = []
        if agent_obj and agent_obj.call_records:
            steps = agent_obj.call_records[-1].reasoning_steps

        if steps:
            cprint(f"\n  [dim]Reasoning steps ({agent_name}):[/dim]", "dim")
            for i, step in enumerate(steps, 1):
                print_reasoning_step(agent_name, step, i)


def _agent_attr(agent_name: str) -> str:
    return {
        "LearningPathCuratorAgent": "curator",
        "StudyPlanGeneratorAgent": "planner",
        "EngagementAgent": "engagement",
        "AssessmentAgent": "assessor",
        "ManagerInsightsAgent": "manager_insights",
    }.get(agent_name, "")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enterprise Learning System — Microsoft Agents League 2026",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --demo
  python main.py --employee EMP007 --cert AZ-204
  python main.py --manager
  python main.py --manager --dept "Engineering"
  python main.py --assess EMP005 AI-102
        """,
    )
    parser.add_argument("--demo", action="store_true", help="Run full end-to-end demo")
    parser.add_argument("--employee", metavar="EMP_ID", help="Employee ID (e.g. EMP007)")
    parser.add_argument("--cert", metavar="CERT_ID", help="Target certification (e.g. AZ-204)")
    parser.add_argument("--manager", action="store_true", help="Show manager insights dashboard")
    parser.add_argument("--dept", metavar="DEPT", help="Filter manager dashboard by department")
    parser.add_argument("--assess", nargs=2, metavar=("EMP_ID", "CERT_ID"), help="Run assessment")
    return parser


def run_demo(orchestrator: LearningSystemOrchestrator) -> None:
    """Full end-to-end demo scenario."""
    if _RICH and console:
        console.print(Panel(
            "[bold white]Microsoft Agents League 2026 — Reasoning Agents Track[/bold white]\n"
            "[dim]Enterprise Learning & Certification Management System[/dim]\n\n"
            "Powered by: Azure AI Foundry · Foundry IQ · Fabric IQ · Work IQ",
            title="[bold magenta]Demo Mode[/bold magenta]",
            border_style="magenta",
            padding=(1, 4),
        ))

    cprint("\n[bold]Demo Scenario: Sam Nguyen (Software Engineer) → AZ-204[/bold]", "bold white")
    cprint("This demo chains all 5 agents to show the full reasoning pipeline.\n", "dim")

    # Learner flow
    orchestrator.run_learner_flow(
        employee_id="EMP007",
        certification_goal="AZ-204",
    )

    # Manager dashboard
    cprint("\n\n[bold]Demo Part 2: Manager Insights Dashboard[/bold]", "bold white")
    orchestrator.run_manager_dashboard(department="Engineering")

    if _RICH and console:
        console.print(Rule("[bold green]Demo Complete[/bold green]"))
    cprint("\nAll 5 agents executed successfully. Check logs for telemetry data.\n", "bold green")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not any([args.demo, args.employee, args.manager, args.assess]):
        parser.print_help()
        sys.exit(0)

    orchestrator = LearningSystemOrchestrator()

    try:
        if args.demo:
            run_demo(orchestrator)

        elif args.employee:
            cert = args.cert
            if not cert:
                emp = _get_employee(args.employee)
                if emp and emp.get("certifications_in_progress"):
                    cert = emp["certifications_in_progress"][0]
                else:
                    cprint("Error: --cert required when using --employee", "bold red")
                    sys.exit(1)
            orchestrator.run_learner_flow(args.employee, cert)

        elif args.manager:
            orchestrator.run_manager_dashboard(department=args.dept)

        elif args.assess:
            emp_id, cert_id = args.assess
            cprint(f"\nRunning assessment for {emp_id} → {cert_id}", "bold cyan")
            result = orchestrator.assessor.run(
                employee_id=emp_id,
                certification_goal=cert_id,
                learner_answers={"Q01": "A", "Q02": "A", "Q03": "A", "Q04": "A", "Q05": "A"},
                question_count=5,
            )
            print_panel(
                "Assessment Result",
                result.get("feedback_summary", "")[:1200],
                style="green" if result.get("passed") else "red",
            )

    except KeyboardInterrupt:
        cprint("\n\nInterrupted by user.", "dim")
        sys.exit(0)
    except Exception as exc:
        cprint(f"\n[bold red]Error: {exc}[/bold red]")
        raise


if __name__ == "__main__":
    main()
