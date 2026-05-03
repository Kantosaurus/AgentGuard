"""Tool registry singleton - populated by import side-effects in build_default_registry."""
from .base import Tool, ToolError, ToolRegistry

__all__ = ["Tool", "ToolError", "ToolRegistry", "build_default_registry"]


def build_default_registry() -> ToolRegistry:
    """Construct a registry pre-loaded with all eight production tools."""
    # Imports are local to avoid a circular dependency at module import time.
    from .calculate import Calculate
    from .fetch_url import FetchUrl
    from .list_directory import ListDirectory
    from .read_file import ReadFile
    from .shell_exec import ShellExec
    from .web_request import WebRequest
    from .web_search import WebSearch
    from .write_file import WriteFile

    reg = ToolRegistry()
    for tool in (
        WebSearch(),
        FetchUrl(),
        ReadFile(),
        WriteFile(),
        ListDirectory(),
        WebRequest(),
        ShellExec(),
        Calculate(),
    ):
        reg.register(tool)
    return reg
