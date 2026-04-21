from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, desc, select
from datetime import datetime, timedelta
import httpx, json

from typing import List, Optional


from src.database.database import get_session
from src.auth.dependencies import get_current_user
from src.auth.models import User, Track, ListenHistory, Artist
from src.spotify.service import SpotifyETLService
from src.spotify.auth_manager import SpotifyTokenManager
from src.analytics.schemas import DashboardResponse, TrackMini, TopArtistResponse
from src.core.redis import redis_client

router = APIRouter(prefix="/analytics", tags=["Analytics"])
etl_service = SpotifyETLService()
token_manager = SpotifyTokenManager()

@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    background_tasks.add_task(etl_service.run_pipeline, db, current_user)

    now_playing = None
    try:
        token = await token_manager.get_active_token(db, str(current_user.id))
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.spotify.com/v1/me/player/currently-playing", headers=headers)
            if resp.status_code == 200 and resp.text: 
                data = resp.json()
                if data and "item" in data and data["item"]:
                    album_images = data["item"]["album"].get("images", [])
                    current_image = album_images[0]["url"] if album_images else None

                    now_playing = {
                        "name": data["item"]["name"],
                        "artist": data["item"]["artists"][0]["name"],
                        "is_playing": data.get("is_playing", False),
                        "image_url": current_image
                    }
    except Exception as e:
        print(f"Error obteniendo Now Playing: {e}")

    cache_key = f"dashboard_hr:{current_user.id}"
    cached_hr = await redis_client.get(cache_key)

    if cached_hr:
        heavy_rotation = json.loads(cached_hr)
    else:
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        statement = (
            select(Track, func.count(ListenHistory.id).label("play_count"))
            .join(ListenHistory)
            .where(ListenHistory.user_id == current_user.id)
            .where(ListenHistory.played_at >= seven_days_ago)
            .group_by(Track.id)
            .order_by(desc("play_count"))
            .limit(5)
        )
    
        results = await db.execute(statement)
        heavy_rotation = []
        
        for track_obj, count in results.all():
            stmt_artist = select(Artist).where(Artist.id == track_obj.artist_id)
            artist_obj = (await db.execute(stmt_artist)).scalars().first()
            
            heavy_rotation.append({
                "name": track_obj.name,
                "artist_name": artist_obj.name if artist_obj else "Unknown",
                "play_count": count,
                "image_url": track_obj.image_url
            })
        
        await redis_client.set(cache_key, json.dumps(heavy_rotation), ex=300)

    return DashboardResponse(now_playing=now_playing, heavy_rotation=heavy_rotation)


@router.get("/top-artists", response_model=List[TopArtistResponse])
async def get_top_artists(
    time_range: str = Query("medium_term", regex="^(short_term|medium_term|long_term)$"),
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    try:
        token = await token_manager.get_active_token(db, str(current_user.id))
        headers = {"Authorization": f"Bearer {token}"}
        
        async with httpx.AsyncClient() as client:
            url = f"https://api.spotify.com/v1/me/top/artists?time_range={time_range}&limit=10"
            resp = await client.get(url, headers=headers)
            
            if resp.status_code != 200:
                return []
                
            items = resp.json().get("items", [])
            return [
                TopArtistResponse(
                    name=item["name"],
                    genres=item.get("genres", []),
                    popularity=item.get("popularity", 0),
                    image_url=item["images"][0]["url"] if item.get("images") else None
                ) for item in items
            ]
    except Exception as e:
        print(f"Error obteniendo Top Artists: {e}")
        return []