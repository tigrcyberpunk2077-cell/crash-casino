"""Роутеры хэндлеров."""

from .balance import router as balance_router
from .common import router as common_router
from .crash import router as crash_router
from .group import router as group_router

__all__ = ["common_router", "balance_router", "crash_router", "group_router"]
