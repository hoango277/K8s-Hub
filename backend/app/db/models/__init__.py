"""Collects every table.

Alembic only sees tables that have been imported into `Base.metadata`, so every
new model MUST be listed here — otherwise `alembic revision --autogenerate`
will silently generate a migration that drops that table.
"""

from app.db.models.message import Message, ToolCall
from app.db.models.rca_report import RcaEvidence, RcaHypothesis, RcaRun
from app.db.models.setting import SettingChange, SettingOverride
from app.db.models.skill import SkillFile, SkillRecord, SkillRun
from app.db.models.thread import ChatThread
from app.db.models.tool import McpServer, McpTool, ToolRun, ToolSetting
from app.db.models.user import RefreshToken, User

__all__ = [
    "ChatThread",
    "McpServer",
    "McpTool",
    "Message",
    "RcaEvidence",
    "RcaHypothesis",
    "RcaRun",
    "RefreshToken",
    "SettingChange",
    "SettingOverride",
    "SkillFile",
    "SkillRecord",
    "SkillRun",
    "ToolCall",
    "ToolRun",
    "ToolSetting",
    "User",
]
