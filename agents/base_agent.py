"""
Base agent class providing Azure AI Foundry connection, telemetry, and shared utilities.
All five specialized agents inherit from this class.
"""
from __future__ import annotations

import os
import logging
import json
from abc import ABC, abstractmethod
from typing import Any
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Optional Azure SDK imports — gracefully degrade in demo / offline mode
# ---------------------------------------------------------------------------
try:
    from azure.ai.agents import AgentsClient
    from azure.identity import DefaultAzureCredential
    _AZURE_AVAILABLE = True
except ImportError:
    _AZURE_AVAILABLE = False
    logger.warning("azure-ai-agents not installed — running in demo mode")

try:
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry import trace
    _OT_AVAILABLE = True
except ImportError:
    _OT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Telemetry setup
# ---------------------------------------------------------------------------
_tracer = None

def _setup_telemetry() -> None:
    global _tracer
    conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if conn_str and _OT_AVAILABLE:
        try:
            configure_azure_monitor(connection_string=conn_str)
        except Exception as exc:
            logger.debug("Azure Monitor setup failed: %s", exc)
    if _OT_AVAILABLE:
        _tracer = trace.get_tracer("enterprise-learning-system")

_setup_telemetry()


class AgentCallRecord:
    """Lightweight telemetry record for a single agent invocation."""

    def __init__(self, agent_name: str, input_summary: str):
        self.agent_name = agent_name
        self.input_summary = input_summary
        self.started_at = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None
        self.token_count: int = 0
        self.success: bool = False
        self.reasoning_steps: list[str] = []

    def finish(self, token_count: int = 0, success: bool = True) -> None:
        self.finished_at = datetime.now(timezone.utc)
        self.token_count = token_count
        self.success = success

    @property
    def duration_ms(self) -> float:
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds() * 1000
        return 0.0

    def to_dict(self) -> dict:
        return {
            "agent": self.agent_name,
            "started_at": self.started_at.isoformat(),
            "duration_ms": round(self.duration_ms, 1),
            "tokens": self.token_count,
            "success": self.success,
            "input_summary": self.input_summary[:120],
            "reasoning_steps": self.reasoning_steps,
        }


class BaseAgent(ABC):
    """
    Abstract base class for all enterprise learning agents.

    Handles:
    - Azure AI Foundry AgentsClient lifecycle (azure-ai-agents SDK)
    - Telemetry (call records + optional OTel spans)
    - Input validation and Responsible AI output guardrails
    - Reasoning step logging
    - Graceful demo-mode fallback when Azure creds are unavailable
    """

    AGENT_NAME: str = "BaseAgent"
    AGENT_VERSION: str = "1.0"

    _RAI_DISCLAIMER = (
        "\n\n---\n*Responsible AI Notice: This content is AI-generated and intended "
        "to support learning. Always verify certification requirements against official "
        "Microsoft Learn documentation. Do not share personal or confidential data with AI systems.*"
    )

    _BLOCKED_PATTERNS = [
        "social security", "credit card", "password", "api key", "secret key",
    ]

    def __init__(self) -> None:
        self._client: Any = None
        self._agent_id: str | None = None
        self.call_records: list[AgentCallRecord] = []
        self._demo_mode = DEMO_MODE or not _AZURE_AVAILABLE
        self._model = os.getenv("AZURE_AI_MODEL_DEPLOYMENT", "gpt-4o")
        self._endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")

        if not self._demo_mode:
            self._init_azure_client()

    # ------------------------------------------------------------------
    # Azure client lifecycle
    # ------------------------------------------------------------------

    def _init_azure_client(self) -> None:
        """Initialize azure-ai-agents AgentsClient with DefaultAzureCredential."""
        try:
            credential = DefaultAzureCredential()
            self._client = AgentsClient(
                endpoint=self._endpoint,
                credential=credential,
            )
            logger.info("[%s] Azure AI Agents client initialized", self.AGENT_NAME)
        except Exception as exc:
            logger.warning(
                "[%s] Azure client init failed (%s) — falling back to demo mode",
                self.AGENT_NAME, exc,
            )
            self._demo_mode = True

    def _create_or_get_agent(self, instructions: str, tools: list | None = None) -> str:
        """Create a Foundry agent and return its ID. Cached after first call."""
        if self._agent_id:
            return self._agent_id
        agent = self._client.create_agent(
            model=self._model,
            name=self.AGENT_NAME,
            instructions=instructions,
            tools=tools or [],
        )
        self._agent_id = agent.id
        logger.info("[%s] Created Foundry agent: %s", self.AGENT_NAME, self._agent_id)
        return self._agent_id

    def _run_thread(self, agent_id: str, user_message: str) -> tuple[str, int]:
        """Create a thread, post a message, run it, return (response_text, token_count)."""
        thread = self._client.threads.create()
        self._client.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_message,
        )
        run = self._client.runs.create_and_process(
            thread_id=thread.id,
            agent_id=agent_id,
        )

        if str(run.status).lower() in ("failed", "cancelled", "expired"):
            error_detail = getattr(run, "last_error", "unknown error")
            raise RuntimeError(f"Agent run {run.status}: {error_detail}")

        # Use the convenience method to get the last assistant message text
        last_msg = self._client.messages.get_last_message_text_by_role(
            thread_id=thread.id, role="assistant"
        )
        response_text = last_msg.text.value if last_msg else ""

        # Extract token count from run usage dict
        usage = getattr(run, "usage", None) or {}
        if isinstance(usage, dict):
            token_count = usage.get("total_tokens", 0)
        else:
            token_count = getattr(usage, "total_tokens", 0)

        return response_text, int(token_count)

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def _validate_input(self, data: dict) -> None:
        serialized = json.dumps(data).lower()
        for pattern in self._BLOCKED_PATTERNS:
            if pattern in serialized:
                raise ValueError(
                    f"Input contains potentially sensitive data pattern '{pattern}'. "
                    "Please remove PII before submitting."
                )
        if not any(str(v).strip() for v in data.values()):
            raise ValueError("Input cannot be empty.")

    # ------------------------------------------------------------------
    # Output guardrails
    # ------------------------------------------------------------------

    def _apply_guardrails(self, text: str) -> str:
        lower = text.lower()
        for pattern in self._BLOCKED_PATTERNS:
            if pattern in lower:
                logger.warning("[%s] Guardrail triggered: '%s' in output", self.AGENT_NAME, pattern)
                text = text.replace(pattern, "[REDACTED]")
        return text

    def _add_rai_disclaimer(self, text: str) -> str:
        return text + self._RAI_DISCLAIMER

    # ------------------------------------------------------------------
    # Reasoning step logging
    # ------------------------------------------------------------------

    def _log_step(self, record: AgentCallRecord, step: str) -> None:
        record.reasoning_steps.append(step)
        logger.info("[%s] STEP: %s", self.AGENT_NAME, step)

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def _start_record(self, input_summary: str) -> AgentCallRecord:
        record = AgentCallRecord(self.AGENT_NAME, input_summary)
        self.call_records.append(record)
        return record

    def _emit_telemetry(self, record: AgentCallRecord) -> None:
        data = record.to_dict()
        logger.info("[TELEMETRY] %s", json.dumps(data))
        if _OT_AVAILABLE and _tracer:
            with _tracer.start_as_current_span(f"{self.AGENT_NAME}.run") as span:
                span.set_attribute("agent.name", self.AGENT_NAME)
                span.set_attribute("agent.tokens", record.token_count)
                span.set_attribute("agent.duration_ms", record.duration_ms)
                span.set_attribute("agent.success", record.success)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, **kwargs) -> dict:
        """Execute agent logic and return structured result dict."""
        ...

    def cleanup(self) -> None:
        """Delete the Foundry agent to free resources."""
        if self._client and self._agent_id:
            try:
                self._client.delete_agent(self._agent_id)
                logger.info("[%s] Deleted agent %s", self.AGENT_NAME, self._agent_id)
            except Exception as exc:
                logger.debug("[%s] Cleanup error: %s", self.AGENT_NAME, exc)
            self._agent_id = None
