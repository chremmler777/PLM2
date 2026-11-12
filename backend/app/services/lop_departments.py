"""Department names of other systems mapped to PLM2 departments (wf_departments).

SEP template text and PDB team names to the PLM2 department name. None means
"(to be defined)": the line gets no department and no responsible.
Proposal of 2026-11-11 from the prod department list; Christoph confirms it.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import Department

SEP_DEPARTMENT_MAP: dict[str, Optional[str]] = {
    "Development / Project Mgmt.": "Project Manager",
    "Project Mgmt.": "Project Manager",
    "Advanced Product Quality Planning": "APQP",
    "Sales": "Sales",
    "Production": "Production",
    "Industrial Enineering": "Manufacturing Engineer",   # spelling as in the template
    "Purchasing/Supplier Mgmt.": "Purchasing",
    "Tool Mgmt.": "Tool Engineer",
    "Project Controlling": "Finance",
    "Managing Directors": "Management",
    "Productionplanning": "Planner/Scheduler",
    "(to be defined)": None,
}

PDB_DEPARTMENT_MAP: dict[str, Optional[str]] = {
    "APQP": "APQP", "Process ENG": "Process Engineer", "Project Management": "Project Manager",
    "Tool Engineering": "Tool Engineer", "Manufacturing Engineering": "Manufacturing Engineer",
}


async def department_id_for(db: AsyncSession, mapping: dict[str, Optional[str]],
                            text: Optional[str]) -> Optional[int]:
    """Active PLM2 department id for a foreign department text; None when
    unmapped, "(to be defined)", or the department does not exist."""
    name = mapping.get((text or "").strip())
    if name is None:
        return None
    return (await db.execute(select(Department.id).where(
        Department.name == name, Department.is_active.is_(True)))).scalar_one_or_none()
