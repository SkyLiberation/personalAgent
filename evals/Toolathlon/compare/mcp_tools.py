"""Select the common MCP tools for Toolathlon comparison runs."""

from collections.abc import Iterable, Mapping
from typing import TypedDict

from pydantic import RootModel

from evals.Toolathlon.confirmation_probe import mapping
from personal_agent.kernel.config_models import MCPToolConfig


class ToolInventoryAudit(TypedDict):
    request_count: int
    matched_request_count: int
    missing: list[str]
    unexpected: list[str]


def audit_model_tools(expected: frozenset[str], inventories: Iterable[set[str]]) -> ToolInventoryAudit:
    actual = [names for names in inventories if names]
    return ToolInventoryAudit(
        request_count=len(actual),
        matched_request_count=sum(names == expected for names in actual),
        missing=sorted(set().union(*(expected - names for names in actual))) if actual else sorted(expected),
        unexpected=sorted(set().union(*(names - expected for names in actual))),
    )


class ComparisonMCPTools(RootModel[tuple[MCPToolConfig, ...]]):
    @classmethod
    def from_gateway(cls, health: dict, tools: list[dict]) -> "ComparisonMCPTools":
        return cls.model_validate(tool_mappings(health, tools))

    @property
    def remote_names(self) -> frozenset[str]:
        return frozenset(tool.remote_name for tool in self.root)

    @property
    def product_names(self) -> frozenset[str]:
        return frozenset(tool.name or tool.remote_name for tool in self.root)

    def require_available(self, tools: Iterable[Mapping[str, object]]) -> None:
        missing = self.remote_names - {tool["name"] for tool in tools}
        if missing:
            raise ValueError(f"Task gateway is missing shared MCP tools: {', '.join(sorted(missing))}")


READ = {
    "filesystem": {"directory_tree", "get_file_info", "list_allowed_directories", "list_directory",
                   "list_directory_with_sizes", "read_file", "read_multiple_files", "search_files"},
    "excel": {"get_data_validation_info", "get_workbook_metadata", "read_data_from_excel",
              "validate_excel_range", "validate_formula_syntax"},
    "memory": {"open_nodes", "read_graph", "search_nodes"},
    "word": {"find_text_in_document", "get_document_info", "get_document_outline", "get_document_text",
             "get_paragraph_text_from_document", "list_available_documents"},
    "pptx": {"open_presentation", "extract_presentation_text", "extract_slide_text", "get_presentation_info",
             "get_slide_info", "get_server_info", "list_presentations"},
    "pdf-tools": {"get_pdf_info", "read_pdf_pages", "search_pdf_content", "search_pdf_go_page",
                  "search_pdf_info", "search_pdf_next_page", "search_pdf_prev_page"},
    "howtocook": {"mcp_howtocook_getAllRecipes", "mcp_howtocook_getRecipeById", "mcp_howtocook_getRecipesByCategory",
                  "mcp_howtocook_recommendMeals", "mcp_howtocook_whatToEat"},
    "terminal": {"show_security_rules"},
    "yahoo-finance": {"get_historical_stock_prices", "get_stock_price_by_date", "get_stock_info",
                      "get_recommendations", "get_stock_actions", "get_financial_statement",
                      "get_holder_info", "get_yahoo_finance_news"},
    "arxiv_local": {"list_papers", "read_paper", "search_papers"},
    "scholarly": {"search-arxiv", "search-google-scholar", "search-pubmed"},
    "huggingface": {"hub_repo_search", "hub_repo_details"},
    "git": {"git_status", "git_log", "git_show", "git_diff", "git_diff_unstaged", "git_diff_staged", "git_branch"},
    "github": {"search_repositories", "search_code", "get_me", "get_file_contents", "get_commit",
               "list_branches", "list_commits", "list_issues", "get_issue", "issue_read",
               "get_repository", "get_repository_info", "compare_commits"},
    "playwright_with_chunk": {
        "browser_navigate", "browser_navigate_back", "browser_snapshot", "browser_wait_for",
        "browser_snapshot_search", "browser_snapshot_navigate_to_next_span",
        "browser_snapshot_navigate_to_prev_span", "browser_snapshot_navigate_to_span",
    },
}
WRITE = {
    "filesystem": {"create_directory", "edit_file", "write_file", "move_file"},
    "excel": {"apply_formula", "copy_range", "copy_worksheet", "create_chart", "create_pivot_table", "create_table",
              "create_workbook", "create_worksheet", "format_range", "merge_cells", "rename_worksheet",
              "unmerge_cells", "write_data_to_excel"},
    "word": {"add_heading", "add_page_break", "add_paragraph", "add_picture", "add_table",
             "copy_document", "create_custom_style", "create_document", "format_table", "format_table_cell_text",
             "format_text", "highlight_table_header", "insert_line_or_paragraph_near_text", "search_and_replace"},
    "terminal": {"run_command"},
    "pdf-tools": {"merge_pdfs"},
    "playwright_with_chunk": {"browser_click", "browser_press_key", "browser_select_option", "browser_type"},
    "arxiv_local": {"download_paper"},
    "github": {"fork_repository", "update_repository", "rename_repository", "create_branch",
               "create_or_update_file", "push_files"},
    "canvas": {"submit_quiz", "submit_quiz_attempt", "start_quiz_attempt",
               "create_quiz", "create_quiz_question", "create_announcement",
               "create_assignment", "update_quiz", "update_quiz_question", "submit_quiz_answers"},
}
SERVICE_READ = {
    "wandb": {"query_wandb_tool", "query_wandb_entity_projects", "query_weave_traces_tool",
              "count_weave_traces_tool", "query_wandb_support_bot"},
    "web_search": {"search"},
}
SERVICE_PREFIX_READ = {"google_sheet", "google_map", "youtube", "youtube-transcript", "woocommerce", "k8s", "notion", "emails", "google_forms", "google_calendar", "huggingface"}
SERVICE_PREFIX_WRITE = {"google_sheet", "woocommerce", "k8s", "notion", "google_forms", "google_calendar"}
KUBERNETES_OPERATIONS = {
    "kubectl_get": "read", "kubectl_describe": "read", "kubectl_logs": "read",
    "explain_resource": "read", "list_api_resources": "read", "ping": "read",
    "kubectl_create": "create", "kubectl_apply": "update", "kubectl_patch": "update",
    "kubectl_scale": "update", "kubectl_rollout": "update", "kubectl_delete": "delete",
    "install_helm_chart": "create", "upgrade_helm_chart": "update", "uninstall_helm_chart": "delete",
    "port_forward": "update", "stop_port_forward": "update",
}


def tool_mappings(health: dict, tools: list[dict]) -> list[dict[str, object]]:
    mappings = []
    owners = sorted(health["connected_servers"], key=len, reverse=True)
    for server in health["connected_servers"]:
        prefix = server + "-"
        for tool in tools:
            exposed = tool["name"]
            if next((owner for owner in owners if exposed.startswith(owner + "-")), None) != server:
                continue
            name = exposed[len(prefix):]
            canonical = f"{server.replace('-', '_')}.{name.replace('-', '_')}"
            public_read = (
                server == "fetch" and name.startswith("fetch")
                or server in {"arxiv-latex", "youtube-transcript", "rail_12306"}
                and name.startswith(("get", "search", "list", "fetch", "download", "query"))
            )
            normalized = name.replace("-", "_").lower()
            if server == "k8s":
                operation = KUBERNETES_OPERATIONS.get(normalized)
                if operation is not None:
                    options = {} if operation == "read" else {"risk_level": "medium", "data_egress_class": "content"}
                    mappings.append(mapping(exposed, canonical, operation, "external_network", timeout_seconds=120,
                                            credential_mode="service_token", **options))
                continue
            if server == "canvas":
                operation = normalized.removeprefix("canvas_")
                if operation.startswith(("get_", "search_", "list_")):
                    mappings.append(mapping(exposed, canonical, "read", "external_network", timeout_seconds=120,
                                            credential_mode="service_token", data_egress_class="metadata"))
                elif operation in WRITE["canvas"]:
                    mappings.append(mapping(exposed, canonical, "update", "external_network", risk_level="medium",
                                            timeout_seconds=120, credential_mode="service_token",
                                            data_egress_class="content"))
                continue
            if server == "google_map" and normalized.startswith("maps_"):
                mappings.append(mapping(exposed, canonical, "read", "external_network",
                                        semantic_domains=["maps"], resource_types=["route"],
                                        output_contract="route_directions", credential_mode="service_token",
                                        data_egress_class="metadata", timeout_seconds=35))
                continue
            if (normalized in SERVICE_READ.get(server, ())
                or server == "youtube" and normalized.startswith(("channels_", "playlists_", "transcripts_", "videos_"))
                or server == "woocommerce" and (normalized.endswith(("_get", "_list")) or normalized.startswith("woo_reports_") or normalized == "woo_system_status")
                or server == "notion" and normalized.startswith(("api_get_", "api_retrieve_", "api_list_", "api_search_", "api_post_search", "api_post_database_query", "api_post_data_source_query"))
                or server in SERVICE_PREFIX_READ and normalized.startswith(("get_", "list_", "search_", "read_", "find_", "query_", "retrieve_"))):
                mappings.append(mapping(exposed, canonical, "read", "external_network", timeout_seconds=120,
                                        credential_mode="service_token", data_egress_class="metadata"))
                continue
            if server == "emails" and normalized in {"send_email", "reply_email", "forward_email", "reply_to_email", "forward_emails", "reply_to_emails"}:
                mappings.append(mapping(exposed, canonical, "create", "external_network", risk_level="medium",
                                        credential_mode="service_token", data_egress_class="content", timeout_seconds=120))
                continue
            if server == "notion" and normalized == "api_delete_a_block":
                mappings.append(mapping(exposed, canonical, "delete", "external_network", risk_level="medium",
                                        credential_mode="service_token", data_egress_class="content", timeout_seconds=120))
                continue
            if server == "notion" and normalized == "api_create_a_comment":
                mappings.append(mapping(exposed, canonical, "create", "external_network", risk_level="medium",
                                        credential_mode="service_token", data_egress_class="content", timeout_seconds=120))
                continue
            if (server in SERVICE_PREFIX_WRITE and normalized.startswith(("create_", "update_", "add_", "append_", "edit_", "batch_update_", "rename_", "copy_", "patch_", "api_patch_", "api_post_page", "api_post_database", "api_update_", "api_create_a_database"))
                or server == "woocommerce" and normalized.endswith(("_create", "_update"))):
                mappings.append(mapping(exposed, canonical, "update", "external_network", risk_level="medium", timeout_seconds=120,
                                        credential_mode="service_token", data_egress_class="content"))
                continue
            if name in READ.get(server, ()) or public_read:
                if server == "github":
                    mappings.append(mapping(exposed, canonical, "read", "external_network", timeout_seconds=120,
                                            credential_mode="service_token", data_egress_class="metadata"))
                else:
                    mappings.append(mapping(exposed, canonical, "read", "read_local", timeout_seconds=120))
            if name in WRITE.get(server, ()):
                if server == "playwright_with_chunk":
                    mappings.append(mapping(exposed, canonical, "update", "external_network", risk_level="medium",
                                            timeout_seconds=120, data_egress_class="content"))
                elif server == "github":
                    mappings.append(mapping(exposed, canonical, "update", "external_network", risk_level="medium",
                                            timeout_seconds=120, credential_mode="service_token",
                                            data_egress_class="content"))
                else:
                    mappings.append(mapping(exposed, canonical, "update", "write_local", risk_level="medium",
                                            timeout_seconds=120))
    return mappings
