#!/usr/bin/env python3
"""Ask privately for a Qwen key and configure the project's root .env. No dependencies."""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import re
import sys
import tempfile
import warnings

BASE_URL = "https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1"
MODEL = "qwen3.7-plus"
MODEL_KEYS = (
    "TIWALA_COORDINATOR_MODEL", "TIWALA_TREASURY_MODEL", "TIWALA_CHECKER_MODEL",
    "TIWALA_NEGOTIATOR_MODEL", "TIWALA_SUPPLIER_AGENT_MODEL",
)
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def find_project(explicit: str | None = None) -> Path:
    if explicit:
        candidates = [Path(explicit).expanduser().resolve()]
    else:
        script = Path(__file__).resolve().parent
        cwd = Path.cwd()
        candidates = [script, *script.parents, cwd, *cwd.parents,
                      Path.home() / "Downloads" / "tiwala_SEPOLIA"]
    for candidate in candidates:
        if (candidate / "agent" / "tiwala_agent" / "llm.py").is_file():
            return candidate
    raise ValueError("Cannot find Tiwala. Run from its project folder or add --project /path/to/Tiwala.")


def update_env(path: Path, key: str) -> None:
    key = key.strip()
    # Values stay unquoted for compatibility with Tiwala's loader and shell sourcing.
    if not key or not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
        raise ValueError("Enter only the API key, with no quotes, spaces, or other characters.")
    if path.is_symlink():
        raise ValueError("The .env is a symbolic link; choose the actual project folder.")
    values = {
        "DASHSCOPE_API_KEY": key,
        "DASHSCOPE_BASE_URL": BASE_URL,
        "TIWALA_LLM_PROVIDER": "qwen",
        "QWEN_ENABLE_THINKING": "true",
        **dict.fromkeys(MODEL_KEYS, MODEL),
    }
    original = ""
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as f:
            original = f.read()
    newline = "\r\n" if "\r\n" in original else "\n"
    lines, seen = [], set()
    for line in original.splitlines(keepends=True):
        match = ASSIGNMENT.match(line)
        name = match.group(1) if match else None
        if name in values:
            if name not in seen:
                lines.append(f"{name}={values[name]}{newline}")
                seen.add(name)
        else:
            lines.append(line)
    if lines and not lines[-1].endswith(("\r", "\n")):
        lines[-1] += newline
    lines.extend(f"{name}={value}{newline}" for name, value in values.items() if name not in seen)
    # Temporary file starts owner-only; replace atomically so interruption cannot truncate .env.
    fd, temporary = tempfile.mkstemp(prefix=".qwen-config-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write("".join(lines))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Tiwala folder; normally detected automatically")
    args = parser.parse_args()
    try:
        project = find_project(args.project)
        print(f"Configuring: {project / '.env'}")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("Paste your Qwen / DASHSCOPE API key (hidden): ")
        update_env(project / ".env", key)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Configuration was not changed.")
        return 1
    except getpass.GetPassWarning:
        print("Use an interactive terminal so your API key can be entered privately.", file=sys.stderr)
        return 1
    except (ValueError, OSError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Saved. Wallet and negotiation agents are configured for {MODEL}, thinking enabled.")
    print("The .env is readable and writable only by your user. Restart Tiwala to load it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
