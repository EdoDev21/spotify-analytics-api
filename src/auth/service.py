import os
import httpx
import uuid
import base64
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from fastapi import HTTPException, status
from urllib.parse import urlencode
from cryptography.fernet import Fernet

from src.core.security import EncryptionService
from src.auth.models import User
from src.core.config import settings

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8000/api/v1/auth/callback")

class SpotifyOAuthService:
    def __init__(self):
        self.encryption = EncryptionService()
        self.auth_base_url = "https://accounts.spotify.com/authorize"
        self.token_url = "https://accounts.spotify.com/api/token"
        self.api_base_url = "https://api.spotify.com/v1"
        self.PKCE_TTL = 300

    def get_authorization_url(self, state: str, code_challenge: str) -> str:
        scopes_list = [
            "user-read-private",
            "user-read-email",
            "user-top-read",
            "user-read-recently-played",
            "user-read-currently-playing",
            "user-read-playback-state"
        ]
        
        params = {
            "client_id": SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": SPOTIFY_REDIRECT_URI,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
            "scope": " ".join(scopes_list)
        }
        
        return f"{self.auth_base_url}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str, code_verifier: str) -> dict:
        payload = {
            "client_id": SPOTIFY_CLIENT_ID,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": SPOTIFY_REDIRECT_URI,
            "code_verifier": code_verifier,
        }
        
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(self.token_url, data=payload, headers=headers)
            
        if response.status_code != 200:
            print(f"DEBUG TOKEN ERROR: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"Error negociando token con Spotify. Revisa la consola."
            )
        return response.json()

    async def get_spotify_profile(self, access_token: str) -> dict:
        if not access_token:
            raise HTTPException(status_code=400, detail="Spotify no devolvió un access_token válido.")

        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.api_base_url}/me", headers=headers)
            
        if response.status_code != 200:
            print(f"DEBUG PROFILE ERROR: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Error de Spotify: {response.json().get('error', {}).get('message', 'Desconocido')}"
            )
        return response.json()

    async def process_callback(self, db: AsyncSession, code: str, code_verifier: str) -> dict:
        
        token_data = await self.exchange_code_for_token(code, code_verifier)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        profile_data = await self.get_spotify_profile(access_token)
        display_name = profile_data.get("display_name")
        images = profile_data.get("images", [])
        profile_image = images[0].get("url") if images else None
        spotify_id = profile_data.get("id")
        email = profile_data.get("email")

        stmt = select(User).where(User.spotify_id == spotify_id)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if user:
            encrypted_refresh = self.encryption.encrypt(refresh_token) if refresh_token else None
            
            if encrypted_refresh:
                user.spotify_refresh_token_encrypted = encrypted_refresh
                await db.commit()
                await db.refresh(user)
                
            return {"is_new": False, "user": user}
            
        else:
            spotify_data = {
                "spotify_id": spotify_id,
                "email": email,
                "display_name": display_name,
                "profile_image_url": profile_image,
                "refresh_token": refresh_token 
            }
            return {"is_new": True, "spotify_data": spotify_data}
    
    async def get_valid_spotify_token(self, db: AsyncSession, user_id: uuid.UUID) -> str:
        user = await db.get(User, user_id)
        if not user or not user.spotify_refresh_token_encrypted:
            raise HTTPException(status_code=401, detail="El usuario no tiene una conexión activa con Spotify.")

        try:
            fernet = Fernet(settings.ENCRYPTION_KEY.encode())
            refresh_token = fernet.decrypt(user.spotify_refresh_token_encrypted.encode()).decode()
        except Exception:
            raise HTTPException(status_code=500, detail="Error de consistencia criptográfica en la BD.")

        auth_str = f"{settings.SPOTIFY_CLIENT_ID}:{settings.SPOTIFY_CLIENT_SECRET}"
        b64_auth_str = base64.b64encode(auth_str.encode()).decode()

        headers = {
            "Authorization": f"Basic {b64_auth_str}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }

        async with httpx.AsyncClient() as client:
            response = await client.post("https://accounts.spotify.com/api/token", headers=headers, data=data)
            
            if response.status_code != 200:
                print(f"Error de Spotify Refresh: {response.text}")
                raise HTTPException(status_code=401, detail="La sesión de Spotify expiró permanentemente. Por favor, vuelve a iniciar sesión.")
            
            token_data = response.json()
            new_access_token = token_data.get("access_token")
            new_refresh_token = token_data.get("refresh_token")

            if new_refresh_token and new_refresh_token != refresh_token:
                encrypted_new_refresh = fernet.encrypt(new_refresh_token.encode()).decode()
                user.spotify_refresh_token_encrypted = encrypted_new_refresh
                db.add(user)
                await db.commit()

            return new_access_token
        
    async def save_pkce_state(self, state: str, code_verifier: str):
        await self.redis.setex(
            name=f"pkce:{state}",
            time=self.PKCE_TTL,
            value=code_verifier
        )

    async def get_pkce_verifier(self, state: str) -> str:
        key = f"pkce:{state}"
        verifier = await self.redis.get(key)
        if verifier:
            await self.redis.delete(key) # Garantizamos un solo uso
        return verifier