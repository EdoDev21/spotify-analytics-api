import os
import base64
import hashlib
import jwt
from datetime import datetime, timedelta, timezone
from cryptography.fernet import Fernet
from typing import Tuple

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", Fernet.generate_key().decode()).encode()
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key-change-in-production")
ALGORITHM = "HS256"

class EncryptionService:
    def __init__(self):
        self.fernet = Fernet(ENCRYPTION_KEY)

    def encrypt(self, data: str) -> str:
        return self.fernet.encrypt(data.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self.fernet.decrypt(token.encode()).decode()

class PKCEUtils:
    @staticmethod
    def generate_state() -> str:
        return base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("=")

    @staticmethod
    def generate_pkce_pair() -> Tuple[str, str]:
        code_verifier = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return code_verifier, code_challenge

class SessionUtils:
    @staticmethod
    def create_session_token(user_id: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(days=7)
        payload = {"sub": str(user_id), "exp": expire}
        return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)