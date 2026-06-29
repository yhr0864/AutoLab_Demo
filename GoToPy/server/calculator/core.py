"""Core calculation functions — pure business logic, no gRPC dependency."""

import logging

logger = logging.getLogger(__name__)


def add(a: float, b: float) -> float:
    """Add two numbers."""
    result = a + b
    logger.debug("add(%.2f, %.2f) = %.2f", a, b, result)
    return result


def subtract(a: float, b: float) -> float:
    """Subtract b from a."""
    result = a - b
    logger.debug("subtract(%.2f, %.2f) = %.2f", a, b, result)
    return result


def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    result = a * b
    logger.debug("multiply(%.2f, %.2f) = %.2f", a, b, result)
    return result


def divide(a: float, b: float) -> float:
    """Divide a by b. Raises ValueError if b is zero."""
    if b == 0:
        raise ValueError("Division by zero")
    result = a / b
    logger.debug("divide(%.2f, %.2f) = %.2f", a, b, result)
    return result