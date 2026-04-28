from core.models import DeviceMessage
from msgs.nats_client import NATSClient


class NATSPublisher:
    """
    NATS Publisher
    """

    def __init__(self, client: NATSClient):
        self.client = client

    async def publish(self, subject: str, message: DeviceMessage):
        await self.client.js.publish(subject, message.to_json().encode())
