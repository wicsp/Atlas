# Repository Runtime Notes

## `apply_patch` Caveat

- In this workspace, `apply_patch` has shown an inconsistent filesystem view: shell commands can read a file, while `apply_patch` reports `No such file or directory` during update/delete verification.
- This was reproduced with temporary probe files: `apply_patch` could add a file, but immediately failed to update or delete that same file.
- When this happens, do not assume the target file is actually missing. Verify with host-side commands such as `sed`, `rg --files`, `ls -l`, or `readlink`.
- If the requested edit is still required, use non-sandbox execution with `sandbox_permissions="require_escalated"` and a narrow command that only touches the intended file.
- Prefer recording this in the final response so future agents understand why `apply_patch` was not used for that edit.

## Sandbox And Command Execution

- Some sandboxed `exec_command` calls can be rejected at process creation with `CreateProcess ... Rejected`, even for commands that exist.
- This does not necessarily mean the Python environment or target file is broken.
- For checks that must reflect the real host environment, run with `sandbox_permissions="require_escalated"`.
- This matters especially for `.venv/bin/python`, directory-size checks such as `du -shL data/models`, and symlink-following operations.
