"""Transactional retention workflow for completed interaction records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from app.models.interaction import Interaction, InteractionArchive


ARCHIVABLE_STATES = {"COMPLETED", "FAILED", "CANCELLED"}


def archive_values(interaction: Interaction, archived_at: datetime) -> dict[str, Any]:
    values = {
        attribute.key: getattr(interaction, attribute.key)
        for attribute in inspect(Interaction).column_attrs
    }
    values.update({"archived_at": archived_at, "is_immutable": True})
    return values


async def archive_completed_interactions(
    db: AsyncSession, *, retention_days: int, dry_run: bool = False
) -> dict[str, Any]:
    if retention_days < 1:
        raise ValueError("retention_days는 1 이상이어야 합니다.")
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    rows = (
        await db.execute(
            select(Interaction)
            .where(
                Interaction.state.in_(ARCHIVABLE_STATES),
                Interaction.complete_timestamp.is_not(None),
                Interaction.complete_timestamp <= cutoff,
            )
            .order_by(Interaction.tree_depth.desc(), Interaction.complete_timestamp)
        )
    ).scalars().all()
    if dry_run or not rows:
        return {
            "retention_days": retention_days,
            "cutoff": cutoff,
            "eligible_count": len(rows),
            "archived_count": 0,
            "dry_run": dry_run,
        }

    archived_at = datetime.now(timezone.utc)
    db.add_all([InteractionArchive(**archive_values(row, archived_at)) for row in rows])
    await db.flush()
    interaction_ids = [row.interaction_id for row in rows]
    await db.execute(
        delete(Interaction).where(Interaction.interaction_id.in_(interaction_ids))
    )
    await db.flush()
    return {
        "retention_days": retention_days,
        "cutoff": cutoff,
        "eligible_count": len(rows),
        "archived_count": len(rows),
        "dry_run": False,
    }
