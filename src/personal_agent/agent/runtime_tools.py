from __future__ import annotations

from ..tools import (
    CaptureTextTool,
    CaptureUploadTool,
    CaptureUrlTool,
    DeleteNoteTool,
    GraphSearchTool,
    WebSearchTool,
)


class RuntimeToolsMixin:
    def _register_tools(self) -> None:
        if self.capture_service is not None:
            self._tool_registry.register(CaptureUrlTool(self.capture_service))
            self._tool_registry.register(
                CaptureUploadTool(self.capture_service, self.settings.data_dir / "uploads")
            )
        self._tool_registry.register(GraphSearchTool(self.graph_store))
        self._tool_registry.register(CaptureTextTool(self))
        self._tool_registry.register(DeleteNoteTool(self.store, self.graph_store, self.pending_action_store))
        if self.settings.firecrawl_api_key:
            from ..capture.providers.web_search import FirecrawlWebSearchProvider
            web_provider = FirecrawlWebSearchProvider(self.settings)
            self._tool_registry.register(WebSearchTool(self.settings, web_provider, self.capture_service))

    @property
    def _web_search_available(self) -> bool:
        return bool(self.settings.firecrawl_api_key)

    def list_tools(self) -> list:
        return self._tool_registry.list_tools()

    def execute_tool(self, name: str, **kwargs: object):
        return self._tool_registry.execute(name, **kwargs)


