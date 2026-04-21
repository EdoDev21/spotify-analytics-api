from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
import uuid

class UserSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    email: str
    display_name: Optional[str] = None
    profile_image_url: Optional[str] = None
    is_authenticated_with_spotify: bool

class SpotifyCallbackQuery(BaseModel):
    code: Optional[str] = None
    state: Optional[str] = None
    error: Optional[str] = None

class OnboardingRequest(BaseModel):
    alias: str = Field(..., min_length=3, max_length=50, description="Alias público del usuario")
    preferred_genres: List[str] = Field(default_factory=list, description="Lista de géneros musicales")
    onboarding_token: str = Field(..., description="JWT temporal extraído de la URL")