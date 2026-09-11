"""pgvector-backed retrieval for topic-scoped teaching context (PRD 7.2).

Falls back to keyword matching if the vector query fails, so the tutor keeps
working even without the extension or an embedding key.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContentChunk
from app.services import llm

logger = logging.getLogger(__name__)


async def index_chunks(
    db: AsyncSession,
    *,
    subject_id: uuid.UUID,
    chunks: List[str],
    source: str = "syllabus",
    subtopic_id: Optional[uuid.UUID] = None,
) -> int:
    """Embed and store text chunks. Returns the number indexed."""
    if not chunks:
        return 0

    vectors = await llm.embed(chunks, lane_name="background")
    for text, vector in zip(chunks, vectors):
        db.add(
            ContentChunk(
                subject_id=subject_id,
                subtopic_id=subtopic_id,
                source=source,
                content=text,
                embedding=vector,
            )
        )
    await db.flush()
    return len(chunks)


async def search(
    db: AsyncSession,
    *,
    subject_id: uuid.UUID,
    query: str,
    limit: int = 4,
) -> List[str]:
    """Nearest chunks within one subject's scope."""
    if not query.strip():
        return []

    try:
        vector = (await llm.embed([query], lane_name="interactive"))[0]
        stmt = (
            select(ContentChunk.content)
            .where(ContentChunk.subject_id == subject_id)
            .where(ContentChunk.embedding.is_not(None))
            .order_by(ContentChunk.embedding.cosine_distance(vector))
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        if rows:
            return list(rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vector search failed (%s); falling back to keywords", exc)

    keywords = [w for w in query.split() if len(w) > 3][:5]
    if not keywords:
        return []
    stmt = select(ContentChunk.content).where(ContentChunk.subject_id == subject_id)
    for word in keywords:
        stmt = stmt.where(ContentChunk.content.ilike(f"%{word}%"))
    try:
        return list((await db.execute(stmt.limit(limit))).scalars().all())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Keyword fallback failed: %s", exc)
        return []
