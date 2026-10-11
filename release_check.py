#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def tracked_files():
    output = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=str(ROOT),
    )
    return [
        ROOT / Path(raw.decode("utf-8"))
        for raw in output.split(b"\0")
        if raw
    ]


def build_patterns():
    patterns = [
        re.compile(rb"ghp_[A-Za-z0-9]+"),
        re.compile(rb"github_pat_[A-Za-z0-9_]+"),
        re.compile(rb'"(?:access_token|refresh_token|accessToken|refreshToken)"\s*:\s*"'),
        re.compile(rb"C:\\\\Users\\\\Administrator"),
    ]

    try:
        config_path = (
            Path(os.environ.get("APPDATA", ""))
            / "MinecraftLauncher"
            / "config.json"
        )
        account = json.loads(
            config_path.read_text(encoding="utf-8")
        ).get("account", {})

        if account.get("display_name"):
            patterns.append(
                re.compile(
                    re.escape(account["display_name"]).encode("utf-8")
                )
            )

        if account.get("uuid"):
            patterns.append(
                re.compile(
                    re.escape(account["uuid"]).encode("ascii")
                )
            )
    except Exception:
        pass

    return patterns


def main():
    patterns = build_patterns()
    failures = []
    forbidden_names = {
        "config.json",
        "auth.json",
        "launcher_profiles.json",
        "avatar.png",
    }

    for relative in tracked_files():
        name = relative.name.lower()

        if relative.name == "release_check.py":
            continue

        if name in forbidden_names or name.endswith(".log"):
            failures.append(f"{relative}: 敏感文件名被跟踪")
            continue

        data = relative.read_bytes()
        for pattern in patterns:
            if pattern.search(data):
                failures.append(
                    f"{relative}: 检测到疑似正版登录信息"
                )
                break

    if failures:
        print("Release check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("Release check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
