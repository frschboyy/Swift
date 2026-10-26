"""Every Swift tool a provider can be given: email and present (ADR-010), calendar (ADR-011 W1),
desktop (ADR-012 D1-D2). A workflow run narrows this to its manifest's ``needs``."""

from __future__ import annotations

from swift.workflows.calendar import CALENDAR_TOOLS
from swift.workflows.desktop_tools import DESKTOP_TOOLS
from swift.workflows.tools import TOOLS, ToolSpec

ALL_TOOLS: tuple[ToolSpec, ...] = TOOLS + CALENDAR_TOOLS + DESKTOP_TOOLS
