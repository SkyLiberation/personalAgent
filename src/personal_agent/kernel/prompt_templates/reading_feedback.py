"""Conversation-owned reading explanations and repairable binding feedback."""

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS = {
    "conversation.read.explanation": PromptSpec(
        name="conversation.read.explanation",
        version="2026-10-27.v1",
        template="line 是正文行号；只看见实际返回的文字。next_read 是可直接调用 read_artifact 的续读参数；读到末尾不等于此前各行均已读。",
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
        version="2026-10-27.v1",
        template="只返回命中行的正文，超长行给出局部文字与 start_column、line_length；line 可作为 read_artifact 的 start_line。搜索结束或零命中不表示全文已读或相关语义不存在。",
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
        version="2026-10-27.v1",
        template="单条匹配记录超过输出容量，未将截断内容计作完整证据；请用 read_artifact 读取原资源。",
        owner="conversation",
    ),
    "conversation.observation.omission_marker": PromptSpec(
        name="conversation.observation.omission_marker",
        version="2026-10-27.v1",
        template="\n... [{omitted} characters omitted from the middle] ...\n",
        owner="conversation",
    ),
    "conversation.observation.window_explanation": PromptSpec(
        name="conversation.observation.window_explanation",
        version="2026-10-27.v1",
        template="仅返回本次顺序窗口；continuation 为空只表示此后缀结束，不证明累计全文已读。",
        owner="conversation",
    ),
    "conversation.citations.range_invalid": PromptSpec(
        name="conversation.citations.range_invalid",
        version="2026-10-27.v1",
        template="引用 {evidence_id} 不是可见的连续多行范围；结束行须大于起始行，且每行已完整返回。",
        owner="conversation",
    ),
    "conversation.citations.coordinate_unavailable": PromptSpec(
        name="conversation.citations.coordinate_unavailable",
        version="2026-10-27.v1",
        template="引用 {evidence_id} 中的 {missing} 未完整返回或不存在。请选择 citations 中实际可见的行；连续范围不能跳过缺行，部分行须原样保留字符范围，需要其他内容时继续读取。",
        owner="conversation",
    ),
    "conversation.final_revision.base_unavailable": PromptSpec(
        name="conversation.final_revision.base_unavailable",
        version="2026-10-27.v1",
        template="只能修订本次交互中最新可见的完整回答；请复制其 resource_ref，或提交完整新稿。",
        owner="conversation",
    ),
    "conversation.final_revision.segment_out_of_bounds": PromptSpec(
        name="conversation.final_revision.segment_out_of_bounds",
        version="2026-10-27.v1",
        template="修改位置不在当前基稿 segments 中；整批修改未应用。",
        owner="conversation",
    ),
    "conversation.final_revision.citation_rejected": PromptSpec(
        name="conversation.final_revision.citation_rejected",
        version="2026-10-27.v1",
        template="整批修改未应用：{error}",
        owner="conversation",
    ),
}
