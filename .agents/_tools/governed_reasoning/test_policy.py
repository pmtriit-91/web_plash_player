#!/usr/bin/env python3
"""Focused acceptance for governed stop policy."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))

from governed_reasoning.policy import escalation_metrics, resolve_disposition
from governed_reasoning.test_planning import fixtures, hashed


def main() -> None:
    _, policy, _, _ = fixtures()
    authority = {"disposition": "proceed", "reason_codes": ["AUTHORITY_VALID"]}
    run = lambda pol=policy, auth=authority, challenge="proceed", confidence="high", retry=0: resolve_disposition(pol, auth, challenge, confidence=confidence, retry_budget=retry)
    cases = []
    check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    check("valid-policy-proceeds", run()["disposition"] == "proceed")
    check("authority-block-preserved", run(auth={"disposition": "block", "reason_codes": ["CONSTITUTION_CONFLICT"]})["reason_codes"] == ["CONSTITUTION_CONFLICT"])
    check("authority-escalation-preserved", run(auth={"disposition": "escalate", "reason_codes": ["OWNER_INPUT_REQUIRED"]})["disposition"] == "escalate")
    check("challenge-block-dominates-escalation", run(auth={"disposition": "escalate", "reason_codes": ["OWNER_INPUT_REQUIRED"]}, challenge="block")["disposition"] == "block")
    check("challenge-escalates", run(challenge="escalate")["disposition"] == "escalate")
    check("challenge-blocks", run(challenge="block")["disposition"] == "block")
    check("low-confidence-escalates", run(confidence="low")["reason_codes"] == ["LOW_CONFIDENCE"])
    strict = copy.deepcopy(policy); strict["risk"]["low_confidence"] = "block"; hashed(strict)
    check("restrictive-low-confidence-blocks", run(pol=strict, confidence="low")["disposition"] == "block")
    no_retry = copy.deepcopy(policy); no_retry["limits"]["max_retry_budget"] = 0; hashed(no_retry)
    check("retry-limit-blocks", "POLICY_RETRY_LIMIT_EXCEEDED" in run(pol=no_retry, retry=1)["reason_codes"])
    metrics = escalation_metrics(["block", "escalate", "proceed", "proceed"], ["proceed", "escalate", "block", "proceed"])
    check("false-negative-measured-separately", metrics["false_negative_escalation_count"] == 1 and metrics["false_negative_escalation_rate"] == 0.5)
    check("excessive-measured-separately", metrics["excessive_escalation_count"] == 1 and metrics["excessive_escalation_rate"] == 0.5)
    try: escalation_metrics([], [])
    except ValueError as error: check("invalid-metric-envelope-fails", str(error) == "ESCALATION_METRIC_INPUT_INVALID")
    result = {"ok": all(item["passed"] for item in cases), "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, indent=2)); raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
