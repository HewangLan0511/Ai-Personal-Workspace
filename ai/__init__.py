#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 层（阶段5）。

- `providers/`   Provider 抽象与实现（新增供应商只改 registry）
- `credentials.py` 凭据管理（系统凭据库，红线 V1）
- `context.py`   上下文装配与双模式隔离（红线 V2）
- `prompt_renderer.py` + `prompt/` 提示词模板
- `service.py`   编排层（sidecar /ai/* 的业务实现）
"""
