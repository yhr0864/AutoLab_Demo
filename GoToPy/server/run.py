#!/usr/bin/env python
"""Entry point — starts the Calculator gRPC server."""

import logging
from concurrent import futures

import grpc
from grpc_stubs import calculator_pb2_grpc
from calculator import CalculatorServicer


def serve(port: int = 50051):
    """Start the gRPC server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    calculator_pb2_grpc.add_CalculatorServicer_to_server(CalculatorServicer(), server)

    address = f"[::]:{port}"
    server.add_insecure_port(address)
    server.start()

    logging.getLogger(__name__).info("Calculator server listening on %s...", address)
    print(f"Calculator server listening on {address}...")

    server.wait_for_termination()


if __name__ == "__main__":
    serve()