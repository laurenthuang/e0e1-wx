"""摘要：导出 MCP 后台控制服务、配置和 UI 弹窗入口。"""

from __future__ import annotations

from package.mcp_control.config import McpServerConfig
from package.mcp_control.service import McpControlService

__all__ = ["McpControlService", "McpServerConfig"]
