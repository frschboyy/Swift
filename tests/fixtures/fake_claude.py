"""Stand-in for a running `claude` that has started a child process (tree-kill test).

Starts a sleeping child, writes its PID to FAKE_CLAUDE_CHILD_PID, then sleeps.
"""

import os
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
with open(os.environ["FAKE_CLAUDE_CHILD_PID"], "w") as f:
    f.write(str(child.pid))
time.sleep(600)
