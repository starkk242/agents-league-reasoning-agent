# Architecture

## System Overview

The Enterprise Learning System is a multi-agent reasoning pipeline built on Microsoft Azure AI Foundry. Five specialized agents collaborate to deliver personalized certification learning experiences at enterprise scale.

## Agent Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ENTERPRISE LEARNING SYSTEM                               │
│                  Microsoft Agents League 2026                               │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐
  │  User Input  │  (role + certification goal)
  └──────┬───────┘
         │
         ▼
┌─────────────────────────┐      ┌──────────────────────────┐
│  LearningPathCurator    │◄────►│  Foundry IQ              │
│  Agent                  │      │  Knowledge Base           │
│                         │      │  (learning_content.json) │
│  • Retrieves grounded   │      └──────────────────────────┘
│    content w/ citations │
│  • Checks prerequisites │      ┌──────────────────────────┐
│  • Role fit scoring     │◄────►│  Fabric IQ               │
└──────────┬──────────────┘      │  Semantic Model           │
           │                     │  (fabric_iq_model.json)  │
           │ curated_resources   └──────────────────────────┘
           ▼
┌─────────────────────────┐      ┌──────────────────────────┐
│  StudyPlanGenerator     │◄────►│  Fabric IQ               │
│  Agent                  │      │  Hours Budget Query       │
│                         │      └──────────────────────────┘
│  • Weekly schedule      │
│  • Hours budget from    │      ┌──────────────────────────┐
│    Work IQ signals      │◄────►│  Work IQ Signals         │
│  • Milestone checkpoints│      │  (employees.json)        │
└──────────┬──────────────┘      └──────────────────────────┘
           │
           │ study plan + schedule
           ▼
┌─────────────────────────┐      ┌──────────────────────────┐
│  EngagementAgent        │◄────►│  Work IQ Signals         │
│                         │      │  meeting_hours,          │
│  • Adaptive reminders   │      │  focus_hours,            │
│  • Work-context timing  │      │  preferred_slot          │
│  • ESCALATION to manager│      └──────────────────────────┘
│    if 2+ fails / 14d    │
│    inactive             │
└──────────┬──────────────┘
           │
           │ reminder + escalation
           ▼
┌─────────────────────────┐      ┌──────────────────────────┐
│  AssessmentAgent        │◄────►│  Foundry IQ              │
│                         │      │  Knowledge Base           │
│  • Grounded questions   │      │  (cited questions)       │
│  • Scores + feedback    │      └──────────────────────────┘
│  • Readiness verdict    │
└──────────┬──────────────┘
           │
           ├──── PASS (≥75%) ────► Recommend next cert
           │
           └──── FAIL (<75%) ────► Loop back to StudyPlanGenerator
                                   (with remediation resources)

                    ┌───────────────────────────┐
                    │  ManagerInsightsAgent     │  (always-on, query any time)
                    │                           │
                    │  • Team completion rates  │◄── team_progress.json
                    │  • At-risk identification │◄── employees.json
                    │  • Skill coverage gaps    │
                    │  • Actionable insights    │
                    └───────────────────────────┘
```

## Data Flow

```
employees.json ──────────────────────────────► EngagementAgent (Work IQ)
                                             ► StudyPlanGeneratorAgent
                                             ► ManagerInsightsAgent

certifications.json ─────────────────────────► FabricIQ semantic queries
                                             ► LearningPathCuratorAgent

learning_content.json (Foundry IQ KB) ───────► LearningPathCuratorAgent
                                             ► AssessmentAgent

fabric_iq_model.json ────────────────────────► StudyPlanGeneratorAgent
                                             ► LearningPathCuratorAgent

team_progress.json ──────────────────────────► EngagementAgent
                                             ► ManagerInsightsAgent
```

## Component Responsibilities

| Component | Responsibility | Key Integrations |
|-----------|---------------|-----------------|
| `LearningPathCuratorAgent` | Retrieve + rank learning content for role/cert | Foundry IQ, Fabric IQ |
| `StudyPlanGeneratorAgent` | Build week-by-week schedule | Fabric IQ (hours), Work IQ (availability) |
| `EngagementAgent` | Personalized reminders + manager escalation | Work IQ (signals) |
| `AssessmentAgent` | Generate questions, score, give feedback | Foundry IQ (grounded Qs) |
| `ManagerInsightsAgent` | Team analytics dashboard | All data sources |
| `tools/knowledge_retrieval.py` | Foundry IQ wrapper (local + Azure AI Search) | learning_content.json |
| `tools/fabric_iq_semantic.py` | Semantic graph queries | fabric_iq_model.json |
| `tools/work_iq_signals.py` | Work context signals | employees.json |

## Adaptive Loop

When a learner fails the assessment twice:
1. `EngagementAgent` detects `failed_assessment_count >= 2`
2. Escalation message sent to manager with Work IQ context
3. `AssessmentAgent` returns `readiness.remediation_resources` (cited)
4. Orchestrator loops back to `StudyPlanGeneratorAgent` with targeted resources

## Azure AI Foundry Integration Points

```
Azure AI Project ──► AIProjectClient (azure.ai.projects)
    ├── Agents API ──► Per-agent create/run/delete lifecycle
    ├── Foundry IQ ──► Azure AI Search index (learning_content.json)
    └── Telemetry ──► Azure Monitor + OpenTelemetry

Azure Identity ──► DefaultAzureCredential (managed identity in prod)
```

## Responsible AI Design

- All agent outputs include Responsible AI disclaimer
- Input validation rejects PII-like patterns before processing
- Output guardrails scan for sensitive data leakage
- All generated questions and recommendations cite knowledge base sources
- No real employee PII used — fully synthetic dataset
