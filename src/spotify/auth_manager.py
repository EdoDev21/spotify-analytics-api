import httpx
import base64
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from cryptography.fernet import Fernet

from src.auth.models import User
from src.core.config import settings
from src.core.redis import redis_client

logger = logging.getLogger("spotify_token_manager")

class SpotifyTokenManager:
    def __init__(self):
        self.token_url = "https://accounts.spotify.com/api/token"
        self.fernet = Fernet(settings.ENCRYPTION_KEY.encode())

    async def get_active_token(self, db: AsyncSession, user_id: str) -> str:
        cache_key = f"token:{user_id}"
        lock_key = f"lock:token:{user_id}"
        
        cached_token = await redis_client.get(cache_key)
        if cached_token:
            return cached_token

        async with redis_client.lock(lock_key, timeout=10):
            cached_token = await redis_client.get(cache_key)
            if cached_token:
                return cached_token

            stmt = select(User).where(User.id == user_id)
            user = (await db.execute(stmt)).scalars().first()

            if not user or not user.spotify_refresh_token_encrypted:
                raise ValueError("Usuario sin refresh token.")

            refresh_token = self.fernet.decrypt(user.spotify_refresh_token_encrypted.encode()).decode()
            auth_str = f"{settings.SPOTIFY_CLIENT_ID}:{settings.SPOTIFY_CLIENT_SECRET}"
            b64_auth_str = base64.b64encode(auth_str.encode()).decode()
            
            headers = {
                "Authorization": f"Basic {b64_auth_str}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(self.token_url, headers=headers, data={"grant_type": "refresh_token", "refresh_token": refresh_token})
                if response.status_code != 200:
                    raise Exception("Fallo de comunicación con Spotify")
                
                token_data = response.json()
                
            new_rt = token_data.get("refresh_token")
            if new_rt:
                user.spotify_refresh_token_encrypted = self.fernet.encrypt(new_rt.encode()).decode()
                await db.commit()

            access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600) - 300 
            
            await redis_client.set(cache_key, access_token, ex=expires_in)

            return access_token