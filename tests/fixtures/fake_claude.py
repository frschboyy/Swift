"""Stand-in for the `claude` CLI in executor tests.

FAKE_CLAUDE_MODE:
  replay  - print FAKE_CLAUDE_FIXTURE line by line (FAKE_CLAUDE_DELAY s apart)
  hang    - print the init event, start a sleeping child process, then sleep
  crash   - print the init event, write to stderr, exit 3 without a result
  garbage - print non-JSON noise and a huge line, then a success result
The prompt read from stdin is written to FAKE_CLAUDE_STDIN_OUT; the child's
PID (hang mode) to FAKE_CLAUDE_CHILD_PID.
"""

import json
import os
import subprocess
import sys
import time

prompt = sys.stdin.read()
if out := os.environ.get("FAKE_CLAUDE_STDIN_OUT"):
    with open(out, "w", encoding="utf-8") as f:
        f.write(prompt)
        f.write("\n--argv--\n" + json.dumps(sys.argv[1:]))

mode = os.environ.get("FAKE_CLAUDE_MODE", "replay")
delay = float(os.environ.get("FAKE_CLAUDE_DELAY", "0"))
INIT = json.dumps({"type": "system", "subtype": "init", "cwd": os.getcwd()})


def emit(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


if mode == "replay":
    with open(os.environ["FAKE_CLAUDE_FIXTURE"], encoding="utf-8") as f:
        for line in f:
            emit(line.rstrip("\n"))
            time.sleep(delay)
elif mode == "hang":
    emit(INIT)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    if pid_out := os.environ.get("FAKE_CLAUDE_CHILD_PID"):
        with open(pid_out, "w") as f:
            f.write(str(child.pid))
    emit(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "sleep 600"}}]}}))
    time.sleep(600)
elif mode == "crash":
    emit(INIT)
    sys.stderr.write("Error: something broke inside the CLI\n")
    sys.exit(3)
elif mode == "garbage":
    emit("this is not json")
    emit("[1, 2, 3]")
    emit(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "x" * 200_000}]}}))
    emit(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "Survived the noise."}))
