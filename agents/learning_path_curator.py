"""
LearningPathCuratorAgent
Retrieves grounded, cited learning content from Foundry IQ knowledge base
mapped to a learner's role and certification goal.
"""
from __future__ import annotations

import os
import json
from typing import Any

from agents.base_agent import BaseAgent
from tools.knowledge_retrieval import FoundryIQKnowledgeRetrieval
from tools.fabric_iq_semantic import FabricIQSemantic


class LearningPathCuratorAgent(BaseAgent):
    AGENT_NAME = "LearningPathCuratorAgent"

    _INSTRUCTIONS = """You are an enterprise learning path curator specializing in Microsoft Azure certifications.

Your job:
1. Analyze the learner's role, skill gaps, and target certification
2. Retrieve relevant learning content from the Foundry IQ knowledge base
3. Curate a prioritized list of resources that directly address skill gaps
4. Cite every piece of content with its document ID and title
5. Explain WHY each resource is recommended for this specific learner

Rules:
- Never fabricate content — only cite verified knowledge base sources
- Always include citation format: [Source: <document_id> — "<title>"]
- Prioritize hands-on labs and videos over articles for complex topics
- Flag prerequisites the learner may be missing
- Keep recommendations actionable and role-specific"""

    def __init__(self) -> None:
        super().__init__()
        self._kb = FoundryIQKnowledgeRetrieval(demo_mode=self._demo_mode)
        self._fabric = FabricIQSemantic()

    def run(
        self,
        employee_id: str,
        role: str,
        certification_goal: str,
        skill_gaps: list[str] | None = None,
        completed_certifications: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Curate a learning path for the given learner.

        Returns structured dict with recommended resources + citations.
        """
        skill_gaps = skill_gaps or []
        completed_certifications = completed_certifications or []

        self._validate_input({
            "employee_id": employee_id,
            "role": role,
            "certification_goal": certification_goal,
        })

        record = self._start_record(f"{role} → {certification_goal}")

        try:
            self._log_step(record, f"Analyzing role '{role}' alignment with {certification_goal}")

            # Step 1: Check prerequisites via Fabric IQ
            self._log_step(record, "Querying Fabric IQ for prerequisite chain")
            prereqs = self._fabric.get_prerequisites(certification_goal)
            missing_prereqs = [
                p for p in prereqs
                if p["certification_id"] not in completed_certifications
                and p["relationship"] == "hard_prerequisite"
            ]

            # Step 2: Assess role alignment
            self._log_step(record, "Computing role-certification fit score from Fabric IQ")
            alignment = self._fabric.get_role_alignment(role, certification_goal)

            # Step 3: Analyse skill gap coverage
            self._log_step(record, f"Analysing coverage of {len(skill_gaps)} skill gaps")
            gap_coverage = self._fabric.get_skill_gap_coverage(skill_gaps, certification_goal)

            # Step 4: Retrieve relevant knowledge from Foundry IQ
            self._log_step(record, "Retrieving grounded content from Foundry IQ knowledge base")
            query = f"{role} {certification_goal} {' '.join(skill_gaps)}"
            resources = self._kb.retrieve(
                query=query,
                certification_id=certification_goal,
                top_k=6,
            )

            if not resources:
                # Fallback: retrieve all content for the cert
                resources = self._kb.get_by_certification(certification_goal)
                for r in resources:
                    r["relevance_score"] = 0.5
                    r["citation"] = (
                        f"[Source: learning_content.json › {r['id']} — \"{r['title']}\"]"
                    )

            # Step 5: Sort by relevance and prioritize labs
            self._log_step(record, "Curating and ranking resources by relevance and content type")
            resources = self._rank_resources(resources, skill_gaps)

            # Step 6: Compose result
            if self._demo_mode:
                result = self._compose_demo_result(
                    employee_id, role, certification_goal,
                    resources, prereqs, missing_prereqs,
                    alignment, gap_coverage,
                )
            else:
                result = self._compose_live_result(
                    employee_id, role, certification_goal,
                    resources, prereqs, missing_prereqs,
                    alignment, gap_coverage,
                )

            result = self._apply_guardrails_to_result(result)
            record.finish(token_count=len(json.dumps(result)) // 4, success=True)

        except Exception as exc:
            record.finish(success=False)
            raise RuntimeError(f"[{self.AGENT_NAME}] Failed: {exc}") from exc
        finally:
            self._emit_telemetry(record)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _rank_resources(self, resources: list[dict], skill_gaps: list[str]) -> list[dict]:
        """Boost labs/videos and resources matching skill gaps."""
        type_weight = {"lab": 1.3, "video": 1.1, "article": 1.0}
        for r in resources:
            boost = type_weight.get(r.get("content_type", "article"), 1.0)
            topic_overlap = len(
                set(r.get("topics", [])) & set(g.replace(" ", "_") for g in skill_gaps)
            )
            r["_final_score"] = r.get("relevance_score", 0.5) * boost + topic_overlap * 0.1
        resources.sort(key=lambda x: x["_final_score"], reverse=True)
        return resources

    def _compose_demo_result(
        self, employee_id, role, cert_goal,
        resources, prereqs, missing_prereqs,
        alignment, gap_coverage,
    ) -> dict:
        curated_items = []
        for i, r in enumerate(resources, 1):
            curated_items.append({
                "rank": i,
                "document_id": r["document_id"],
                "title": r["title"],
                "content_type": r["content_type"],
                "summary": r["content"],
                "estimated_minutes": r.get("estimated_minutes", 60),
                "url": r.get("url", ""),
                "topics": r.get("topics", []),
                "difficulty": r.get("difficulty", "intermediate"),
                "relevance_score": r.get("relevance_score", 0.5),
                "citation": r["citation"],
                "why_recommended": (
                    f"Directly addresses {role} skill requirements for {cert_goal}. "
                    f"Topics covered: {', '.join(r.get('topics', [])[:3])}."
                ),
            })

        narrative = (
            f"**Learning Path for {role} targeting {cert_goal}**\n\n"
            f"Role-certification fit: {int(alignment['fit_score']*100)}% "
            f"({alignment['rationale']})\n\n"
            f"Skill gap coverage: {int(gap_coverage['coverage_ratio']*100)}% of your "
            f"identified gaps are addressed by this certification.\n\n"
        )
        if missing_prereqs:
            narrative += (
                "⚠️ **Missing Prerequisites**: "
                + ", ".join(p["certification_id"] for p in missing_prereqs)
                + " — complete these first.\n\n"
            )
        narrative += (
            f"**Recommended Resources ({len(curated_items)} items):**\n"
            + "\n".join(
                f"{i['rank']}. {i['title']} [{i['content_type']}] — "
                f"~{i['estimated_minutes']}min  {i['citation']}"
                for i in curated_items
            )
        )

        return {
            "agent": self.AGENT_NAME,
            "employee_id": employee_id,
            "role": role,
            "certification_goal": cert_goal,
            "role_fit_score": alignment["fit_score"],
            "skill_gap_coverage": gap_coverage,
            "missing_prerequisites": missing_prereqs,
            "curated_resources": curated_items,
            "narrative_summary": narrative + self._RAI_DISCLAIMER,
            "total_estimated_minutes": sum(
                r.get("estimated_minutes", 60) for r in resources
            ),
            "citations": [r["citation"] for r in resources],
        }

    def _compose_live_result(
        self, employee_id, role, cert_goal,
        resources, prereqs, missing_prereqs,
        alignment, gap_coverage,
    ) -> dict:
        """Compose result using a live Foundry agent call."""
        agent_id = self._create_or_get_agent(self._INSTRUCTIONS)
        prompt = json.dumps({
            "learner": {"employee_id": employee_id, "role": role},
            "certification_goal": cert_goal,
            "retrieved_resources": resources[:5],
            "missing_prerequisites": missing_prereqs,
            "alignment": alignment,
            "gap_coverage": gap_coverage,
        }, indent=2)

        response_text, token_count = self._run_thread(agent_id, prompt)
        return {
            "agent": self.AGENT_NAME,
            "employee_id": employee_id,
            "role": role,
            "certification_goal": cert_goal,
            "role_fit_score": alignment["fit_score"],
            "skill_gap_coverage": gap_coverage,
            "missing_prerequisites": missing_prereqs,
            "curated_resources": resources,
            "narrative_summary": response_text + self._RAI_DISCLAIMER,
            "citations": [r["citation"] for r in resources],
            "token_count": token_count,
        }

    def _apply_guardrails_to_result(self, result: dict) -> dict:
        result["narrative_summary"] = self._apply_guardrails(result["narrative_summary"])
        return result
