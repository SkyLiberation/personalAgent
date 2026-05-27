from __future__ import annotations

from ..tools import (
    build_capture_text_tool,
    build_capture_upload_tool,
    build_capture_url_tool,
    build_delete_note_tool,
    build_graph_search_tool,
    build_web_search_tool,
)


class RuntimeToolsMixin:
    def _register_tools(self) -> None:
        if self.capture_service is not None:
            self._tool_executor.register(build_capture_url_tool(self.capture_service))
            self._tool_executor.register(
                build_capture_upload_tool(self.capture_service, self.settings.data_dir / "uploads")
            )
        self._tool_executor.register(build_graph_search_tool(self.graph_store))
        self._tool_executor.register(build_capture_text_tool(
            lambda text, source_type="text", user_id="default": self.execute_capture(
                text=text, source_type=source_type, user_id=user_id,
            )
        ))
        self._tool_executor.register(build_delete_note_tool(self.store, self.graph_store, self.pending_action_store))
        if self.settings.firecrawl_api_key:
            from ..capture.providers.web_search import FirecrawlWebSearchProvider
            web_provider = FirecrawlWebSearchProvider(self.settings)
            self._tool_executor.register(build_web_search_tool(self.settings, web_provider, self.capture_service))

    @property
    def _web_search_available(self) -> bool:
        return bool(self.settings.firecrawl_api_key)

    def list_tools(self) -> list:
        return self._tool_executor.list_tools()

    def execute_tool(self, name: str, **kwargs: object):
        return self._tool_executor.invoke_direct(name, **kwargs)
