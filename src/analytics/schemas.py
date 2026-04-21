from pydantic import BaseModel
from typing import List, Optional

class TrackMini(BaseModel):
    name: str
    artist_name: str
    play_count: Optional[int] = None
    image_url: Optional[str] = None

class DashboardResponse(BaseModel):
    now_playing: Optional[dict]
    heavy_rotation: List[TrackMini]

class TopArtistResponse(BaseModel):
    name: str
    genres: List[str]
    popularity: int
    image_url: Optional[str] = None