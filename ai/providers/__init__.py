#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Provider 抽象层（阶段5 ★ 核心）。

对外只暴露 `registry`（注册中心）与 `base`（接口定义），
业务代码**只应通过 registry 取 Provider**，不直接 import 具体实现 ——
这样新增 Provider 才不需要改业务代码。
"""

from . import registry  # noqa: F401
from .base import (  # noqa: F401
    AIProvider,
    Chunk,
    Message,
    ProviderConfig,
    ProviderError,
)

__all__ = [
    "registry",
    "AIProvider",
    "Chunk",
    "Message",
    "ProviderConfig",
    "ProviderError",
]
