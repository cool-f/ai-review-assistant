import logging

from sqlalchemy import delete, or_, select

from review_assistant.application.knowledge.linking import LinkingService
from review_assistant.infrastructure.ai.embeddings import EmbeddingService
from review_assistant.infrastructure.persistence.database import async_session_factory
from review_assistant.infrastructure.persistence.models import Courseware, KnowledgePoint, KnowledgePointLink
from review_assistant.infrastructure.usage.context import usage_scope


logger = logging.getLogger(__name__)


async def refresh_knowledge_point_index(knowledge_point_id: str) -> None:
    """Rebuild one edited knowledge point's vector and all of its derived links."""
    async with async_session_factory() as db:
        kp = await db.get(KnowledgePoint, knowledge_point_id)
        if kp is None:
            return
        service = EmbeddingService()
        try:
            kp.indexing_status = "processing"
            kp.indexing_error = None
            await db.commit()
            course_id = await db.scalar(
                select(Courseware.course_id).where(Courseware.id == kp.courseware_id)
            )
            with usage_scope("knowledge_reindex", course_id=course_id):
                embedding = await service.embed_single(f"{kp.title}\n{kp.content}", text_type="document")
            kp.embedding = embedding
            await db.execute(delete(KnowledgePointLink).where(or_(
                KnowledgePointLink.source_kp_id == kp.id,
                KnowledgePointLink.target_kp_id == kp.id,
            )))
            await LinkingService(db).find_links([kp.id])
            kp.indexing_status = "completed"
            await db.commit()
        except Exception as exc:
            logger.exception("知识点重新索引失败: %s", knowledge_point_id)
            await db.rollback()
            kp = await db.get(KnowledgePoint, knowledge_point_id)
            if kp:
                kp.indexing_status = "failed"
                kp.indexing_error = str(exc)[:2048]
                await db.commit()
        finally:
            await service.close()
