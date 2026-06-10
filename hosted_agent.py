"""
Hosted Agent entrypoint for Azure AI Foundry Agent Service.
Wraps the LearningSystemOrchestrator as a deployable Foundry Agent endpoint.

To deploy:
  az ai agent create --source hosted_agent.py --endpoint $AZURE_AI_PROJECT_ENDPOINT

Local test:
  python hosted_agent.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from main import LearningSystemOrchestrator, _get_employee


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------

SUPPORTED_ACTIONS = {
    "learner_flow": "Run full learning pipeline for an employee",
    "manager_dashboard": "Get team-level insights for a manager",
    "assessment": "Run a certification practice assessment",
    "engagement_check": "Check learner engagement status and get reminder",
}


def handle_request(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Main handler for hosted agent requests.

    Expected payload format:
    {
        "action": "learner_flow" | "manager_dashboard" | "assessment" | "engagement_check",
        "employee_id": "EMP007",           # for learner actions
        "certification_goal": "AZ-204",    # for learner actions
        "department": "Engineering",        # for manager_dashboard
        "answers": {"Q01": "A", ...}       # for assessment
    }
    """
    action = payload.get("action", "learner_flow")

    if action not in SUPPORTED_ACTIONS:
        return {
            "error": f"Unsupported action '{action}'",
            "supported_actions": list(SUPPORTED_ACTIONS.keys()),
        }

    orchestrator = LearningSystemOrchestrator()

    try:
        if action == "learner_flow":
            emp_id = payload.get("employee_id")
            cert_goal = payload.get("certification_goal")
            if not emp_id or not cert_goal:
                return {"error": "employee_id and certification_goal are required"}

            emp = _get_employee(emp_id)
            if not emp:
                return {"error": f"Employee '{emp_id}' not found"}

            results = orchestrator.run_learner_flow(
                employee_id=emp_id,
                certification_goal=cert_goal,
                simulate_assessment_answers=payload.get("answers"),
            )
            return {
                "action": action,
                "status": "success",
                "employee_id": emp_id,
                "certification_goal": cert_goal,
                "learning_path_summary": results.get("learning_path", {}).get(
                    "narrative_summary", ""
                )[:500],
                "study_plan_weeks": len(
                    results.get("study_plan", {}).get("schedule", [])
                ),
                "assessment_score": results.get("assessment", {}).get("score_percentage"),
                "assessment_passed": results.get("assessment", {}).get("passed"),
                "engagement_escalated": results.get("engagement", {}).get("escalation_triggered"),
                "next_cert_recommendation": results.get("next_certification_recommendation"),
            }

        elif action == "manager_dashboard":
            department = payload.get("department")
            result = orchestrator.run_manager_dashboard(department=department)
            return {
                "action": action,
                "status": "success",
                "department": department or "All",
                "team_size": result.get("team_size"),
                "average_completion": result.get("metrics", {}).get("average_completion_percentage"),
                "at_risk_count": len(result.get("at_risk_learners", [])),
                "insights_count": len(result.get("insights", [])),
                "summary": result.get("narrative_summary", "")[:800],
            }

        elif action == "assessment":
            emp_id = payload.get("employee_id")
            cert_goal = payload.get("certification_goal")
            answers = payload.get("answers")
            if not emp_id or not cert_goal:
                return {"error": "employee_id and certification_goal are required"}

            result = orchestrator.assessor.run(
                employee_id=emp_id,
                certification_goal=cert_goal,
                learner_answers=answers,
                question_count=payload.get("question_count", 5),
            )
            return {
                "action": action,
                "status": "success",
                "score_percentage": result.get("score_percentage"),
                "passed": result.get("passed"),
                "verdict": result.get("verdict"),
                "feedback": result.get("feedback_summary", "")[:600],
                "citations": result.get("citations", []),
            }

        elif action == "engagement_check":
            emp_id = payload.get("employee_id")
            cert_goal = payload.get("certification_goal")
            if not emp_id or not cert_goal:
                return {"error": "employee_id and certification_goal are required"}

            from data_loader import _get_progress
            progress = _get_progress(emp_id, cert_goal) or {}
            result = orchestrator.engagement.run(
                employee_id=emp_id,
                certification_goal=cert_goal,
                completion_percentage=progress.get("completion_percentage", 0),
                last_activity_date=progress.get("last_activity_date", "2026-01-01"),
                assessment_scores=progress.get("assessment_scores", []),
            )
            return {
                "action": action,
                "status": "success",
                "reminder": result.get("reminder_message", "")[:400],
                "escalation_triggered": result.get("escalation_triggered"),
                "escalation_message": result.get("escalation_to_manager", "")[:400],
                "status_category": result.get("status", {}).get("category"),
            }

    except Exception as exc:
        return {"action": action, "status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Azure Foundry Agent Service entrypoint
# ---------------------------------------------------------------------------

def agent_main(context: dict) -> dict:
    """
    Azure AI Foundry hosted agent entrypoint.
    `context` is provided by the Foundry Agent Service runtime.
    """
    # Extract payload from Foundry Agent Service context
    payload = context.get("body", context)
    if isinstance(payload, str):
        payload = json.loads(payload)
    return handle_request(payload)


# ---------------------------------------------------------------------------
# Local test entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Testing hosted agent locally...\n")

    test_cases = [
        {
            "action": "learner_flow",
            "employee_id": "EMP007",
            "certification_goal": "AZ-204",
            "answers": {"Q01": "A", "Q02": "A", "Q03": "A", "Q04": "A", "Q05": "A"},
        },
        {
            "action": "manager_dashboard",
            "department": "Engineering",
        },
    ]

    for tc in test_cases:
        print(f"\n--- Testing action: {tc['action']} ---")
        result = handle_request(tc)
        print(json.dumps(result, indent=2)[:600])
        print("...")
