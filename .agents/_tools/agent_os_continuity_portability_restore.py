#!/usr/bin/env python3
"""Restore domain behavior for AOS-15 continuity portability.

This internal mixin owns bundle admission for restore, exact diff planning,
backup-before-write, transactional apply, rollback, and durable receipt validation.
It cannot authorize Core overwrite or trust a bundle as project authority.
"""

from __future__ import annotations

from continuity_portability_restore.apply_orchestration import (
    RestoreApplyOrchestrationMixin,
)
from continuity_portability_restore.backup_lifecycle import (
    RestoreBackupLifecycleMixin,
)
from continuity_portability_restore.backup_validation import (  # noqa: F401
    RestoreBackupValidationMixin,
)
from continuity_portability_restore.contracts import (
    _PLAN_ID,  # noqa: F401 - stable facade re-export
    _RECEIPT_DIR_AGENT_REL,  # noqa: F401 - stable facade re-export
    BACKUP_ID,  # noqa: F401 - stable facade re-export
    RESTORE_BACKUP_FIELDS,  # noqa: F401 - stable facade re-export
    RESTORE_BACKUP_FILE_FIELDS,  # noqa: F401 - stable facade re-export
    RESTORE_PLAN_FIELDS,  # noqa: F401 - stable facade re-export
    RESTORE_RECEIPT_FIELDS,  # noqa: F401 - stable facade re-export
    RESTORE_RECEIPT_ID,  # noqa: F401 - stable facade re-export
    RESTORE_TARGET_FIELDS,  # noqa: F401 - stable facade re-export
    _has_portable_path_collision,  # noqa: F401 - stable facade re-export
    _valid_hash,  # noqa: F401 - stable facade re-export
    _valid_time,  # noqa: F401 - stable facade re-export
)
from continuity_portability_restore.plan_validation import RestorePlanValidationMixin
from continuity_portability_restore.receipt_builder import RestoreReceiptBuilderMixin
from continuity_portability_restore.receipt_validation import (
    RestoreReceiptValidationMixin,
)
from continuity_portability_restore.stage_plan import RestoreStagePlanMixin
from continuity_portability_restore.target_analysis import RestoreTargetAnalysisMixin


class ContinuityRestoreMixin(
    RestoreApplyOrchestrationMixin,
    RestoreBackupLifecycleMixin,
    RestoreReceiptBuilderMixin,
    RestoreReceiptValidationMixin,
    RestorePlanValidationMixin,
    RestoreTargetAnalysisMixin,
    RestoreStagePlanMixin,
):
    """Stable public restore facade composed from bounded concern owners."""
