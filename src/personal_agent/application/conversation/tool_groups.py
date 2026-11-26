"""Classify business capabilities exposed by the Conversation main loop."""

from personal_agent.kernel.contracts.tool import ConversationToolGroup

from .skills import LOAD_SKILL_CAPABILITY


_GROUP_BY_CAPABILITY: dict[str, ConversationToolGroup] = {
    "bash": "bash",
    "read_file": "files_and_artifacts",
    "grep_file": "files_and_artifacts",
    "write_artifact": "files_and_artifacts",
    LOAD_SKILL_CAPABILITY: "skills",
    "prepare_conversation_knowledge_save": "knowledge",
    "prepare_knowledge_delete": "knowledge",
    "search_personal_knowledge": "knowledge",
    "list_personal_knowledge": "knowledge",
    "graph_search": "knowledge",
    "inspect_knowledge_gaps": "knowledge",
    "list_recent_notes": "knowledge",
    "get_note": "knowledge",
    "find_similar_notes": "knowledge",
    "list_research_subscriptions": "research_and_operations",
    "list_research_runs": "research_and_operations",
    "get_research_digest": "research_and_operations",
    "inspect_worker_queue": "research_and_operations",
    "web_read": "network",
    "web_search": "network",
    "prepare_workspace_changes": "workspace_changes",
    "retrieval_experiment": "retrieval_experiment",
}


def conversation_tool_group(capability_name: str) -> ConversationToolGroup:
    """Dynamically registered capabilities use the extensions group by default."""
    return _GROUP_BY_CAPABILITY.get(capability_name, "extensions")
