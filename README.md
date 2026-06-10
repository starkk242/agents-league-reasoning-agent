# Enterprise Learning & Certification Management System

**Microsoft Agents League Hackathon 2026 — Reasoning Agents Track (Battle #2)**

A production-grade multi-agent system that manages internal team certification programs using Microsoft Azure AI Foundry, Foundry IQ, Fabric IQ, and Work IQ.

---

## Architecture

```
  User Input (role + cert goal)
         │
         ▼
┌─────────────────────────┐   Foundry IQ    ┌──────────────────────┐
│  LearningPathCurator    │◄───────────────►│  Knowledge Base       │
│  Agent                  │   Fabric IQ     │  (learning_content)  │
│  • Cited content        │◄───────────────►│  Semantic Graph       │
└──────────┬──────────────┘                 └──────────────────────┘
           │ curated_resources
           ▼
┌─────────────────────────┐   Fabric IQ    ┌──────────────────────┐
│  StudyPlanGenerator     │◄──────────────►│  Hours Budget         │
│  Agent                  │   Work IQ      │  Role Alignment       │
│  • Weekly schedule      │◄──────────────►│  Meeting Load         │
└──────────┬──────────────┘                └──────────────────────┘
           │
           ▼
┌─────────────────────────┐   Work IQ      ┌──────────────────────┐
│  EngagementAgent        │◄──────────────►│  Focus Hours          │
│  • Adaptive reminders   │                │  Meeting Hours        │
│  • Manager escalation   │                │  Preferred Slot       │
└──────────┬──────────────┘                └──────────────────────┘
           │
           ▼
┌─────────────────────────┐   Foundry IQ   ┌──────────────────────┐
│  AssessmentAgent        │◄──────────────►│  Grounded Questions   │
│  • Cited questions      │                │  w/ Citations         │
│  • Score + feedback     │                └──────────────────────┘
└──────────┬──────────────┘
           ├── PASS ──► Next cert recommendation
           └── FAIL ──► Loop back + remediation

┌─────────────────────────┐
│  ManagerInsightsAgent   │  (always-on dashboard)
│  • Team completion      │
│  • At-risk detection    │
│  • Skill gap analysis   │
└─────────────────────────┘
```

---

## Agents

| Agent | Responsibility | IQ Integration |
|-------|---------------|----------------|
| **LearningPathCuratorAgent** | Retrieves grounded learning content mapped to role + certification, cites every source | Foundry IQ (retrieval), Fabric IQ (prerequisites, role fit) |
| **StudyPlanGeneratorAgent** | Converts curated content into a week-by-week study schedule respecting work availability | Fabric IQ (hours budget, cert level), Work IQ (meeting load, focus hours) |
| **EngagementAgent** | Sends adaptive reminders timed to preferred learning slot; escalates to manager on 2+ failures or 14+ days inactive | Work IQ (meeting_hours, focus_hours, preferred_learning_slot) |
| **AssessmentAgent** | Generates cited practice questions from knowledge base, scores answers, gives targeted feedback | Foundry IQ (grounded questions with citations) |
| **ManagerInsightsAgent** | Aggregates team completion rates, readiness scores, at-risk learners, skill coverage gaps | employees.json, team_progress.json, certifications.json |

---

<!-- DEMO_VIDEO_URL -->

## Demo Output (Live Run — Azure AI Foundry + GPT-4o)

```
╭────────────────────────── Demo Mode ──────────────────────────╮
│  Microsoft Agents League 2026 — Reasoning Agents Track        │
│  Enterprise Learning & Certification Management System        │
│  Powered by: Azure AI Foundry · Foundry IQ · Fabric IQ · Work IQ │
╰───────────────────────────────────────────────────────────────╯

  ➤  User Input ─────────────────────▶ LearningPathCuratorAgent   (19.6s, GPT-4o)
  ➤  LearningPathCuratorAgent ───────▶ StudyPlanGeneratorAgent     (24.1s, GPT-4o)
  ➤  StudyPlanGeneratorAgent ────────▶ EngagementAgent             (11.5s, GPT-4o)
  ➤  EngagementAgent ────────────────▶ AssessmentAgent             (19.5s, GPT-4o)
  ➤  Manager Query ──────────────────▶ ManagerInsightsAgent        (13.3s, GPT-4o)

  Assessment Score: 75%  |  Verdict: PASS — Recommend booking exam
  ✓ Cert complete! Next recommended: AZ-104

All 5 agents executed successfully. Check logs for telemetry data.
```

Each agent logs its full reasoning chain (6-7 steps per agent) and every response cites its Foundry IQ knowledge base source.

## Prerequisites

- Python 3.9+
- Azure subscription with AI Foundry project (optional — demo mode works without it)
- Azure CLI authenticated (for live mode)

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/starkk242/agents-league-reasoning-agent
cd agents-league-reasoning-agent

# 2. Create virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — for live Azure mode:
#   AZURE_AI_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
#   AZURE_AI_MODEL_DEPLOYMENT=gpt-4o
#   DEMO_MODE=false
# For local testing without Azure credentials:
#   DEMO_MODE=true

# 5. Authenticate with Azure (live mode only)
az login
az account set --subscription "<your subscription>"
```

---

## Running the Demo

### Full end-to-end demo (all 5 agents)

```bash
python main.py --demo
```

### Run for a specific employee

```bash
python main.py --employee EMP007 --cert AZ-204
```

### Manager insights dashboard

```bash
python main.py --manager
python main.py --manager --dept "Engineering"
```

### Practice assessment

```bash
python main.py --assess EMP005 AI-102
```

### Run evaluation harness (all 5 test scenarios)

```bash
python evaluation/eval_runner.py
```

---

## Project Structure

```
agents-league-reasoning-agent/
├── main.py                      # Orchestrator + CLI (python main.py --demo)
├── hosted_agent.py              # Foundry Agent Service endpoint
├── requirements.txt
├── .env.example
├── agents/
│   ├── base_agent.py            # Azure Foundry connection, telemetry, guardrails
│   ├── learning_path_curator.py # Stage 1: Foundry IQ content retrieval
│   ├── study_plan_generator.py  # Stage 2: Fabric IQ + Work IQ scheduling
│   ├── engagement_agent.py      # Stage 3: Work IQ adaptive reminders
│   ├── assessment_agent.py      # Stage 4: Foundry IQ grounded assessment
│   └── manager_insights.py      # Stage 5: Team analytics dashboard
├── data/
│   ├── employees.json           # 10 synthetic employees with Work IQ signals
│   ├── certifications.json      # 8 Microsoft certifications
│   ├── learning_content.json    # 20 knowledge base entries (Foundry IQ source)
│   ├── team_progress.json       # Team certification progress snapshot
│   └── fabric_iq_model.json     # Semantic graph (prerequisites, role alignment)
├── tools/
│   ├── knowledge_retrieval.py   # Foundry IQ wrapper (local + Azure AI Search)
│   ├── work_iq_signals.py       # Work IQ data access + reminder scheduling
│   └── fabric_iq_semantic.py    # Fabric IQ semantic graph queries
├── evaluation/
│   ├── eval_runner.py           # Automated evaluation harness
│   └── test_scenarios.json      # 5 end-to-end test scenarios
└── docs/
    ├── architecture.md          # Full architecture + agent flow diagram
    └── demo_script.md           # Step-by-step demo walkthrough
```

---

## Synthetic Data

All data is fully synthetic — no real PII.

- **10 employees** across Engineering, Security, Data & Analytics, Business Applications, IT Operations
- **8 Microsoft certifications**: AZ-204, AZ-400, AZ-900, DP-100, SC-900, AI-102, PL-400, MS-900
- **20 knowledge base entries** mapped to certifications (Foundry IQ source)
- **Fabric IQ semantic graph**: prerequisite chains, role-cert fit scores, skill-cert coverage

---

## Key Design Decisions

### Grounded Retrieval (Foundry IQ)
Every resource recommendation and assessment question is retrieved from the knowledge base, not generated from model memory. Citations are in the format `[Source: <doc_id> — "<title>"]`.

### Semantic Prerequisites (Fabric IQ)
The `fabric_iq_model.json` encodes certification prerequisites, role-skill alignment scores, and canonical learning paths as a semantic graph — not hardcoded rules. The `StudyPlanGeneratorAgent` queries this to calculate realistic completion timelines.

### Work-Aware Scheduling (Work IQ)
`EngagementAgent` and `StudyPlanGeneratorAgent` consume `meeting_hours_per_week`, `focus_hours_per_week`, and `preferred_learning_slot` to personalize reminder timing and study session sizes.

### Adaptive Escalation Loop
If a learner fails 2+ assessments or is inactive for 14+ days, `EngagementAgent` automatically generates a manager escalation message with Work IQ context and actionable recommendations — not just a flag.

### Responsible AI
- Input validation rejects PII-like patterns before any agent processes data
- Output guardrails scan all responses for sensitive data leakage
- Every agent output includes a Responsible AI disclaimer
- No real employee data used anywhere in the system

---

## Evaluation Harness

5 automated test scenarios covering:
1. Standard learner flow (AZ-204, Software Engineer)
2. High-completion assessment pass (AI-102, AI/ML Engineer)
3. At-risk escalation trigger (PL-400, high meeting load)
4. Manager insights dashboard (Engineering department)
5. Prerequisite detection (DP-100, Data Scientist)

```bash
python evaluation/eval_runner.py
python evaluation/eval_runner.py --scenario SC003   # specific scenario
python evaluation/eval_runner.py --output results.json
```

---

## Telemetry & Observability

Every agent call logs:
- Agent name + timestamp
- Duration (ms)
- Token count estimate
- Reasoning steps
- Success/failure

Configure Azure Monitor:
```env
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=<key>;...
```

---

## Hackathon Submission

- **Track**: Reasoning Agents (Battle #2)
- **Platform**: Microsoft Azure AI Foundry
- **Deadline**: June 14, 2026
- **Team**: starkk242

---

## License

MIT License — see [LICENSE](LICENSE)
