import redis.asyncio as redis
import logging
from src.core.config import settings

logger = logging.getLogger("redis_client")

redis_client = redis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True
)

async def check_redis_connection():
    try:
        await redis_client.ping()
        logger.info("Conexión a Redis establecida exitosamente.")
    except Exception as e:
        logger.error(f"Error crítico: No se pudo conectar a Redis. {e}")