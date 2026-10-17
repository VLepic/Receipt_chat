import asyncio
import uuid

from sqlalchemy import select

from app.core.db import async_session_maker
from app.models.job import JobKind, JobStatus, ProcessingJob
from app.models.user import User
from app.workers.ocr_worker import recover_interrupted_jobs


def test_restart_requeues_only_interrupted_document_jobs():
    async def check():
        async with async_session_maker() as session:
            user = User(id=uuid.uuid4(), email=f"recovery-{uuid.uuid4()}@example.com", hashed_password="unused")
            session.add(user)
            await session.flush()
            jobs = [
                ProcessingJob(user_id=user.id, kind=JobKind.ocr, status=JobStatus.running),
                ProcessingJob(user_id=user.id, kind=JobKind.extraction, status=JobStatus.running),
                ProcessingJob(user_id=user.id, kind=JobKind.ocr, status=JobStatus.succeeded),
                ProcessingJob(user_id=user.id, kind=JobKind.extraction, status=JobStatus.failed),
                ProcessingJob(user_id=user.id, kind=JobKind.rag_index, status=JobStatus.running),
            ]
            session.add_all(jobs)
            await session.commit()
            assert await recover_interrupted_jobs(session) >= 2
            for job, expected in zip(jobs, ["queued", "queued", "succeeded", "failed", "running"]):
                await session.refresh(job)
                assert job.status == expected
            assert (await session.scalars(select(ProcessingJob).where(ProcessingJob.user_id == user.id))).all()

    asyncio.run(check())
