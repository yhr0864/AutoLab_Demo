import nats
from nats.js.errors import NotFoundError


class NATSClient:
    def __init__(self, url: str, client_name: str):
        self.url = url
        self.client_name = client_name
        self.nc = None
        self.js = None

    async def connect(self):
        self.nc = await nats.connect(
            servers=self.url,
            name=self.client_name,
            connect_timeout=3,
        )
        self.js = self.nc.jetstream()

    async def ensure_stream(self, stream_name: str, subjects: list):
        """
        确保 JetStream Stream 存在

        如果不存在则自动创建
        """
        try:
            await self.js.stream_info(stream_name)
        except NotFoundError:
            await self.js.add_stream(
                name=stream_name,
                subjects=subjects,
            )

    async def close(self):
        if self.nc:
            await self.nc.close()
