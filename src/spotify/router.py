from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from src.database.database import get_session
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.auth.service import SpotifyOAuthService

router = APIRouter()
spotify_service = SpotifyOAuthService()

@router.get("/recently-played")
async def get_recently_played(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session)
):
    access_token = await spotify_service.get_valid_spotify_token(db, current_user.id)
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.spotify.com/v1/me/player/recently-played", 
            headers=headers
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Error consultando a Spotify")
            
        return response.json()
    
@router.post("/sync")
async def trigger_etl_sync(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session)
):

    return {"message": "Sincronización ETL enviada a segundo plano."}