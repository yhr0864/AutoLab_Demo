"""
用于查阅数据(Jetstream)历史内容

"""

import asyncio
import nats
import json
from nats.js.api import ConsumerConfig, DeliverPolicy, AckPolicy

from config_loader import load_config


async def main():

    config = load_config("../config.yaml")

    nc = await nats.connect("nats://192.168.198.128:5223")
    js = nc.jetstream(domain="leaf")

    info = await js.stream_info(config["stream"]["name"])
    print("stream name:", info.config.name)
    print("subjects:", info.config.subjects)
    print("messages:", info.state.messages)
    print("bytes:", info.state.bytes)
    print("first seq:", info.state.first_seq)
    print("last seq:", info.state.last_seq)

    sub = await js.pull_subscribe(
        "lab.device.>",
        stream=config["stream"]["name"],
        config=ConsumerConfig(
            deliver_policy=DeliverPolicy.ALL,
            ack_policy=AckPolicy.EXPLICIT,
        ),
    )

    while True:
        try:
            msgs = await sub.fetch(batch=10, timeout=1)
        except Exception:
            break

        if not msgs:
            break

        for msg in msgs:
            print("subject:", msg.subject)
            print("raw:", msg.data.decode())
            try:
                print("json:", json.loads(msg.data.decode()))
            except Exception:
                pass
            print("-" * 40)
            await msg.ack()

    await nc.close()


asyncio.run(main())
