from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from src.database.database import init_db
from src.auth.router import router as auth_router
from src.spotify.router import router as spotify_router
from src.core.config import settings 
from src.analytics.router import router as analytics_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="Dashboard Spotify API", lifespan=lifespan)

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "message": exc.detail,
            "path": request.url.path
        }
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins, 
    allow_credentials=True, 
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(spotify_router, prefix="/api/v1/spotify", tags=["spotify"])
app.include_router(analytics_router, prefix="/api/v1")