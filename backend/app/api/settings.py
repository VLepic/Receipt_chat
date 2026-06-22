from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_active_user
from app.core.db import get_async_session
from app.models.settings import UserSettings
from app.models.user import User
from app.schemas.settings import UserSettingsRead, UserSettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


async def get_or_create_user_settings(user: User, session: AsyncSession) -> UserSettings:
    result = await session.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    user_settings = result.scalar_one_or_none()
    if user_settings is not None:
        return user_settings

    user_settings = UserSettings(user_id=user.id)
    session.add(user_settings)
    await session.commit()
    await session.refresh(user_settings)
    return user_settings


@router.get("", response_model=UserSettingsRead)
async def read_settings(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> UserSettings:
    return await get_or_create_user_settings(user, session)


@router.put("", response_model=UserSettingsRead)
async def update_settings(
    payload: UserSettingsUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> UserSettings:
    user_settings = await get_or_create_user_settings(user, session)
    user_settings.default_chat_model = payload.default_chat_model or None
    user_settings.tts_voice = payload.tts_voice or None
    user_settings.ocr_processing_model = payload.ocr_processing_model or None
    user_settings.rag_source_strategy = payload.rag_source_strategy
    user_settings.rag_best_band = payload.rag_best_band
    user_settings.rag_reranker_best_band = payload.rag_reranker_best_band
    user_settings.rag_reranker_min_score = payload.rag_reranker_min_score
    user_settings.rag_top_n = payload.rag_top_n
    await session.commit()
    await session.refresh(user_settings)
    return user_settings
