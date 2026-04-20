import asyncio
from nats.server import run

async def main():
    # Start server with auto port assignment
    server = await nats.server.run(port=0, jetstream=True)
    print(f"Server running on {server.host}:{server.port}")

    # Do something with the server...
    # e.g connect with server.client_url

    # Clean shutdown
    await server.shutdown()

asyncio.run(main())