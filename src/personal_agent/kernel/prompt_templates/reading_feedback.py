"""Conversation-owned reading explanations and repairable binding feedback."""

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS = {
    "conversation.read.explanation": PromptSpec(
        name="conversation.read.explanation",
        version="2026-10-27.v2-file-path",
        template="line 是正文行号；只看见实际返回的文字。next_read 是可直接调用 read_file 的续读参数；读到末尾不等于此前各行均已读。",
        owner="conversation",
    ),
    "conversation.read.snapshot_mismatch": PromptSpec(
        name="conversation.read.snapshot_mismatch",
        version="2026-10-27.v1",
        template="读取快照与请求引用不一致。",
        owner="conversation",
    ),
    "conversation.read.start_line_out_of_bounds": PromptSpec(
        name="conversation.read.start_line_out_of_bounds",
        version="2026-10-27.v1",
        template="start_line 超出正文范围，正文共 {total_lines} 行。",
        owner="conversation",
    ),
    "conversation.read.start_column_out_of_bounds": PromptSpec(
        name="conversation.read.start_column_out_of_bounds",
        version="2026-10-27.v1",
        template="start_column 超出正文行长度。",
        owner="conversation",
    ),
    "conversation.read.capacity_insufficient": PromptSpec(
        name="conversation.read.capacity_insufficient",
        version="2026-10-27.v1",
        template="输出容量不足以返回正文及续读参数。",
        owner="conversation",
    ),
    "conversation.search.explanation": PromptSpec(
        name="conversation.search.explanation",
        version="v2-draft-ranges",
        template="返回命中行；超长行给出局部正文和 start_column、line_length。line 可用作 read_file 的 start_line。可编辑文稿的 match_ranges 给出补丁行列范围；match_ranges_truncated 为真时，用更具体的词缩小搜索。结束或零命中不表示全文已读或相关语义不存在。",
        owner="conversation",
    ),
    "conversation.search.snapshot_mismatch": PromptSpec(
        name="conversation.search.snapshot_mismatch",
        version="2026-10-27.v1",
        template="搜索快照与请求引用不一致。",
        owner="conversation",
    ),
    "conversation.search.match_out_of_bounds": PromptSpec(
        name="conversation.search.match_out_of_bounds",
        version="2026-10-27.v1",
        template="搜索位置超出本次正文。",
        owner="conversation",
    ),
    "conversation.search.offset_out_of_bounds": PromptSpec(
        name="conversation.search.offset_out_of_bounds",
        version="2026-10-27.v1",
        template="搜索结果分页偏移超出匹配记录数。",
        owner="conversation",
    ),
    "conversation.search.record_capacity_exceeded": PromptSpec(
        name="conversation.search.record_capacity_exceeded",
        version="2026-10-27.v2-file-path",
        template="单条匹配记录超过输出容量，未将截断内容计作完整证据；请用 read_file 读取原资源。",
        owner="conversation",
    ),
}
