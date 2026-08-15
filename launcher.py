import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import webview


class LaunchState:
    def __init__(self):
        self._lock = threading.Lock()
        self.progress = 0
        self.message = ""
        self.error = ""
        self.process = None

    def update(self, progress, message, error=""):
        with self._lock:
            self.progress = progress
            self.message = message
            self.error = error

    def set_process(self, process):
        with self._lock:
            self.process = process

    def snapshot(self):
        with self._lock:
            running = self.process is not None and self.process.poll() is None
            return {
                "progress": self.progress,
                "message": self.message,
                "error": self.error,
                "running": running,
            }


class Api:
    def __init__(self, config_path=None):
        if config_path is None:
            base = Path(os.environ.get("APPDATA") or Path.home())
            config_path = base / "MinecraftLauncher" / "config.json"

        self.config_path = Path(config_path)
        self.imported_info = None
        self.launch_state = LaunchState()

    def _read_config(self):
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_config(self, data):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_version(self):
        value = self._read_config().get("version")

        if isinstance(value, str) and value.strip():
            return value.strip()

        return None

    def save_version(self, value):
        data = self._read_config()
        data["version"] = str(value)
        self._write_config(data)
        return True

    def _load_imported_info(self):
        data = self._read_config().get("imported")
        return data if isinstance(data, dict) else None

    def _save_imported_info(self, info):
        data = self._read_config()
        data["version"] = info["version_id"]
        data["imported"] = info
        self._write_config(data)

    def _discover_version_folder(self, selected):
        selected = Path(selected).resolve()
        candidates = []

        def add_candidate(folder):
            folder = Path(folder)
            if not folder.is_dir():
                return

            for json_path in folder.glob("*.json"):
                jar_path = folder / f"{json_path.stem}.jar"
                if jar_path.exists():
                    candidates.append((folder, json_path, jar_path))

        add_candidate(selected)

        version_root = selected / "versions"
        if selected.name == "versions":
            version_root = selected

        if version_root.is_dir():
            for child in version_root.iterdir():
                add_candidate(child)

        if not candidates:
            return None

        saved_version = self.load_version()
        for folder, json_path, jar_path in candidates:
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                if saved_version and data.get("id") == saved_version:
                    return folder, json_path, jar_path, data
            except Exception:
                continue

        folder, json_path, jar_path = max(
            candidates,
            key=lambda candidate: candidate[1].stat().st_mtime_ns,
        )

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

        return folder, json_path, jar_path, data

    def _read_account(self, game_root):
        username = "Player"
        profile_id = "00000000-0000-0000-0000-000000000000"

        try:
            data = json.loads(
                (game_root / "launcher_profiles.json").read_text(encoding="utf-8")
            )
            auth_database = data.get("authenticationDatabase", {})

            for account in auth_database.values():
                if account.get("username"):
                    username = account["username"]

                profiles = account.get("profiles", {})
                for uid, profile in profiles.items():
                    if profile.get("displayName"):
                        username = profile["displayName"]
                    profile_id = uid

            selected_user = data.get("selectedUser", {})
            if selected_user.get("profile"):
                profile_id = selected_user["profile"]
        except Exception:
            pass

        return username, profile_id

    def import_folder(self):
        try:
            selected = webview.windows[0].create_file_dialog(
                webview.FileDialog.FOLDER,
                directory=str(Path.home()),
            )
        except Exception as exc:
            return {"ok": False, "message": f"无法打开文件夹选择器：{exc}"}

        if not selected:
            return {"ok": False, "message": "未选择文件夹"}

        return self.import_path(Path(selected[0]))

    def import_path(self, selected):
        found = self._discover_version_folder(selected)

        if not found:
            return {
                "ok": False,
                "message": "未找到游戏版本配置，请选择包含 versions 或版本 json+jar 的文件夹",
            }

        version_folder, version_json_path, version_jar_path, version_data = found
        version_id = version_data.get("id") or version_json_path.stem

        if version_folder.parent.name == "versions":
            game_root = version_folder.parent.parent
        elif selected.name == "versions":
            game_root = selected.parent
        elif (selected / "versions").is_dir():
            game_root = selected
        else:
            game_root = selected

        game_root = Path(game_root).resolve()
        libraries_root = game_root / "libraries"
        assets_root = game_root / "assets"
        natives = version_folder / f"{version_id}-natives"

        if not natives.is_dir():
            natives = version_folder / "natives"

        asset_index = (
            version_data.get("assets")
            or version_data.get("assetIndex", {}).get("id")
            or "legacy"
        )
        username, profile_id = self._read_account(game_root)

        info = {
            "ok": True,
            "version_id": version_id,
            "version_folder": str(version_folder),
            "version_json": str(version_json_path),
            "version_jar": str(version_jar_path),
            "game_root": str(game_root),
            "libraries_root": str(libraries_root),
            "assets_root": str(assets_root),
            "asset_index": asset_index,
            "natives": str(natives),
            "main_class": version_data.get(
                "mainClass", "net.minecraft.client.main.Main"
            ),
            "username": username,
            "uuid": profile_id,
            "message": f"已导入 {version_id}",
        }

        self.imported_info = info
        self._save_imported_info(info)
        return info

    def _find_java(self):
        candidates = [
            Path(r"I:\hmcl\bin\javaw.exe"),
            Path(r"I:\hmcl\bin\java.exe"),
            Path(r"C:\Program Files\Java\latest\bin\javaw.exe"),
            Path(r"C:\Program Files\Java\latest\bin\java.exe"),
            Path(r"C:\Program Files\Java\jdk-11\bin\java.exe"),
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        which = shutil.which("javaw") or shutil.which("java")
        return Path(which) if which else None

    def _build_launch_command(self, info):
        version_json = json.loads(
            Path(info["version_json"]).read_text(encoding="utf-8")
        )
        libraries_root = Path(info["libraries_root"])
        classpath = [info["version_jar"]]

        for library in version_json.get("libraries", []):
            artifact_path = (
                library.get("downloads", {}).get("artifact", {}).get("path")
            )

            if artifact_path:
                library_file = libraries_root / artifact_path
            else:
                name_parts = str(library.get("name", "")).split(":")

                if len(name_parts) < 3:
                    continue

                group, artifact, version = name_parts[:3]
                file_name = f"{artifact}-{version}"

                if len(name_parts) > 3 and name_parts[3]:
                    file_name += f"-{name_parts[3]}"

                artifact_path = (
                    f"{group.replace('.', '/')}/{artifact}/{version}/{file_name}.jar"
                )
                library_file = libraries_root / artifact_path

            if not library_file.exists():
                continue

            classpath.append(str(library_file))

        java = self._find_java()
        if not java:
            raise RuntimeError("未找到可用的 Java")

        natives = info["natives"]
        args = [
            str(java),
            "-Xms512m",
            "-Xmx4G",
            f"-Djava.library.path={natives}",
            f"-Djna.tmpdir={natives}",
            f"-Dorg.lwjgl.system.SharedLibraryExtractPath={natives}",
            f"-Dio.netty.native.workdir={natives}",
            "-Dminecraft.launcher.brand=MinecraftLauncher",
            "-Dminecraft.launcher.version=1.0",
            "-cp",
            os.pathsep.join(classpath),
            "-DFabricMcEmu= net.minecraft.client.main.Main ",
            info["main_class"],
            "--username",
            info["username"],
            "--version",
            info["version_id"],
            "--gameDir",
            info["version_folder"],
            "--assetsDir",
            info["assets_root"],
            "--assetIndex",
            info["asset_index"],
            "--uuid",
            info["uuid"],
            "--accessToken",
            "0",
            "--clientId",
            info["uuid"],
            "--xuid",
            "",
            "--userType",
            "legacy",
            "--versionType",
            "release",
        ]

        return args, Path(info["version_folder"])

    def launch_game(self):
        info = self.imported_info or self._load_imported_info()

        if not info:
            return {"ok": False, "message": "请先导入文件夹"}

        if self.launch_state.process and self.launch_state.process.poll() is None:
            return {"ok": False, "message": "游戏已经在启动"}

        self.imported_info = info
        self.launch_state.update(2, "准备启动")
        thread = threading.Thread(
            target=self._launch_worker,
            args=(info,),
            daemon=True,
        )
        thread.start()

        return {"ok": True}

    def stop_game(self):
        process = self.launch_state.process

        if process is None or process.poll() is not None:
            return {"ok": False, "message": "游戏未在运行"}

        self.launch_state.update(95, "正在关闭游戏")
        thread = threading.Thread(
            target=self._stop_worker,
            args=(process,),
            daemon=True,
        )
        thread.start()

        return {"ok": True}

    def _stop_worker(self, process):
        try:
            process.terminate()

            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

        self.launch_state.update(0, "游戏已关闭")

    def get_launch_status(self):
        return self.launch_state.snapshot()

    def _launch_worker(self, info):
        try:
            self.launch_state.update(8, "正在解析版本配置")
            json.loads(Path(info["version_json"]).read_text(encoding="utf-8"))

            self.launch_state.update(20, "正在检查游戏文件")
            for key in (
                "version_jar",
                "game_root",
                "libraries_root",
                "assets_root",
                "natives",
            ):
                if not Path(info[key]).exists():
                    raise RuntimeError(f"缺少必要文件：{info[key]}")

            self.launch_state.update(45, "正在构建启动参数")
            args, cwd = self._build_launch_command(info)

            self.launch_state.update(75, "正在启动 Minecraft")
            log_path = self.config_path.parent / "logs" / "latest.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            creationflags = 0

            with open(log_path, "a", encoding="utf-8", errors="replace") as log:
                process = subprocess.Popen(
                    args,
                    cwd=str(cwd),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )

            self.launch_state.set_process(process)
            self.launch_state.update(100, "游戏已启动")
        except Exception as exc:
            self.launch_state.update(0, "启动失败", str(exc))


def resource_path(relative_path):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


if __name__ == "__main__":
    api = Api()

    webview.create_window(
        "Minecraft Launcher",
        resource_path("index.html"),
        width=1280,
        height=720,
        min_size=(960, 640),
        background_color="#ffffff",
        js_api=api,
    )
    webview.start()
