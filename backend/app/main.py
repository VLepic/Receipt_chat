import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import auth_backend, current_active_user, fastapi_users
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.inference import router as inference_router
from app.api.settings import router as settings_router
from app.api.voice import router as voice_router
from app.core.config import settings
from app.core.db import Base, engine
from app.core.errors import register_exception_handlers
from app.core.middleware import register_request_middleware
from app.models import conversation, document, inference, job, settings as user_settings, user, voice  # noqa: F401
from app.schemas.user import UserCreate, UserRead, UserUpdate


def configure_logging() -> None:
    sp2_logger = logging.getLogger("sp2")
    sp2_logger.setLevel(logging.INFO)

    uvicorn_handlers = logging.getLogger("uvicorn.error").handlers
    if uvicorn_handlers:
        sp2_logger.handlers = list(uvicorn_handlers)
        sp2_logger.propagate = False
    else:
        logging.basicConfig(level=logging.INFO)


configure_logging()
logging.getLogger("sp2.api").info("SP2 logging configured")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)
register_request_middleware(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/api/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/api/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/api/users",
    tags=["users"],
)
app.include_router(chat_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(inference_router, prefix="/api")
app.include_router(voice_router, prefix="/api")
