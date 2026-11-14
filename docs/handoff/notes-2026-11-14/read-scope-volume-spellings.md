# Read scope: volume spellings (worktree a2-question-state-42bf6d, branch claude/strange-cori-8f1753)

Failing test: test_seams_audit_privacy.py::test_a_whole_drive_or_volume_spelled_another_way_is_never_a_blanket_read

Both (a) and (b) are true, and there is a third finding in the same check.

1. (a) The test assumes one PC's layout. On this PC QueryDosDevice gives C: = \Device\HarddiskVolume4, E: = HarddiskVolume1.
   HarddiskVolume3 is a volume with no file system, so realpath raises WinError 1005. Commit 1824a4c makes the test look up the drive's device name. Label: root.
2. (b) verdict() raised on any volume spelling it couldn't resolve: WinError 6 for HarddiskVolume1/2/5..99, 1005 for 3.
   That also covers \\127.0.0.2\c$ (1231) and \\<PC>.local\c$ (1326). In a run, the exception becomes an SDK "error" control
   response. The bundled CLI reports it as "Tool permission request failed" (read from the CLI's strings, not run end to end).
   So the read was most likely refused, but with no card and no log line. in_command treated the OSError as "not a path"
   and let the command go on to a card. Fix: verdict returns "never". Commit 6cc953e. Label: root. PRODUCT RULE: needs a review by someone else.
3. (new) realpath keeps the \\?\ prefix: C:'s volume GUID or device spelling resolved to \\?\c:\..., which missed the never list.
   Proven: Swift's real log via \\?\Volume{df5b4c97-...}\ got "ask", not "never". Fix: _norm maps the result back with _local.
   Commit a98e1f1. Label: root. PRODUCT RULE: needs a review by someone else.

For the reviewer: a Read of another computer's share that fails to resolve is now refused with the "holds secrets" message.
It used to fail as an error. Whether the CLI's Read tool opens \\?\Volume{...} paths at all is unproven.
