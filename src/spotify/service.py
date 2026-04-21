import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import logging
import json

from src.auth.models import User, Track, Artist, ListenHistory
from src.spotify.auth_manager import SpotifyTokenManager

logger = logging.getLogger("etl_pipeline")

class SpotifyETLService:
    def __init__(self):
        self.base_url = "https://api.spotify.com/v1"
        self.token_manager = SpotifyTokenManager()

    async def run_pipeline(self, db: AsyncSession, user: User):
        logger.info(f"--- INICIANDO ETL: CATÁLOGO BÁSICO PARA {user.alias} ---")
        
        try:
            access_token = await self.token_manager.get_active_token(db, str(user.id))
            headers = {"Authorization": f"Bearer {access_token}"}
            
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.base_url}/me/player/recently-played?limit=50", headers=headers)
                if resp.status_code != 200:
                    logger.error(f"Fallo al extraer recently-played: {resp.text}")
                    return
                items = resp.json().get("items", [])

            if not items:
                logger.info("No hay reproducciones recientes.")
                return

            nuevos_registros = 0

            for item in items:
                played_at = datetime.fromisoformat(item["played_at"].replace("Z", "+00:00")).replace(tzinfo=None)
                
                stmt_h = select(ListenHistory).where(ListenHistory.user_id == user.id, ListenHistory.played_at == played_at)
                if (await db.execute(stmt_h)).scalars().first(): 
                    continue

                track_data = item.get("track")
                if not track_data or not track_data.get("id"): continue

                artists = track_data.get("artists", [])
                if not artists or not artists[0].get("id"): continue

                main_artist = artists[0]

                stmt_a = select(Artist).where(Artist.spotify_artist_id == main_artist.get("id"))
                artist_obj = (await db.execute(stmt_a)).scalars().first()

                if not artist_obj:
                    artist_obj = Artist(
                        spotify_artist_id=main_artist.get("id"),
                        name=main_artist.get("name", "Desconocido"),
                        genres=[] 
                    )
                    db.add(artist_obj)
                    await db.flush()

                stmt_t = select(Track).where(Track.spotify_track_id == track_data.get("id"))
                track_obj = (await db.execute(stmt_t)).scalars().first()

                if not track_obj:
                    images = track_data.get("album", {}).get("images", [])
                    track_image = images[0].get("url") if images else None

                    track_obj = Track(
                        spotify_track_id=track_data.get("id"),
                        name=track_data.get("name", "Desconocido"),
                        popularity=track_data.get("popularity", 0),
                        release_date=track_data.get("album", {}).get("release_date"),
                        image_url=track_image,
                        artist_id=artist_obj.id
                    )
                    db.add(track_obj)
                    await db.flush()

                db.add(ListenHistory(user_id=user.id, track_id=track_obj.id, played_at=played_at))
                nuevos_registros += 1

            await db.commit()
            logger.info(f"ETL Exitoso: {nuevos_registros} nuevos registros guardados en Postgres.")

        except Exception as e:
            await db.rollback()
            logger.error(f"Error crítico en el pipeline: {str(e)}")