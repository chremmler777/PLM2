"""Change assessment routing: resolve the standard RASIC matrix, snapshot it per
change, generate staged assessments, advance stages, govern deviations, promote on
release. Standard is read from the flow designer (WfTemplate); falls back to the
legacy TYPE_DISCIPLINES dict when no ChangeRoutingStandard mapping exists.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.change import (
    ChangeRequest, ChangeAssessment, ChangeRouting, ChangeRoutingStandard,
    BLOCKING_LETTERS, TASK_LETTERS,
)
from app.models.workflow import Department, WfTemplate, WfStage, WfStep, WfStepRasic
from app.services.notification_service import NotificationService


# Legacy fallback (kept in sync with change_service.TYPE_DISCIPLINES).
FALLBACK_DISCIPLINES = {
    "physical_part": ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"],
    "tooling":       ["Tool Engineer", "Process Engineer", "Manufacturing Engineer"],
    "document_spec": ["Quality", "Project Manager"],
    "process_im":    ["Process Engineer", "Manufacturing Engineer", "Quality"],
    "packaging":     ["Packaging Engineer", "Quality", "Sales"],
}


class ChangeRoutingService:

    @staticmethod
    async def resolve_standard(session: AsyncSession, change_type: str):
        """Return (template_id|None, template_version|None, stages).

        stages = [{"stage_order": int, "departments": [{"department_id", "rasic_letter"}]}]
        """
        std = (await session.execute(
            select(ChangeRoutingStandard).where(ChangeRoutingStandard.change_type == change_type)
        )).scalar_one_or_none()

        if std is not None:
            template = (await session.execute(
                select(WfTemplate)
                .where(WfTemplate.id == std.template_id)
                .options(
                    selectinload(WfTemplate.stages)
                    .selectinload(WfStage.steps)
                    .selectinload(WfStep.rasic_assignments)
                )
            )).scalar_one_or_none()
            if template is not None and template.stages:
                stages = []
                for stage in sorted(template.stages, key=lambda s: s.stage_order):
                    deps = []
                    for step in sorted(stage.steps, key=lambda s: s.position_in_stage):
                        for r in step.rasic_assignments:
                            deps.append({"department_id": r.department_id, "rasic_letter": r.rasic_letter})
                    stages.append({"stage_order": stage.stage_order, "departments": deps})
                return template.id, template.version, stages

        # Fallback: single implicit stage, all blocking R, from discipline names.
        names = FALLBACK_DISCIPLINES.get(change_type, [])
        rows = (await session.execute(
            select(Department).where(Department.name.in_(names))
        )).scalars().all() if names else []
        deps = [{"department_id": d.id, "rasic_letter": "R"} for d in rows]
        return None, None, [{"stage_order": 1, "departments": deps}]
