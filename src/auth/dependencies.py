from fastapi import Request, Depends, HTTPException, status
import jwt
from src.core.security import JWT_SECRET, ALGORITHM
from src.auth.models import User
from src.database.database import get_session
from sqlalchemy.ext.asyncio import AsyncSession

async def get_current_user(request: Request, db: AsyncSession = Depends(get_session)) -> User:
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="No session cookie")
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid session payload")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user