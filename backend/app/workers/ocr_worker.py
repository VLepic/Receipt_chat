import asyncio
import logging
import signal

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import async_session_maker, engine
from app.models.job import JobKind, JobStatus, ProcessingJob
from app.services.extraction import process_next_extraction_job
from app.services.ocr import process_next_ocr_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sp2.ocr_worker")
WORKER_LOCK_ID = 74205003


async def run_forever() -> None:
    # Keep one worker per database, including while recovering interrupted jobs.
    async with engine.connect() as connection:
        acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": WORKER_LOCK_ID})
        await connection.commit()
        if not acquired:
            raise RuntimeError("Another OCR worker is already active for this database")
        try:
            async with async_session_maker() as session:
                await recover_interrupted_jobs(session)
            await process_jobs_forever()
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": WORKER_LOCK_ID})
            await connection.commit()


async def recover_interrupted_jobs(session: AsyncSession) -> int:
    result = await session.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.kind.in_([JobKind.ocr, JobKind.extraction]),
            ProcessingJob.status == JobStatus.running,
        )
        .values(status=JobStatus.queued, error_message=None)
    )
    await session.commit()
    count = result.rowcount
    if count:
        logger.warning("Requeued %s interrupted document jobs", count)
    return count


async def process_jobs_forever() -> None:
    logger.info("OCR worker started")
    while True:
        async with async_session_maker() as session:
            job = await process_next_ocr_job(session)
            if job is None:
                extraction_job = await process_next_extraction_job(session)
                if extraction_job is None:
                    await asyncio.sleep(settings.ocr_worker_poll_seconds)
                else:
                    logger.info("Processed extraction job %s with status %s", extraction_job.id, extraction_job.status)
            else:
                logger.info("Processed OCR job %s with status %s", job.id, job.status)
                if job.status == JobStatus.succeeded:
                    session.add(
                        ProcessingJob(
                            user_id=job.user_id,
                            document_id=job.document_id,
                            kind=JobKind.extraction,
                            status=JobStatus.queued,
                            payload={"source_job_id": str(job.id)},
                        )
                    )
                    await session.commit()


async def main() -> None:
    task = asyncio.create_task(run_forever())
    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    except NotImplementedError:
        pass
    try:
        await task
    except asyncio.CancelledError:
        logger.info("OCR worker stopped")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
