"""
AssessmentAgent
Generates grounded practice questions with cited sources, evaluates learner
readiness, scores responses, and decides pass/fail with feedback.
"""
from __future__ import annotations

import json
import random
from typing import Any

from agents.base_agent import BaseAgent
from tools.knowledge_retrieval import FoundryIQKnowledgeRetrieval


# Passing threshold as a percentage
PASS_THRESHOLD = 75.0


class AssessmentAgent(BaseAgent):
    AGENT_NAME = "AssessmentAgent"

    _INSTRUCTIONS = """You are a Microsoft certification assessment expert.

Your job:
1. Generate practice questions grounded in the Foundry IQ knowledge base
2. Each question must cite its source document
3. Evaluate learner answers and provide detailed feedback
4. Score the assessment and determine readiness for the real exam
5. Identify knowledge gaps from wrong answers and map them to learning resources

Rules:
- All questions must be derived from cited knowledge base content
- Provide correct answer + explanation + source citation for every question
- Score: ≥75% = PASS, recommend booking exam; <75% = FAIL, loop back to study plan
- Feedback must be constructive and specific, not just 'correct' or 'wrong'
- Flag if the learner is exam-ready or needs targeted remediation"""

    def __init__(self) -> None:
        super().__init__()
        self._kb = FoundryIQKnowledgeRetrieval(demo_mode=self._demo_mode)

    def run(
        self,
        employee_id: str,
        certification_goal: str,
        learner_answers: dict[str, str] | None = None,
        question_count: int = 5,
    ) -> dict[str, Any]:
        """
        Generate assessment questions and/or evaluate provided answers.

        If learner_answers is None: returns a set of practice questions.
        If learner_answers is provided: scores them and returns feedback.
        """
        self._validate_input({
            "employee_id": employee_id,
            "certification_goal": certification_goal,
        })

        record = self._start_record(f"{employee_id} → {certification_goal}")

        try:
            # Step 1: Retrieve grounded content
            self._log_step(record, "Retrieving knowledge base content from Foundry IQ")
            resources = self._kb.get_by_certification(certification_goal)
            if not resources:
                resources = self._kb.retrieve(certification_goal, top_k=question_count)

            if not resources:
                raise ValueError(
                    f"No knowledge base content found for {certification_goal}. "
                    "Cannot generate grounded assessment."
                )

            # Step 2: Generate questions
            self._log_step(record, f"Generating {question_count} grounded questions from knowledge base")
            questions = self._generate_questions(resources, question_count)

            if learner_answers is None:
                # Return questions only
                result = {
                    "agent": self.AGENT_NAME,
                    "employee_id": employee_id,
                    "certification_goal": cert_goal,
                    "assessment_type": "question_generation",
                    "questions": questions,
                    "instructions": (
                        "Answer each question by providing the answer key (e.g., 'A', 'B', 'C', 'D'). "
                        "Return your answers as a dict mapping question_id → answer."
                    ),
                }
                record.finish(success=True)
                return result

            # Step 3: Score answers
            self._log_step(record, "Scoring learner answers against answer key")
            scored = self._score_answers(questions, learner_answers)

            # Step 4: Compute readiness
            self._log_step(record, "Computing readiness score and generating feedback")
            score_pct = scored["score_percentage"]
            passed = score_pct >= PASS_THRESHOLD
            readiness = self._compute_readiness(scored, resources)

            cert_goal = certification_goal
            result = {
                "agent": self.AGENT_NAME,
                "employee_id": employee_id,
                "certification_goal": cert_goal,
                "assessment_type": "scored",
                "questions": questions,
                "scored_answers": scored["answers"],
                "score_percentage": score_pct,
                "passed": passed,
                "pass_threshold": PASS_THRESHOLD,
                "verdict": "PASS — Recommend booking exam" if passed else "FAIL — Return to study plan",
                "readiness": readiness,
                "feedback_summary": self._generate_feedback(scored, passed, cert_goal),
                "citations": list({q["citation"] for q in questions}),
            }
            result["feedback_summary"] = self._apply_guardrails(result["feedback_summary"])
            result["feedback_summary"] += self._RAI_DISCLAIMER

            # Live mode: GPT-4o generates richer, personalized feedback
            if not self._demo_mode:
                self._log_step(record, "Calling GPT-4o to generate detailed assessment feedback")
                result, tokens = self._enhance_feedback_live(result, scored, passed, cert_goal)
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
    # Question generation
    # ------------------------------------------------------------------

    def _generate_questions(self, resources: list[dict], count: int) -> list[dict]:
        """Generate multiple-choice questions grounded in knowledge base items."""
        templates = [
            ("Which of the following best describes {topic}?", "definition"),
            ("When implementing {topic}, which approach is recommended?", "best_practice"),
            ("What is the primary benefit of using {topic} in Azure?", "benefit"),
            ("Which Azure service should you use when your requirement involves {topic}?", "service_selection"),
            ("In the context of {cert_id}, {topic} is primarily used for?", "use_case"),
        ]

        questions = []
        used_resources = resources[:min(count, len(resources))]
        random.seed(42)  # deterministic for demo

        for i, res in enumerate(used_resources):
            topic = (res.get("topics") or ["Azure services"])[0].replace("_", " ")
            cert_id = res.get("certification_id", "")
            template, q_type = templates[i % len(templates)]
            question_text = template.format(topic=topic, cert_id=cert_id)

            correct_idx = random.randint(0, 3)
            options = self._generate_options(res, topic, correct_idx)
            answer_keys = ["A", "B", "C", "D"]

            questions.append({
                "question_id": f"Q{i+1:02d}",
                "question": question_text,
                "options": {answer_keys[j]: opt for j, opt in enumerate(options)},
                "correct_answer": answer_keys[correct_idx],
                "explanation": (
                    f"Based on: {res.get('summary', '')} "
                    f"The correct answer addresses {topic} as covered in the knowledge base."
                ),
                "citation": (
                    res.get("citation")
                    or f"[Source: learning_content.json › {res.get('id', '')} — \"{res.get('title', '')}\"]"
                ),
                "source_title": res.get("title", ""),
                "difficulty": res.get("difficulty", "intermediate"),
                "topic": topic,
                "question_type": q_type,
            })

        return questions

    def _generate_options(self, resource: dict, topic: str, correct_idx: int) -> list[str]:
        """Generate plausible MCQ options with one correct answer."""
        summary_excerpt = (resource.get("summary") or "")[:100]
        correct = f"Use {topic} as described in the official guidance: {summary_excerpt[:60]}..."

        distractors = [
            f"Avoid {topic} and use a manual configuration instead",
            f"Use {topic} only in production, not in development environments",
            f"Replace {topic} with an on-premises equivalent for compliance reasons",
        ]

        options = distractors[:]
        options.insert(correct_idx, correct)
        return options[:4]

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_answers(
        self, questions: list[dict], learner_answers: dict[str, str]
    ) -> dict:
        total = len(questions)
        correct_count = 0
        answers = []

        for q in questions:
            qid = q["question_id"]
            learner = learner_answers.get(qid, "").upper().strip()
            correct = q["correct_answer"]
            is_correct = learner == correct

            if is_correct:
                correct_count += 1

            answers.append({
                "question_id": qid,
                "question": q["question"],
                "learner_answer": learner or "(not answered)",
                "correct_answer": correct,
                "is_correct": is_correct,
                "explanation": q["explanation"],
                "citation": q["citation"],
                "topic": q["topic"],
            })

        return {
            "total_questions": total,
            "correct": correct_count,
            "score_percentage": round((correct_count / max(total, 1)) * 100, 1),
            "answers": answers,
        }

    def _compute_readiness(self, scored: dict, resources: list[dict]) -> dict:
        wrong = [a for a in scored["answers"] if not a["is_correct"]]
        weak_topics = list({a["topic"] for a in wrong})

        remediation = []
        for topic in weak_topics:
            matching = [
                r for r in resources
                if topic.replace(" ", "_") in r.get("topics", [])
            ]
            for r in matching[:2]:
                remediation.append({
                    "topic": topic,
                    "resource_id": r.get("id", ""),
                    "title": r.get("title", ""),
                    "citation": r.get("citation", ""),
                })

        return {
            "score_percentage": scored["score_percentage"],
            "weak_topics": weak_topics,
            "remediation_resources": remediation,
            "exam_ready": scored["score_percentage"] >= PASS_THRESHOLD,
        }

    def _generate_feedback(self, scored: dict, passed: bool, cert_goal: str) -> str:
        score = scored["score_percentage"]
        wrong = [a for a in scored["answers"] if not a["is_correct"]]

        if passed:
            fb = (
                f"Congratulations! You scored {score:.0f}% on the {cert_goal} practice assessment — "
                f"above the {PASS_THRESHOLD:.0f}% passing threshold. "
                f"You are ready to schedule your certification exam. "
                f"Review any weak areas before exam day.\n\n"
            )
        else:
            fb = (
                f"You scored {score:.0f}% on the {cert_goal} practice assessment "
                f"(passing threshold: {PASS_THRESHOLD:.0f}%). "
                f"You need to revisit {len(wrong)} topic areas before attempting the exam.\n\n"
            )
            fb += "**Areas requiring further study:**\n"
            for a in wrong:
                fb += (
                    f"- **{a['topic']}**: Your answer: {a['learner_answer']} | "
                    f"Correct: {a['correct_answer']}\n"
                    f"  {a['explanation']}\n"
                    f"  {a['citation']}\n"
                )

        return fb

    def _enhance_feedback_live(self, result: dict, scored: dict, passed: bool, cert_goal: str) -> tuple[dict, int]:
        """Call GPT-4o for personalized, cited assessment feedback."""
        try:
            agent_id = self._create_or_get_agent(self._INSTRUCTIONS)
            wrong = [a for a in scored["answers"] if not a["is_correct"]]
            citations = "\n".join(result.get("citations", [])[:5])
            prompt = (
                f"Provide detailed assessment feedback for {cert_goal}:\n"
                f"Score: {scored['score_percentage']:.0f}% ({'PASS' if passed else 'FAIL'}, threshold: {PASS_THRESHOLD:.0f}%)\n"
                f"Correct: {scored['correct']}/{scored['total_questions']}\n\n"
                + (
                    "Incorrect answers and topics to improve:\n"
                    + "\n".join(f"- {a['topic']}: answered {a['learner_answer']}, correct was {a['correct_answer']}" for a in wrong)
                    + "\n\n" if wrong else "All answers correct!\n\n"
                )
                + f"Knowledge base citations:\n{citations}\n\n"
                + "Provide: (1) specific study recommendations for weak topics citing the sources above, "
                "(2) a confidence assessment for exam readiness, "
                "(3) concrete next steps. Keep it encouraging but honest."
            )
            response_text, token_count = self._run_thread(agent_id, prompt)
            if response_text:
                result["feedback_summary"] = self._apply_guardrails(response_text) + self._RAI_DISCLAIMER
            return result, token_count
        except Exception as exc:
            logger.warning("[%s] Live feedback enhancement failed: %s", self.AGENT_NAME, exc)
            return result, 0
