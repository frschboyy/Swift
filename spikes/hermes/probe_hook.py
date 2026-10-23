"""Does a pre_tool_call plugin gate file writes, with no model or key? Run with the venv python.

Creates a throwaway HERMES_HOME, installs a plugin that blocks write_file/patch, then
calls Hermes' own tool dispatcher (model_tools.handle_function_call) directly.
"""
import json, os, sys, tempfile, pathlib

home = pathlib.Path(tempfile.mkdtemp(prefix="hermes_probe_"))
os.environ["HERMES_HOME"] = str(home)
plug = home / "plugins" / "swift_gate"
plug.mkdir(parents=True)
(plug / "plugin.yaml").write_text("name: swift_gate\nversion: 0.1.0\ndescription: probe\n")
(plug / "__init__.py").write_text('''
CALLS = []
def gate(tool_name=None, args=None, **kw):
    CALLS.append((tool_name, args))
    if tool_name in ("write_file", "patch"):
        return {"action": "block", "message": "Swift: file change needs overlay approval"}
def register(ctx):
    ctx.register_hook("pre_tool_call", gate)
''')
(home / "config.yaml").write_text("plugins:\n  enabled:\n    - swift_gate\n")

target = home / "out.txt"
from hermes_cli.plugins import discover_plugins
discover_plugins()
import model_tools
r = model_tools.handle_function_call("write_file", {"path": str(target), "content": "hi"})
print("result:", r[:200])
print("file written:", target.exists())
