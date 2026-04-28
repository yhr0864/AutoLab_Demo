import asyncpg
from datetime import datetime
from typing import List

from core.models import DeviceMessage


class PostgresWriter:
    """
    PostgreSQL 批量写入器
    """

    def __init__(self, db_config: dict):
        self.db_config = db_config
        self.pool = None

    async def connect(self):
        """
        创建 PostgreSQL 连接池
        """
        self.pool = await asyncpg.create_pool(**self.db_config, min_size=1, max_size=10)

    async def insert_batch(self, messages: List[DeviceMessage]):
        """
        批量插入设备消息
        """
        if not messages:
            return

        sql = """
        INSERT INTO device_messages (device_id, device_type, location, ts, status, data)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        """

        records = []
        for msg in messages:
            ts = datetime.fromisoformat(msg.timestamp)
            records.append(
                (
                    msg.device_id,
                    msg.device_type,
                    msg.location,
                    ts,
                    msg.status,
                    msg.to_json(),
                )
            )

        async with self.pool.acquire() as conn:
            await conn.executemany(sql, records)

    async def close(self):
        if self.pool:
            await self.pool.close()
