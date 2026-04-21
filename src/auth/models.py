from sqlmodel import SQLModel, Field, Relationship, Column, JSON
from pydantic import EmailStr, field_validator
from typing import Optional, List
from datetime import datetime
import uuid

class Track(SQLModel, table=True):
    __tablename__ = "tracks"

    id: Optional[int] = Field(default=None, primary_key=True)
    spotify_track_id: str = Field(unique=True, index=True)
    name: str
    
    popularity: int = Field(default=0)
    release_date: Optional[str] = Field(default=None)
    image_url: Optional[str] = Field(default=None) 

    artist_id: int = Field(foreign_key="artists.id", index=True)
    artist: Artist = Relationship(back_populates="tracks")
    history_entries: List["ListenHistory"] = Relationship(back_populates="track")

class ListenHistory(SQLModel, table=True):
    __tablename__ = "listen_history"

    id: Optional[int] = Field(default=None, primary_key=True)
    
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    track_id: int = Field(foreign_key="tracks.id", index=True)
    
    played_at: datetime = Field(default_factory=datetime.utcnow)

    user: Optional["User"] = Relationship(back_populates="listen_history")
    track: Optional[Track] = Relationship(back_populates="history_entries")


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        index=True,
        nullable=False
    )
    email: EmailStr = Field(unique=True, index=True)
    hashed_password: str
    display_name: Optional[str] = Field(default=None)
    profile_image_url: Optional[str] = Field(default=None)
    spotify_refresh_token_encrypted: Optional[str] = Field(default=None)
    spotify_id: Optional[str] = Field(default=None, unique=True)

    alias: Optional[str] = Field(default=None)
    is_active: bool = Field(default=False)
    
    preferred_genres: List[str] = Field(default=[], sa_column=Column(JSON))

    listen_history: List[ListenHistory] = Relationship(back_populates="user")


    @field_validator("email")
    @classmethod
    def validate_email_domain(cls, v: str) -> str:
        """Validación estricta de formato y vacíos."""
        if not v:
            raise ValueError("El email no puede estar vacío")
        return v.lower().strip()
    
class Artist(SQLModel, table=True):
    __tablename__ = "artists"

    id: Optional[int] = Field(default=None, primary_key=True)
    spotify_artist_id: str = Field(unique=True, index=True)
    name: str
    genres: List[str] = Field(default=[], sa_column=Column(JSON))

    tracks: List["Track"] = Relationship(back_populates="artist")