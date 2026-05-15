import asyncio
import logging

from app.core.config import settings
from app.core.db import async_session_maker
from app.models.job import JobKind, JobStatus, ProcessingJob
from app.services.extraction import process_next_extraction_job
from app.services.ocr import process_next_ocr_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sp2.ocr_worker")


async def run_forever() -> None:
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


if __name__ == "__main__":
    asyncio.run(run_forever())
