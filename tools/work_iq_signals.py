"""
Work IQ signals accessor.
Reads employee work-context signals (meeting load, focus blocks, preferred learning slot)
from the synthetic employees.json dataset.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent.parent / "data"


class WorkIQSignals:
    """
    Provides Work IQ signals for a given employee.

    Signals used by EngagementAgent to personalize reminders and study windows:
    - meeting_hours_per_week: hours consumed by meetings
    - focus_hours_per_week: deep-work hours available
    - preferred_learning_slot: morning / afternoon / evening / lunch
    """

    _SLOT_TIMES = {
        "morning": "7:00–9:00 AM",
        "afternoon": "12:00–2:00 PM",
        "evening": "6:00–8:00 PM",
        "lunch": "12:00–1:00 PM",
    }

    def __init__(self) -> None:
        path = DATA_DIR / "employees.json"
        with open(path) as f:
            employees = json.load(f)
        self._index: dict[str, dict] = {e["employee_id"]: e for e in employees}

    def get_signals(self, employee_id: str) -> dict[str, Any]:
        """Return raw Work IQ signals for an employee."""
        emp = self._index.get(employee_id)
        if not emp:
            raise KeyError(f"Employee '{employee_id}' not found in Work IQ signals")
        return {
            "employee_id": employee_id,
            "name": emp["name"],
            "role": emp["role"],
            "meeting_hours_per_week": emp["meeting_hours_per_week"],
            "focus_hours_per_week": emp["focus_hours_per_week"],
            "preferred_learning_slot": emp["preferred_learning_slot"],
            "available_learning_hours_per_week": self._compute_available_hours(emp),
            "learning_slot_time": self._SLOT_TIMES.get(
                emp["preferred_learning_slot"], "flexible"
            ),
            "engagement_risk": self._assess_engagement_risk(emp),
        }

    def _compute_available_hours(self, emp: dict) -> float:
        """Estimate hours realistically available for learning each week."""
        total_work_hours = 40.0
        meeting_overhead = emp["meeting_hours_per_week"]
        focus_available = emp["focus_hours_per_week"]
        # Cap available learning at 30% of focus time to avoid burnout
        available = min(focus_available * 0.30, total_work_hours - meeting_overhead)
        return round(max(available, 1.0), 1)

    def _assess_engagement_risk(self, emp: dict) -> str:
        """
        Classify engagement risk based on work signals.

        High: >20 meeting hrs/week (barely time to breathe)
        Medium: 15–20 meeting hrs/week
        Low: <15 meeting hrs/week
        """
        mtg = emp["meeting_hours_per_week"]
        if mtg >= 20:
            return "high"
        if mtg >= 15:
            return "medium"
        return "low"

    def get_all_employees(self) -> list[dict]:
        return list(self._index.values())

    def get_reminder_schedule(self, employee_id: str) -> dict[str, Any]:
        """
        Compute an adaptive reminder schedule based on Work IQ signals.

        Returns day + time window for study reminders.
        """
        signals = self.get_signals(employee_id)
        slot = signals["preferred_learning_slot"]
        risk = signals["engagement_risk"]

        frequency = {"high": "twice per week", "medium": "three times per week", "low": "daily"}
        days = {
            "high": ["Tuesday", "Thursday"],
            "medium": ["Monday", "Wednesday", "Friday"],
            "low": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        }

        return {
            "employee_id": employee_id,
            "reminder_frequency": frequency[risk],
            "reminder_days": days[risk],
            "reminder_time": self._SLOT_TIMES.get(slot, "flexible"),
            "study_session_length_minutes": self._recommended_session_length(signals),
            "rationale": (
                f"{signals['name']} has {signals['meeting_hours_per_week']}h/week "
                f"in meetings (engagement risk: {risk}). "
                f"Optimal slot: {slot} ({self._SLOT_TIMES.get(slot)})."
            ),
        }

    def _recommended_session_length(self, signals: dict) -> int:
        """Map engagement risk to focused study session length in minutes."""
        risk = signals["engagement_risk"]
        return {"high": 30, "medium": 45, "low": 60}[risk]
