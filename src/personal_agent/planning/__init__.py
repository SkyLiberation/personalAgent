"""Planning layer: routing, workflow selection, query planning, replanning.

Decides whether a task runs a fixed workflow or a dynamically planned sequence,
and revises plans when results disappoint. Depends on governance/tools/
application/memory/infra/kernel; orchestration sits above it.
"""
