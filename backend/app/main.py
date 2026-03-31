from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.checkpointer import close_checkpointer, get_checkpointer
from app.config import settings
from app.database import engine
from app.models import Base
from app.routers import approve, auth, chat, emails, notifications


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


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
