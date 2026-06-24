from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.core.models import local_now
from personal_agent.tools.base import governance_extras, tool_failure, tool_response, tool_success


def _note_summary(note) -> dict:
    return {
        "id": note.id,
        "user_id": note.user_id,
        "title": note.body.title,
        "summary": note.body.summary,
        "source_type": note.source.type,
        "source_ref": note.source.ref,
        "tags": note.tags,
        "version": note.version.model_dump(mode="json"),
        "graph_sync": note.graph_sync.model_dump(mode="json"),
        "updated_at": note.updated_at,
    }


class ListRecentNotesArgs(BaseModel):
    user_id: str = "default"
    limit: int = Field(default=10, ge=1, le=50)


class GetNoteArgs(BaseModel):
    note_id: str = Field(min_length=1)
    user_id: str = "default"
    include_content: bool = True


class FindSimilarNotesArgs(BaseModel):
    query: str = Field(min_length=1)
    user_id: str = "default"
    limit: int = Field(default=8, ge=1, le=30)


class UpdateNoteArgs(BaseModel):
    note_id: str = Field(min_length=1)
    user_id: str = "default"
    title: str | None = None
    content: str | None = None
    summary: str | None = None
    tags: list[str] | None = None


class SupersedeNoteArgs(BaseModel):
    old_note_id: str = Field(min_length=1)
    new_note_id: str = Field(min_length=1)
    user_id: str = "default"
    reason: str = ""


class MarkNoteDeprecatedArgs(BaseModel):
    note_id: str = Field(min_length=1)
    user_id: str = "default"
    reason: str = ""


class MarkNotesConflictedArgs(BaseModel):
    note_ids: list[str] = Field(min_length=2)
    user_id: str = "default"
    reason: str = ""


def build_list_recent_notes_tool(memory) -> BaseTool:
    @tool(
        "list_recent_notes",
        description="列出用户最近写入或更新的知识笔记，用于判断当前知识状态。",
        args_schema=ListRecentNotesArgs,
        response_format="content_and_artifact",
        extras=governance_extras(exposure="public_agent", side_effects=("read_longterm",), permission_scope="memory:read"),
    )
    def list_recent_notes(user_id: str = "default", limit: int = 10):
        notes = memory.list_recent_notes(user_id, limit=limit, include_chunks=False)
        return tool_response(tool_success({"notes": [_note_summary(note) for note in notes]}))

    return list_recent_notes


def build_get_note_tool(memory) -> BaseTool:
    @tool(
        "get_note",
        description="读取一条知识笔记的详情，用于更新、替换、冲突判断或回答前核实。",
        args_schema=GetNoteArgs,
        response_format="content_and_artifact",
        extras=governance_extras(exposure="public_agent", side_effects=("read_longterm",), permission_scope="memory:read"),
    )
    def get_note(note_id: str, user_id: str = "default", include_content: bool = True):
        note = memory.get_note(note_id, user_id=user_id)
        if note is None:
            return tool_response(tool_failure("未找到该用户可访问的笔记。", error_kind="invalid_param"))
        payload = _note_summary(note)
        if include_content:
            payload["content"] = note.body.content
        return tool_response(tool_success({"note": payload}))

    return get_note


def build_find_similar_notes_tool(memory) -> BaseTool:
    @tool(
        "find_similar_notes",
        description="按语义搜索相似知识笔记，用于查重、冲突发现、更新前定位对象。",
        args_schema=FindSimilarNotesArgs,
        response_format="content_and_artifact",
        extras=governance_extras(exposure="public_agent", side_effects=("read_longterm",), permission_scope="memory:read"),
    )
    def find_similar_notes(query: str, user_id: str = "default", limit: int = 8):
        notes = memory.find_similar_notes(user_id, query, limit=limit)
        return tool_response(tool_success({"notes": [_note_summary(note) for note in notes]}))

    return find_similar_notes


def build_update_note_tool(memory) -> BaseTool:
    @tool(
        "update_note",
        description="更新一条知识笔记的标题、正文、摘要或标签。适合用户明确要求修正已有知识时使用。",
        args_schema=UpdateNoteArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="scoped_agent",
            risk_level="medium",
            side_effects=("write_longterm",),
            permission_scope="memory:write",
            timeout_seconds=20,
        ),
    )
    def update_note(
        note_id: str,
        user_id: str = "default",
        title: str | None = None,
        content: str | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
    ):
        note = memory.get_note(note_id, user_id=user_id)
        if note is None:
            return tool_response(tool_failure("未找到该用户可更新的笔记。", error_kind="invalid_param"))
        if title is not None:
            note.body.title = title
        if content is not None:
            note.body.content = content
        if summary is not None:
            note.body.summary = summary
        if tags is not None:
            note.tags = list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
        note.updated_at = local_now()
        saved = memory.update_note(note, user_id=user_id)
        return tool_response(tool_success({"note": _note_summary(saved)}))

    return update_note


def build_supersede_note_tool(memory) -> BaseTool:
    @tool(
        "supersede_note",
        description="声明一条旧知识已被另一条新知识替代，维护知识版本关系。",
        args_schema=SupersedeNoteArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="scoped_agent",
            risk_level="medium",
            side_effects=("write_longterm",),
            permission_scope="memory:version",
            timeout_seconds=20,
        ),
    )
    def supersede_note(
        old_note_id: str,
        new_note_id: str,
        user_id: str = "default",
        reason: str = "",
    ):
        old_note, new_note = memory.supersede_note(
            old_note_id, new_note_id, user_id=user_id, reason=reason
        )
        return tool_response(tool_success({
            "old_note": _note_summary(old_note),
            "new_note": _note_summary(new_note),
        }))

    return supersede_note


def build_mark_note_deprecated_tool(memory) -> BaseTool:
    @tool(
        "mark_note_deprecated",
        description="将一条知识标记为过期但不删除，适合保留历史上下文。",
        args_schema=MarkNoteDeprecatedArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="scoped_agent",
            risk_level="medium",
            side_effects=("write_longterm",),
            permission_scope="memory:version",
            timeout_seconds=20,
        ),
    )
    def mark_note_deprecated(note_id: str, user_id: str = "default", reason: str = ""):
        note = memory.mark_note_deprecated(note_id, user_id=user_id, reason=reason)
        return tool_response(tool_success({"note": _note_summary(note)}))

    return mark_note_deprecated


def build_mark_notes_conflicted_tool(memory) -> BaseTool:
    @tool(
        "mark_notes_conflicted",
        description="将两条或多条知识标记为存在冲突，供后续人工或 Agent 复核。",
        args_schema=MarkNotesConflictedArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="scoped_agent",
            risk_level="medium",
            side_effects=("write_longterm",),
            permission_scope="memory:version",
            timeout_seconds=20,
        ),
    )
    def mark_notes_conflicted(note_ids: list[str], user_id: str = "default", reason: str = ""):
        notes = memory.mark_notes_conflicted(note_ids, user_id=user_id, reason=reason)
        return tool_response(tool_success({"notes": [_note_summary(note) for note in notes]}))

    return mark_notes_conflicted
