from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.checkpointer import close_checkpointer, get_checkpointer
from app.config import settings
from app.database import engine
from app.models import Base
from app.routers import approve, auth, chat, emails, notifications

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Alembic remains the source of truth; this keeps local bootstraps friction-free.
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    checkpointer = await get_checkpointer()
    await checkpointer.setup()
    app.state.checkpointer = checkpointer
    yield
    await close_checkpointer()
    await engine.dispose()


app = FastAPI(title="Email Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(emails.router, prefix="/api/emails", tags=["emails"])
app.include_router(approve.router, prefix="/api/approve", tags=["approve"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, (dict, list)) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "detail": detail,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "RequestValidationError",
            "detail": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception for %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": exc.__class__.__name__,
            "detail": "Internal server error",
        },
    )


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
