"""Canonical governed reasoning service boundary."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from governed_reasoning.authority import inspect_authority
from governed_reasoning.challenge import (
    normalize_challenge as normalize_challenge_artifact,
)
from governed_reasoning.contracts import (
    validate_artifact as validate_reasoning_artifact,
)
from governed_reasoning.decision import (
    normalize_decision as normalize_decision_artifact,
)
from governed_reasoning.planning import normalize_plan as normalize_plan_artifact
from governed_reasoning.recovery import ReasoningRecovery
from governed_reasoning.transactions import ReasoningTransactions


class GovernedReasoningService:
    """Keep future CLI and MCP adapters on one transaction implementation."""

    def __init__(
        self,
        agent_root: Path,
        *,
        authority_inspector: Callable[[Path], dict[str, Any]] = inspect_authority,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        arguments = {} if now is None else {"now": now}
        self.transactions = ReasoningTransactions(agent_root, authority_inspector, **arguments)
        self.recovery = ReasoningRecovery(agent_root, authority_inspector, **arguments)

    def validate_artifact(self, kind: str, artifact: Any) -> dict[str, Any]:
        reasons = validate_reasoning_artifact(kind, artifact)
        return {"ok": not reasons, "reason_codes": reasons}

    def normalize_plan(
        self,
        request: Any,
        policy: Any,
        snapshot: dict[str, Any],
        draft: Any,
        **authority: Any,
    ) -> dict[str, Any]:
        return normalize_plan_artifact(request, policy, snapshot, draft, **authority)

    def normalize_challenge(
        self,
        request: Any,
        plan: Any,
        policy: Any,
        draft: Any,
        **authority: Any,
    ) -> dict[str, Any]:
        return normalize_challenge_artifact(request, plan, policy, draft, **authority)

    def normalize_decision(
        self,
        request: Any,
        plan: Any,
        challenge: Any,
        policy: Any,
        draft: Any,
        snapshot: dict[str, Any],
        **authority: Any,
    ) -> dict[str, Any]:
        return normalize_decision_artifact(
            request,
            plan,
            challenge,
            policy,
            draft,
            snapshot,
            **authority,
        )

    def plan_receipt(
        self,
        kind: str,
        receipt: Any,
        source_receipt_ids: list[str] | None = None,
        *,
        expiry_seconds: int = 900,
    ) -> dict[str, Any]:
        return self.transactions.plan(kind, receipt, source_receipt_ids or [], expiry_seconds)

    def apply_receipt(self, plan_id: str, *, confirm: bool = False) -> dict[str, Any]:
        return self.transactions.apply(plan_id, confirm)

    def recover_receipt(
        self,
        transaction_id: str,
        *,
        confirm: bool = False,
    ) -> dict[str, Any]:
        return self.recovery.recover(transaction_id, confirm=confirm)
