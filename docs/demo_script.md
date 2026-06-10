# Demo Script

## Microsoft Agents League 2026 — Reasoning Agents Track
### Enterprise Learning & Certification Management System

---

## Prerequisites

```bash
cd agents-league-reasoning-agent
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set DEMO_MODE=true for local demo (no Azure credentials needed)
```

---

## Demo Walkthrough (10 minutes)

### 1. Full End-to-End Demo (5 min)

```bash
python main.py --demo
```

**What to narrate:**

- The system chains 5 agents automatically
- Watch for the agent handoff arrows: `LearningPathCuratorAgent ──► StudyPlanGeneratorAgent ──► ...`
- Each agent prints its reasoning steps in real time
- The colored output shows which agent is active

**Key moments to highlight:**

1. **LearningPathCuratorAgent** — "Notice the citations on every resource: `[Source: LC011 — 'Azure OpenAI Service: GPT-4 Integration Patterns']`. This is grounded retrieval from the Foundry IQ knowledge base."

2. **StudyPlanGeneratorAgent** — "The plan respects Sam's Work IQ signals: 9h/week in meetings, afternoon preferred slot. It calculates the exact number of weeks based on remaining hours."

3. **EngagementAgent** — "Sam has been active recently so no escalation. But notice the reminder is timed to his afternoon slot with 45-minute sessions."

4. **AssessmentAgent** — "Every practice question cites its source. If Sam fails, the system automatically surfaces the specific resources to remediate the weak topics."

5. **ManagerInsightsAgent** — "The dashboard shows which engineers are at risk, why (high meeting load, low scores), and what to do about it."

---

### 2. At-Risk Escalation Demo (2 min)

```bash
python main.py --employee EMP006 --cert PL-400
```

**What to show:**

- Riley Johnson has 18h/week in meetings (high engagement risk)
- Only 30% complete, last active June 1st
- EngagementAgent should trigger **manager escalation**
- Escalation message includes Work IQ data: meeting hours, focus hours, risk factors

**Narrate:** "This is the adaptive loop in action. The system detected that Riley is at risk — not just from inactivity but from structural causes. The escalation to the manager includes actionable recommendations, not just a flag."

---

### 3. Manager Insights Dashboard (2 min)

```bash
python main.py --manager --dept "Engineering"
```

**What to show:**

- Team completion distribution (bar chart in ASCII)
- Certification readiness scores per cert domain
- At-risk learner list with root causes
- Skill coverage gaps (which domains the team is missing)
- Structural recommendations (meeting audit, cohort learning)

---

### 4. Targeted Assessment (1 min)

```bash
python main.py --assess EMP005 AI-102
```

**What to show:**

- Casey Thompson (AI/ML Engineer) at 88% completion
- Assessment questions are grounded with citations
- Score ≥75% → PASS → next cert recommendation appears

---

## Architecture Highlight (if asked)

Point to `docs/architecture.md` for the full ASCII flow diagram.

Key differentiators to mention:

1. **Foundry IQ grounding**: Every resource and question cites its source document — no hallucinated recommendations
2. **Fabric IQ semantic graph**: Prerequisites and role-skill alignment from a structured knowledge graph, not hardcoded rules
3. **Work IQ personalization**: Reminders and study windows adapted to real work signals — meeting load, focus time, preferred slot
4. **Adaptive loop**: Fail twice → manager escalation → remediation loop, all automated
5. **Responsible AI**: Input validation, output guardrails, RAI disclaimer on every output

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: rich` | `pip install rich` |
| `ModuleNotFoundError: azure` | `pip install -r requirements.txt` |
| Azure credential error | Set `DEMO_MODE=true` in `.env` |
| `Employee not found` | Use valid IDs: EMP001–EMP010 |
| `No content for cert` | Use: AZ-204, AZ-400, AZ-900, DP-100, SC-900, AI-102, PL-400, MS-900 |
