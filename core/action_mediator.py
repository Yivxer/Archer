"""Single authorization gate between semantic decisions and Hugo execution."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum

from core.turn_decision import ActionRequest, TurnDecision


class ActionDisposition(str, Enum):
    AUTO_EXECUTE = "AUTO_EXECUTE"
    REQUEST_CONFIRMATION = "REQUEST_CONFIRMATION"
    PROPOSE_ONLY = "PROPOSE_ONLY"
    DENY = "DENY"


@dataclass(frozen=True)
class MediationResult:
    disposition: ActionDisposition
    action: ActionRequest | None = None
    reason: str = ""
    authorization_source: str = "none"
    fingerprint: str = ""


_DIRECT_PUBLISH = re.compile(
    r"(?:帮我|请|麻烦|直接|现在|立刻|马上|给我|把|将|你).{0,30}(?:发布|部署|上线|发到|上传)"
    r"|^(?:发布|部署|上线|上传)"
)
_DELETE_ACTIONS = {"delete", "unpublish", "delete_and_deploy", "withdraw"}
_PUBLISH_ACTIONS = {"publish", "deploy", "redeploy"}


def _fingerprint(query: str, action: ActionRequest) -> str:
    raw = f"{query}\n{action.capability}\n{action.action}\n{action.target}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def mediate_turn(
    decision: TurnDecision, query: str, *, candidate_capabilities: set[str] | None = None,
) -> MediationResult:
    if decision.handling == "propose_action":
        return MediationResult(ActionDisposition.PROPOSE_ONLY, reason="model_proposal")
    if decision.handling != "execute_action" or not decision.action_requests:
        return MediationResult(ActionDisposition.DENY, reason="no_authorized_action")
    action = decision.action_requests[0]
    if candidate_capabilities is not None and action.capability not in candidate_capabilities:
        return MediationResult(ActionDisposition.DENY, action, "capability_not_candidate")
    if action.capability != "hugo_blog":
        return MediationResult(ActionDisposition.DENY, action, "capability_not_migrated")
    evidence = action.evidence.strip()
    if not evidence or evidence not in query:
        return MediationResult(ActionDisposition.REQUEST_CONFIRMATION, action, "missing_verbatim_evidence")
    fingerprint = _fingerprint(query, action)
    scoped_target = str(action.parameters.get("sourcePath") or action.parameters.get("target") or "")
    if scoped_target and scoped_target != action.target:
        return MediationResult(ActionDisposition.REQUEST_CONFIRMATION, action, "parameter_scope_expanded", "current_turn", fingerprint)
    if action.action in _DELETE_ACTIONS:
        return MediationResult(ActionDisposition.REQUEST_CONFIRMATION, action, "destructive_action", "current_turn", fingerprint)
    if action.action not in _PUBLISH_ACTIONS:
        return MediationResult(ActionDisposition.REQUEST_CONFIRMATION, action, "unknown_or_ambiguous_action", "current_turn", fingerprint)
    if not action.target or not _DIRECT_PUBLISH.search(evidence):
        return MediationResult(ActionDisposition.REQUEST_CONFIRMATION, action, "ambiguous_scope", "current_turn", fingerprint)
    return MediationResult(ActionDisposition.AUTO_EXECUTE, action, "explicit_current_turn_authorization", "current_turn", fingerprint)
