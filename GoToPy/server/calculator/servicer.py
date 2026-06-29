"""gRPC servicer — adapts between gRPC layer and business logic."""

import logging

from grpc_stubs import calculator_pb2, calculator_pb2_grpc

from . import core

logger = logging.getLogger(__name__)


class CalculatorServicer(calculator_pb2_grpc.CalculatorServicer):
    """Implements the Calculator gRPC service by delegating to core module."""

    def Add(self, request, context):
        logger.info("Add called: a=%s, b=%s", request.a, request.b)
        result = core.add(request.a, request.b)
        return calculator_pb2.AddResponse(result=result)