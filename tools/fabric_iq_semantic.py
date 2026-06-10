"""
Fabric IQ semantic model accessor.
Queries the role-certification-skill graph in fabric_iq_model.json
to answer prerequisite, alignment, and learning path questions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent.parent / "data"


class FabricIQSemantic:
    """
    Semantic query interface over the Fabric IQ knowledge graph.

    Supports:
    - Prerequisite chains for a target certification
    - Role-certification fit scores
    - Skill gap analysis
    - Recommended learning path for a role
    - Weekly hours budget given certification level and role signals
    """

    def __init__(self) -> None:
        path = DATA_DIR / "fabric_iq_model.json"
        with open(path) as f:
            self._model = json.load(f)

        # Build lookup indices
        self._certs: dict[str, dict] = {
            c["id"]: c for c in self._model["nodes"]["certifications"]
        }
        self._roles: dict[str, dict] = {
            r["id"]: r for r in self._model["nodes"]["roles"]
        }
        self._skills: dict[str, dict] = {
            s["id"]: s for s in self._model["nodes"]["skills"]
        }

    def get_prerequisites(self, certification_id: str) -> list[dict[str, Any]]:
        """Return the prerequisite chain for a certification (BFS)."""
        prereqs = []
        visited = set()
        queue = [certification_id]
        while queue:
            cert = queue.pop(0)
            for edge in self._model["edges"]["prerequisite_of"]:
                if edge["to"] == cert and edge["from"] not in visited:
                    visited.add(edge["from"])
                    prereqs.append({
                        "certification_id": edge["from"],
                        "name": self._certs.get(edge["from"], {}).get("name", edge["from"]),
                        "relationship": edge["type"],
                        "weight": edge["weight"],
                    })
                    queue.append(edge["from"])
        return prereqs

    def get_role_alignment(self, role_name: str, certification_id: str) -> dict[str, Any]:
        """Return fit score between a role and a target certification."""
        role_obj = next(
            (r for r in self._model["nodes"]["roles"] if r["name"] == role_name), None
        )
        if not role_obj:
            return {"fit_score": 0.5, "rationale": "Role not found in semantic model"}

        for edge in self._model["edges"]["role_certification_alignment"]:
            if edge["role"] == role_obj["id"] and edge["certification"] == certification_id:
                return {
                    "role": role_name,
                    "certification_id": certification_id,
                    "fit_score": edge["fit_score"],
                    "rationale": (
                        f"{role_name} has a {int(edge['fit_score']*100)}% skill alignment "
                        f"with {certification_id} based on Fabric IQ semantic graph."
                    ),
                }

        return {
            "role": role_name,
            "certification_id": certification_id,
            "fit_score": 0.6,
            "rationale": "Moderate alignment — check official Microsoft Learn for exact role mapping.",
        }

    def get_skill_gap_coverage(
        self, skill_gaps: list[str], certification_id: str
    ) -> dict[str, Any]:
        """Quantify how much of the employee's skill gaps are covered by the target cert."""
        covered: list[str] = []
        skill_coverage_edges = self._model["edges"]["skill_certification_coverage"]

        for gap in skill_gaps:
            matched_skill = next(
                (s for s in self._model["nodes"]["skills"] if s["name"] == gap), None
            )
            if not matched_skill:
                continue
            coverage_edge = next(
                (
                    e for e in skill_coverage_edges
                    if e["skill"] == matched_skill["id"] and e["certification"] == certification_id
                ),
                None,
            )
            if coverage_edge and coverage_edge["coverage"] >= 0.7:
                covered.append(gap)

        coverage_ratio = len(covered) / max(len(skill_gaps), 1)
        return {
            "certification_id": certification_id,
            "total_skill_gaps": len(skill_gaps),
            "covered_by_cert": covered,
            "coverage_ratio": round(coverage_ratio, 2),
            "recommendation": (
                "Strongly recommended" if coverage_ratio >= 0.7
                else "Moderately relevant" if coverage_ratio >= 0.4
                else "Consider other certifications first"
            ),
        }

    def get_recommended_learning_path(self, role_name: str) -> list[str]:
        """Return the canonical certification sequence for a role."""
        role_to_path = {
            "Cloud Solutions Architect": "cloud_architect",
            "DevOps Engineer": "devops_expert",
            "Data Scientist": "data_scientist",
            "Data Engineer": "data_scientist",
            "AI/ML Engineer": "ai_engineer",
            "Security Engineer": "security_specialist",
            "Cloud Security Architect": "security_specialist",
            "Power Platform Developer": "power_platform_dev",
            "Software Engineer": "software_developer",
            "IT Manager": "it_manager",
        }
        path_key = role_to_path.get(role_name, "software_developer")
        return self._model["learning_paths"].get(path_key, ["AZ-900"])

    def get_weekly_hours_budget(
        self, certification_id: str, available_hours: float
    ) -> dict[str, Any]:
        """
        Calculate realistic study weeks given available hours per week and cert level.
        """
        cert = self._certs.get(certification_id, {})
        level = cert.get("level", "associate")
        rec = self._model["weekly_hours_recommendations"].get(level, {})

        # Pull hours from certifications.json (authoritative source)
        certs_path = DATA_DIR / "certifications.json"
        with open(certs_path) as f:
            certs_data = json.load(f)
        cert_detail = next((c for c in certs_data if c["id"] == certification_id), {})
        total_recommended = cert_detail.get("recommended_hours", 80)

        effective_hours = min(available_hours, rec.get("max_hours", 15))
        effective_hours = max(effective_hours, rec.get("min_hours", 4))
        estimated_weeks = round(total_recommended / effective_hours, 1)

        return {
            "certification_id": certification_id,
            "certification_level": level,
            "total_recommended_hours": total_recommended,
            "available_hours_per_week": available_hours,
            "effective_study_hours_per_week": effective_hours,
            "estimated_weeks_to_complete": estimated_weeks,
            "hours_range": rec,
        }
