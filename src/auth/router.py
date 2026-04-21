from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from cryptography.fernet import Fernet
from redis.exceptions import RedisError
from datetime import datetime, timedelta
import os
import json
import jwt
import logging

from src.database.database import get_session
from src.auth.service import SpotifyOAuthService
from src.auth.dependencies import get_current_user
from src.auth.schemas import UserSessionResponse, OnboardingRequest
from src.auth.models import User
from src.core.security import PKCEUtils, SessionUtils
from src.core.config import settings
from src.core.redis import redis_client

router = APIRouter()
spotify_service = SpotifyOAuthService()

logger = logging.getLogger("auth_onboarding")
logger.setLevel(logging.INFO)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

@router.get("/login")
async def login_to_spotify():
    state = PKCEUtils.generate_state()
    code_verifier, code_challenge = PKCEUtils.generate_pkce_pair()
    
    url = spotify_service.get_authorization_url(state, code_challenge)
    
    await spotify_service.save_pkce_state(state, code_verifier)
    
    return JSONResponse(content={"authorization_url": url})

@router.get("/me", response_model=UserSessionResponse)
async def get_current_session(current_user: User = Depends(get_current_user)):
    return UserSessionResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        profile_image_url=current_user.profile_image_url,
        is_authenticated_with_spotify=bool(current_user.spotify_id)
    )

@router.get("/callback")
async def spotify_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
    db: AsyncSession = Depends(get_session)
):
    if error or not state:
        raise HTTPException(status_code=400, detail="Error en la autenticación con Spotify.")

    code_verifier = await spotify_service.get_pkce_verifier(state)
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Sesión expirada.")

    auth_result = await spotify_service.process_callback(db, code, code_verifier)

    if auth_result["is_new"]:
        spotify_data = auth_result["spotify_data"]
        spotify_id = spotify_data["spotify_id"]

        await redis_client.set(
            name=f"onboarding:{spotify_id}",
            value=json.dumps(spotify_data),
            ex=900
        )

        temp_payload = {
            "sub": spotify_id,
            "scope": "onboarding",
            "exp": datetime.utcnow() + timedelta(minutes=15)
        }
        temp_token = jwt.encode(temp_payload, settings.JWT_SECRET, algorithm="HS256")

        redirect = RedirectResponse(url=f"{settings.FRONTEND_URL}/onboarding?token={temp_token}")

        redirect.delete_cookie("session_token", path="/")
        return redirect
    
    else:
        user = auth_result["user"]
        session_token = SessionUtils.create_session_token(user.id)
        redirect = RedirectResponse(url=f"{settings.FRONTEND_URL}/dashboard")
        redirect.set_cookie(
            key="session_token", value=session_token, httponly=True, secure=False, samesite="lax", path="/"
        )
        return redirect
    
@router.post("/register/complete")
async def complete_registration(
    request: Request,
    data: OnboardingRequest,
    db: AsyncSession = Depends(get_session)
):
    logger.info(f"--- Iniciando completado de registro para el alias: '{data.alias}' ---")
    
    temp_token = data.onboarding_token
    
    if not temp_token:
        logger.error("FALLO 400: El 'onboarding_token' enviado en el Body está vacío.")
        raise HTTPException(status_code=400, detail="Token de registro no puede estar vacío.")

    try:
        payload = jwt.decode(temp_token, settings.JWT_SECRET, algorithms=["HS256"])
        
        if payload.get("scope") != "onboarding":
            logger.error(f"FALLO 403: Scope incorrecto. Esperado 'onboarding', Recibido '{payload.get('scope')}'")
            raise HTTPException(status_code=403, detail="Token inválido para esta operación.")
            
        spotify_id = payload.get("sub")
        logger.info(f"JWT válido. Identidad confirmada para spotify_id: {spotify_id}")
        
    except jwt.ExpiredSignatureError:
        logger.error("FALLO 401: El JWT temporal ha expirado (> 15 minutos).")
        raise HTTPException(status_code=401, detail="El tiempo de registro expiró.")
    except jwt.InvalidTokenError as e:
        logger.error(f"FALLO 401: JWT alterado, corrupto o fallo de firma secreta. Detalle: {str(e)}")
        raise HTTPException(status_code=401, detail="Token de seguridad inválido.")
    except Exception as e:
        logger.error(f"FALLO 500: Error inesperado al procesar JWT. Detalle: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno verificando la sesión.")

    try:
        redis_data = await redis_client.get(f"onboarding:{spotify_id}")
        if not redis_data:
            logger.error(f"FALLO 400: No hay datos en Redis para onboarding:{spotify_id}. (Posible borrado de TTL)")
            raise HTTPException(status_code=400, detail="Sesión de registro caducada en caché. Vuelve a iniciar sesión.")
        
        spotify_data = json.loads(redis_data)
        logger.info("Datos del perfil recuperados desde Redis correctamente.")
        
    except RedisError as e:
        logger.error(f"FALLO 500: Pérdida de conexión con Redis. Detalle: {str(e)}")
        raise HTTPException(status_code=500, detail="Error de infraestructura de caché.")
    except json.JSONDecodeError as e:
        logger.error(f"FALLO 500: Integridad de datos comprometida en Redis. Detalle: {str(e)}")
        raise HTTPException(status_code=500, detail="Los datos temporales están corruptos.")

    try:
        fernet = Fernet(settings.ENCRYPTION_KEY.encode())
        raw_refresh = spotify_data.get("refresh_token")
        encrypted_rt = fernet.encrypt(raw_refresh.encode()).decode() if raw_refresh else None

        new_user = User(
            spotify_id=spotify_id,
            email=spotify_data.get("email"),
            hashed_password="oauth_managed",
            display_name=spotify_data.get("display_name"),
            profile_image_url=spotify_data.get("profile_image_url"),
            spotify_refresh_token_encrypted=encrypted_rt,
            alias=data.alias,
            preferred_genres=data.preferred_genres,
            is_active=True
        )
        
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        logger.info(f"Usuario persistido exitosamente en PostgreSQL. UUID: {new_user.id}")

    except Exception as e:
        await db.rollback()
        logger.error(f"FALLO 500: Inserción en DB fallida (Posible violación de unique/not null). Detalle: {str(e)}")
        raise HTTPException(status_code=500, detail="Error al crear el perfil de usuario.")

    try:
        await redis_client.delete(f"onboarding:{spotify_id}")
        
        session_token = SessionUtils.create_session_token(new_user.id)
        response = JSONResponse(content={"message": "Registro completado", "alias": new_user.alias})
        
        response.set_cookie(
            key="session_token", value=session_token, httponly=True, secure=False, samesite="lax", path="/"
        )
        
        logger.info("--- Registro finalizado exitosamente. Cookies transicionadas. ---")
        return response
        
    except Exception as e:
        logger.error(f"ADVERTENCIA: Usuario creado, pero falló la limpieza post-registro. Detalle: {str(e)}")
        raise HTTPException(status_code=500, detail="Error al inicializar la sesión tras el registro.")

@router.post("/logout")
async def logout():
    response = JSONResponse(content={"message": "Sesión cerrada"})
    response.delete_cookie("session_token", path="/")
    return response