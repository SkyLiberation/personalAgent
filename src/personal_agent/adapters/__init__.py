"""Adapters layer: external entrypoints (HTTP API, CLI, Feishu/Lark).

The top of the stack. Translates external protocols into calls down into
orchestration and the layers below. Nothing depends on adapters.
"""
