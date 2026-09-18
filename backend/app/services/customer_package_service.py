"""Receive a customer delivery for an assembly in one step. See
docs/superpowers/specs/2026-09-18-customer-package-receive-design.md."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import Part, PartRevision
from app.services.bom_tree_service import BomTreeService
from app.services.customer_package import (
    ACTION_ERROR, ACTION_NEW, ACTION_UNCHANGED, ACTION_UNMATCHED,
    Candidate, decide_action, index_from_filename, match_file)
from app.services.part_service import ChangelogService, RevisionService
from app.services.revision_file_service import UnsupportedFile, classify, store_revision_file
from app.services.revision_naming import RevisionRuleViolation, next_major_name


@dataclass
class PackageRow:
    filename: str
    part_id: Optional[int] = None
    part_number: Optional[str] = None
    customer_part_number: Optional[str] = None
    customer_index: Optional[str] = None
    current_revision: Optional[str] = None
    current_index: Optional[str] = None
    action: str = ACTION_UNMATCHED
    suggested_name: Optional[str] = None
    major: Optional[int] = None
    error: Optional[str] = None


class PackageError(ValueError):
    """At least one row is in error; nothing was stored."""

    def __init__(self, rows: list[PackageRow]):
        super().__init__("Package has rows in error")
        self.rows = rows


def _tree_part_ids(node: dict, acc: set[int]) -> set[int]:
    acc.add(node["part_id"])
    for line in node.get("lines", []):
        if line.get("child"):
            _tree_part_ids(line["child"], acc)
    return acc


class CustomerPackageService:

    @staticmethod
    async def candidates(session: AsyncSession, assembly_id: int) -> list[Candidate]:
        assembly = await session.get(Part, assembly_id)
        if assembly is None:
            raise ValueError("Assembly not found")
        tree_ids = _tree_part_ids(await BomTreeService.tree(session, assembly_id), set())
        parts = (await session.execute(
            select(Part).where(Part.project_id == assembly.project_id).order_by(Part.part_number))).scalars().all()
        return [Candidate(p.id, p.part_number, p.customer_part_number, p.id in tree_ids) for p in parts]

    @staticmethod
    async def _current(session: AsyncSession, part_id: int) -> Optional[PartRevision]:
        part = await session.get(Part, part_id)
        return await BomTreeService._display_revision(session, part) if part else None

    @staticmethod
    async def _fill_row(session: AsyncSession, row: PackageRow, statement: str) -> PackageRow:
        """Current revision, suggested name and rule errors for a row with a part."""
        part = await session.get(Part, row.part_id)
        if part is None:
            row.action, row.error = ACTION_ERROR, "Part not found"
            return row
        row.part_number, row.customer_part_number = part.part_number, part.customer_part_number
        current = await CustomerPackageService._current(session, row.part_id)
        row.current_revision = current.revision_name if current else None
        row.current_index = current.customer_index if current else None
        try:
            classify(row.filename)
            majors = await RevisionService._majors(session, row.part_id)
            row.suggested_name = next_major_name([m.revision_name for m in majors], statement, requested=row.major)
        except (UnsupportedFile, RevisionRuleViolation) as e:
            row.action, row.error = ACTION_ERROR, str(e)
        return row

    @staticmethod
    async def preview(session: AsyncSession, assembly_id: int, statement: str, received_at: date,
                      package_index: Optional[str], filenames: list[str]) -> list[PackageRow]:
        cands = await CustomerPackageService.candidates(session, assembly_id)
        rows: list[PackageRow] = []
        for name in filenames:
            row = PackageRow(filename=name)
            c = match_file(name, cands)
            if c is None:
                try:
                    classify(name)
                except UnsupportedFile as e:
                    row.action, row.error = ACTION_ERROR, str(e)
                rows.append(row)
                continue
            row.part_id = c.part_id
            row.customer_index = index_from_filename(name, c.customer_part_number) or (package_index or None)
            await CustomerPackageService._fill_row(session, row, statement)
            if row.action != ACTION_ERROR:
                row.action = decide_action(row.customer_index, row.current_index)
            rows.append(row)
        return rows

    @staticmethod
    async def confirm(session: AsyncSession, assembly_id: int, statement: str, received_at: date,
                      rows: list[PackageRow], files: dict[str, tuple[bytes, Optional[str]]],
                      created_by: int) -> dict:
        assembly = await session.get(Part, assembly_id)
        if assembly is None:
            raise ValueError("Assembly not found")
        # validate every row first; nothing is written while any row errs
        for row in rows:
            if row.action == ACTION_NEW:
                if row.part_id is None:
                    row.action, row.error = ACTION_ERROR, "No part chosen"
                elif row.filename not in files:
                    row.action, row.error = ACTION_ERROR, "File missing from upload"
                else:
                    await CustomerPackageService._fill_row(session, row, statement)
        if any(r.action == ACTION_ERROR for r in rows):
            raise PackageError(rows)

        created, kept, skipped = [], [], []
        written: list[str] = []
        try:
            # children first, the assembly last, so its new BOM copy sees the children active
            ordered = sorted((r for r in rows if r.action == ACTION_NEW), key=lambda r: r.part_id == assembly_id)
            for row in ordered:
                rev = await RevisionService.receive_customer_data(
                    session, row.part_id, statement, received_at, customer_index=row.customer_index,
                    summary=f"Customer package {received_at.isoformat()}", created_by=created_by, major=row.major)
                contents, ctype = files[row.filename]
                f = await store_revision_file(session, rev, row.filename, contents, created_by, content_type=ctype)
                written.append(f.file_path)
                if f.viewer_file_path:
                    written.append(f.viewer_file_path)
                created.append({"part_id": row.part_id, "part_number": row.part_number,
                                "revision_name": rev.revision_name, "file_id": f.id, "filename": row.filename})
            for row in rows:
                if row.action == ACTION_UNCHANGED and row.part_id is not None:
                    current = await CustomerPackageService._current(session, row.part_id)
                    part = await session.get(Part, row.part_id)
                    await ChangelogService.log_action(
                        session, part_id=row.part_id, revision_id=current.id if current else None,
                        action="package_unchanged",
                        action_description=(f"Customer package {received_at.isoformat()}: {row.filename} unchanged, "
                                            f"kept {current.revision_name if current else 'no revision'}"),
                        performed_by=created_by)
                    kept.append({"part_id": row.part_id, "part_number": part.part_number if part else None,
                                 "revision_name": current.revision_name if current else None, "filename": row.filename})
                elif row.action == ACTION_UNMATCHED:
                    skipped.append(row.filename)
        except Exception:
            for path in written:
                try:
                    os.remove(path)
                except OSError:
                    pass
            raise
        return {"created": created, "kept": kept, "skipped": skipped}
