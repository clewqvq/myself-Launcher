import base64
import getpass
import glob
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

import webview

try:
    import certifi
except ImportError:
    certifi = None


MICROSOFT_CLIENT_ID = "00000000402b5328"
MICROSOFT_SCOPE = "service::user.auth.xboxlive.com::MBI_SSL"
DEVICE_CODE_URL = "https://login.live.com/oauth20_connect.srf"
MICROSOFT_TOKEN_URL = "https://login.live.com/oauth20_token.srf"
XBL_AUTH_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MINECRAFT_LOGIN_URL = (
    "https://api.minecraftservices.com/authentication/login_with_xbox"
)
MINECRAFT_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
MINECRAFT_ENTITLEMENTS_URL = (
    "https://api.minecraftservices.com/entitlements/mcstore"
)
BMCLAPI_BASE = "https://bmclapi2.bangbang93.com"
MCIM_BASE = "https://mod.mcimirror.top"
CURSEFORGE_GAME_ID = 432
DOWNLOAD_ENDPOINTS = {
    "manifest": (
        "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
        f"{BMCLAPI_BASE}/mc/game/version_manifest_v2.json",
    ),
    "libraries": (
        f"{BMCLAPI_BASE}/maven",
        "https://libraries.minecraft.net",
    ),
    "assets": (
        f"{BMCLAPI_BASE}/assets",
        "https://resources.download.minecraft.net",
    ),
    "maven": (
        f"{BMCLAPI_BASE}/maven",
        "https://maven.minecraftforge.net",
    ),
}
MODRINTH_PROJECT_TYPE = {
    "mods": "mod",
    "shaders": "shader",
    "resourcepacks": "resourcepack",
}
JAVA_RUNTIME_MANIFEST_URL = (
    "https://launchermeta.mojang.com/v1/products/java-runtime/"
    "2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"
)
VERSION_MANIFEST_URLS = (
    *DOWNLOAD_ENDPOINTS["manifest"],
)


class MicrosoftAuthError(RuntimeError):
    def __init__(self, message, code=""):
        super().__init__(message)
        self.code = code


def _request_json(url, form=None, payload=None, headers=None):
    request_headers = {"Accept": "application/json"}
    data = None
    method = "GET"

    if form is not None:
        method = "POST"
        data = urllib.parse.urlencode(form).encode("utf-8")
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        method = "POST"
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )
    context = None

    if certifi is not None:
        context = ssl.create_default_context(cafile=certifi.where())

    for attempt in range(3):
        try:
            with urllib.request.urlopen(
                request,
                timeout=30,
                context=context,
            ) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            _log_http_error(url, exc.code, raw)

            try:
                body = json.loads(raw)
            except Exception:
                body = {"error": "http_error", "error_description": raw}

            message = (
                body.get("error_description")
                or body.get("message")
                or raw.strip()
                or f"HTTP {exc.code}"
            )
            detail = str(message)[:500]
            raise MicrosoftAuthError(
                f"{url} 返回 HTTP {exc.code}：{detail}",
                body.get("error", str(exc.code)),
            ) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionResetError) as exc:
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue

            reason = getattr(exc, "reason", None) or exc
            raise MicrosoftAuthError(
                f"无法连接微软服务：{reason}，请检查网络后重试"
            ) from exc


def _post_form(url, fields):
    return _request_json(url, form=fields)


def _post_json(url, payload, headers=None):
    return _request_json(url, payload=payload, headers=headers)


def _get_json(url, headers=None):
    return _request_json(url, headers=headers)


def _log_http_error(url, status, raw):
    try:
        base = Path(os.environ.get("APPDATA") or Path.home())
        log_path = base / "MinecraftLauncher" / "logs" / "auth.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(log_path, "a", encoding="utf-8", errors="replace") as log:
            log.write(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"{url} -> HTTP {status}\n{raw}\n\n"
            )
    except Exception:
        pass


def _network_context():
    if certifi is None:
        return None
    return ssl.create_default_context(cafile=certifi.where())


_SOURCE_HEALTH = {}
_SOURCE_HEALTH_LOCK = threading.Lock()
_DOWNLOAD_CANCEL = threading.Event()


class DownloadCancelled(RuntimeError):
    pass


def _source_host(url):
    try:
        return urllib.parse.urlsplit(url).netloc.lower()
    except Exception:
        return ""


def _rank_urls(urls):
    unique = list(dict.fromkeys(url for url in urls if url))
    now = time.time()

    def score(url):
        with _SOURCE_HEALTH_LOCK:
            entry = _SOURCE_HEALTH.get(_source_host(url))
        if not entry or now - entry[1] > 900:
            return 0
        return entry[0]

    return sorted(unique, key=score, reverse=True)


def _record_source(url, ok):
    host = _source_host(url)
    if not host:
        return

    with _SOURCE_HEALTH_LOCK:
        score = _SOURCE_HEALTH.get(host, (0, 0))[0]
        score = min(score + 2, 10) if ok else max(score - 3, -10)
        _SOURCE_HEALTH[host] = (score, time.time())


def _hidden_process_kwargs():
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {
            "creationflags": subprocess.CREATE_NO_WINDOW,
        }
    return {}


def _fetch_json_urls(urls, timeout=12, attempts=2):
    last_error = None

    for url in _rank_urls(urls):
        for attempt in range(max(1, attempts)):
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "MinecraftLauncher/1.0",
                    },
                )
                with urllib.request.urlopen(
                    request,
                    timeout=timeout,
                    context=_network_context(),
                ) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                    _record_source(url, True)
                    return json.loads(raw)
            except Exception as exc:
                last_error = exc
                _record_source(url, False)
                if attempt + 1 < attempts:
                    time.sleep(0.8)

    raise RuntimeError(f"无法读取下载信息：{last_error}")


def _fetch_text_urls(urls, timeout=12, attempts=2):
    last_error = None

    for url in _rank_urls(urls):
        for attempt in range(max(1, attempts)):
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "MinecraftLauncher/1.0"},
                )
                with urllib.request.urlopen(
                    request,
                    timeout=timeout,
                    context=_network_context(),
                ) as response:
                    text = response.read().decode(
                        "utf-8",
                        errors="replace",
                    )
                    _record_source(url, True)
                    return text
            except Exception as exc:
                last_error = exc
                _record_source(url, False)
                if attempt + 1 < attempts:
                    time.sleep(0.8)

    raise RuntimeError(f"无法读取下载信息：{last_error}")


def _download_urls(urls, target, sha1="", progress_callback=None):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and target.stat().st_size > 0:
        if not sha1:
            return str(target)

        digest = hashlib.sha1(target.read_bytes()).hexdigest()
        if digest.lower() == sha1.lower():
            return str(target)

    last_error = None
    candidates = _rank_urls(urls)

    # 单一来源失败时再试一次，多来源则直接切换更快
    if len(candidates) == 1:
        candidates = candidates * 2

    for index, url in enumerate(candidates):
        if _DOWNLOAD_CANCEL.is_set():
            raise DownloadCancelled("已取消")

        part = target.with_suffix(
            f"{target.suffix}.{index}.part"
        )

        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "MinecraftLauncher/1.0"},
            )
            digest = hashlib.sha1()

            with urllib.request.urlopen(
                request,
                timeout=12,
                context=_network_context(),
            ) as response, open(part, "wb") as output:
                total_size = int(
                    response.headers.get("Content-Length") or 0
                )
                downloaded = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if _DOWNLOAD_CANCEL.is_set():
                        raise DownloadCancelled("已取消")
                    if progress_callback:
                        progress_callback(downloaded, total_size)

            if sha1 and digest.hexdigest().lower() != sha1.lower():
                raise RuntimeError("下载文件校验失败")

            os.replace(part, target)
            _record_source(url, True)
            return str(target)
        except DownloadCancelled:
            try:
                part.unlink(missing_ok=True)
            except Exception:
                pass
            raise
        except Exception as exc:
            last_error = exc
            _record_source(url, False)
            try:
                part.unlink(missing_ok=True)
            except Exception:
                pass

    raise RuntimeError(f"下载失败：{target.name}（{last_error}）")


def download(url, dest, expected_sha1=""):
    return _download_urls(
        (url,),
        dest,
        expected_sha1,
    )


def download_with_fallback(urls, dest, expected_sha1=""):
    return _download_urls(
        urls,
        dest,
        expected_sha1,
    )


def _download_file(url, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        context = None

        if certifi is not None:
            context = ssl.create_default_context(cafile=certifi.where())

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "MinecraftLauncher/1.0"},
        )

        with urllib.request.urlopen(
            request,
            timeout=30,
            context=context,
        ) as response, open(target, "wb") as output:
            shutil.copyfileobj(response, output)

        return str(target)
    except Exception:
        return ""


def _avatar_data_uri(path):
    try:
        path = Path(path)
        suffix = path.suffix.lower()
        mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except Exception:
        return ""


def _image_data_uri(path):
    mime_by_suffix = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }

    try:
        path = Path(path)
        mime = mime_by_suffix.get(path.suffix.lower(), "image/png")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except Exception:
        return ""


class LaunchState:
    def __init__(self):
        self._lock = threading.Lock()
        self.progress = 0
        self.message = ""
        self.error = ""
        self.process = None
        self.state = "idle"
        self._log_lines = deque(maxlen=500)
        self._log_revision = 0

    def update(self, progress, message, error=""):
        with self._lock:
            self.progress = progress
            self.message = message
            self.error = error

    def set_state(self, state):
        with self._lock:
            self.state = state

    def reset_log(self):
        with self._lock:
            self._log_lines.clear()
            self._log_revision += 1

    def append_log(self, line):
        with self._lock:
            self._log_lines.append(str(line).rstrip())
            self._log_revision += 1

    def set_process(self, process):
        with self._lock:
            self.process = process

    def get_log(self):
        with self._lock:
            return {
                "revision": self._log_revision,
                "lines": list(self._log_lines),
            }

    def snapshot(self):
        with self._lock:
            running = self.process is not None and self.process.poll() is None
            return {
                "progress": self.progress,
                "message": self.message,
                "error": self.error,
                "running": running,
                "state": self.state,
                "log_revision": self._log_revision,
            }


class DownloadState:
    def __init__(self):
        self._lock = threading.Lock()
        self.progress = 0
        self.message = ""
        self.error = ""
        self.running = False
        self.cancelled = False
        self.result = None
        self.completed = 0
        self.total = 0

    def begin(self, message):
        _DOWNLOAD_CANCEL.clear()
        with self._lock:
            self.progress = 1
            self.message = message
            self.error = ""
            self.running = True
            self.cancelled = False
            self.result = None
            self.completed = 0
            self.total = 0

    def set_total(self, total):
        with self._lock:
            self.total = max(int(total), 1)
            self.completed = 0
            self.progress = max(self.progress, 3)

    def advance(self, message="", amount=1):
        with self._lock:
            self.completed += amount
            if self.total:
                ratio = min(self.completed / self.total, 1)
                next_progress = min(
                    96,
                    max(4, round(ratio * 90) + 6),
                )
                self.progress = max(self.progress, next_progress)
            if message:
                self.message = message

    def update(self, progress, message):
        with self._lock:
            self.progress = max(0, min(100, int(progress)))
            self.message = message

    def finish(self, result, message):
        with self._lock:
            self.progress = 100
            self.message = message
            self.error = ""
            self.running = False
            self.cancelled = False
            self.result = result

    def fail(self, error):
        with self._lock:
            self.progress = 0
            self.message = "下载失败"
            self.error = str(error)
            self.running = False
            self.cancelled = False
            self.result = None

    def cancel(self):
        _DOWNLOAD_CANCEL.set()

        with self._lock:
            if not self.running:
                return
            self.progress = 0
            self.message = "已取消"
            self.error = ""
            self.running = False
            self.cancelled = True
            self.result = None

    def snapshot(self):
        with self._lock:
            return {
                "progress": self.progress,
                "message": self.message,
                "error": self.error,
                "running": self.running,
                "cancelled": self.cancelled,
                "result": self.result,
                "completed": self.completed,
                "total": self.total,
            }


class PremiumLoginState:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = "idle"
        self.message = ""
        self.error = ""
        self.account = None

    def snapshot(self):
        with self.lock:
            return {
                "state": self.state,
                "message": self.message,
                "error": self.error,
                "account": self.account,
            }


class Api:
    def __init__(self, config_path=None):
        if config_path is None:
            base = Path(os.environ.get("APPDATA") or Path.home())
            config_path = base / "MinecraftLauncher" / "config.json"

        self.config_path = Path(config_path)
        self.auth_path = (
            self.config_path.parent / "accounts" / "auth.json"
        )
        self.imported_info = None
        self.launch_state = LaunchState()
        self.download_state = DownloadState()
        self.premium_login_state = PremiumLoginState()
        self._config_cache = None
        self._avatar_uri_cache = {}
        self._wallpaper_uri_cache = {}
        self._account_payload_cache = None
        self._version_cache = {}
        self._manifest_cache = None
        self._manifest_cache_time = 0
        self._translation_cache = {}
        self._translation_misses = set()
        self._translation_path = (
            self.config_path.parent / "translations.json"
        )
        self._translation_loaded = False
        self._content_search_cache = {}
        self._loader_cache = {}
        self._java_version_cache = {}
        self._java_choice_cache = {}
        self._java_candidates_cache = None
        self._java_candidates_cache_time = 0

    def _read_config(self):
        if self._config_cache is not None:
            return self._config_cache

        try:
            self._config_cache = json.loads(
                self.config_path.read_text(encoding="utf-8")
            )
            return self._config_cache
        except Exception:
            self._config_cache = {}
            return self._config_cache

    def _write_config(self, data):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._config_cache = data

    def _normalize_folder_entry(self, folder):
        folder = dict(folder)
        folder["selected_version_id"] = (
            folder.get("selected_version_id")
            or folder.get("version_id")
            or ""
        )

        names = folder.get("version_names")
        names = dict(names) if isinstance(names, dict) else {}
        version_id = folder.get("version_id")

        if version_id and not names.get(version_id):
            names[version_id] = (
                folder.get("display_name")
                or version_id
            )

        folder["version_names"] = names
        folder["display_name"] = (
            names.get(folder["selected_version_id"])
            or names.get(version_id or "")
            or folder.get("display_name")
            or folder.get("version_id")
            or ""
        )
        return folder

    def _get_imported_folders(self, data):
        folders = data.get("imported_folders")

        if isinstance(folders, list):
            return [self._normalize_folder_entry(folder) for folder in folders]

        legacy = data.get("imported")

        if isinstance(legacy, dict):
            legacy = dict(legacy)
            legacy.setdefault(
                "source_folder",
                legacy.get("game_root") or legacy.get("version_folder") or "",
            )
            return [self._normalize_folder_entry(legacy)]

        return []

    def _migrate_imported_list(self, data):
        changed = False
        raw_folders = data.get("imported_folders")
        folders = self._get_imported_folders(data)

        if raw_folders != folders:
            data["imported_folders"] = folders
            changed = True

        if not data.get("selected_folder") and folders:
            data["selected_folder"] = folders[0].get("source_folder", "")
            changed = True

        if changed:
            self._write_config(data)

        return data

    def _find_imported_entry(self, data, source_folder):
        target = os.path.normcase(str(Path(source_folder).resolve()))

        for folder in self._get_imported_folders(data):
            source = folder.get("source_folder", "")
            if source and os.path.normcase(str(source)) == target:
                return folder

        return None

    def _upsert_imported(self, info):
        info = self._normalize_folder_entry(info)
        data = self._read_config()
        data = self._migrate_imported_list(data)
        folders = data.get("imported_folders", [])
        target = os.path.normcase(str(info["source_folder"]))
        replaced = False

        for index, folder in enumerate(folders):
            source = folder.get("source_folder", "")
            if source and os.path.normcase(str(source)) == target:
                folders[index] = info
                replaced = True
                break

        if not replaced:
            folders.append(info)

        data["imported_folders"] = folders
        data["selected_folder"] = info["source_folder"]
        data["version"] = info.get("display_name") or info.get("version_id")
        self._write_config(data)

    def load_version(self):
        data = self._migrate_imported_list(self._read_config())
        folders = data.get("imported_folders", [])
        selected = data.get("selected_folder")

        for folder in folders:
            if folder.get("source_folder") == selected:
                version_id = (
                    folder.get("selected_version_id")
                    or folder.get("version_id")
                )
                names = folder.get("version_names", {})
                value = (
                    names.get(version_id or "")
                    or folder.get("display_name")
                    or folder.get("version_id")
                )
                if value:
                    return value

        value = data.get("version")

        if isinstance(value, str) and value.strip():
            return value.strip()

        default_version = self._get_settings().get("default_version")
        if default_version:
            return str(default_version)

        return None

    def save_version(self, value):
        data = self._read_config()
        data = self._migrate_imported_list(data)
        value = str(value)
        selected = data.get("selected_folder")

        for folder in data.get("imported_folders", []):
            if folder.get("source_folder") == selected:
                version_id = (
                    folder.get("selected_version_id")
                    or folder.get("version_id")
                )
                names = folder.get("version_names", {})
                if version_id:
                    names[version_id] = value
                    folder["version_names"] = names
                folder["display_name"] = value

        data["version"] = value
        self._write_config(data)
        return True

    def _settings_defaults(self):
        return {
            "java_path": "",
            "memory_mb": 4096,
            "default_version": "",
            "minimize_on_launch": False,
            "auto_select_last_folder": True,
            "dark_mode": False,
            "wallpaper_path": "",
        }

    def _get_settings(self):
        defaults = self._settings_defaults()
        saved = self._read_config().get("settings")

        if isinstance(saved, dict):
            defaults.update(saved)

        defaults["memory_mb"] = max(
            512,
            min(16384, int(defaults.get("memory_mb") or 4096)),
        )
        return defaults

    def _wallpaper_uri(self, wallpaper_path):
        path = Path(wallpaper_path)

        try:
            stat = path.stat()
            key = (
                str(path),
                stat.st_mtime_ns,
                stat.st_size,
            )
        except Exception:
            key = str(path)

        cached = self._wallpaper_uri_cache.get(key)
        if cached is not None:
            return cached

        uri = _image_data_uri(path)
        self._wallpaper_uri_cache[key] = uri
        return uri

    def get_settings(self):
        settings = self._get_settings()
        wallpaper_path = settings.get("wallpaper_path") or ""
        wallpaper_uri = ""
        wallpaper_name = ""

        if wallpaper_path and Path(wallpaper_path).exists():
            wallpaper_uri = self._wallpaper_uri(wallpaper_path)
            wallpaper_name = Path(wallpaper_path).name

        settings.update(
            {
                "wallpaper_uri": wallpaper_uri,
                "wallpaper_name": wallpaper_name,
            }
        )
        return {**settings, "ok": True}

    def save_settings(self, settings):
        if not isinstance(settings, dict):
            return {"ok": False, "message": "设置数据无效"}

        saved = {
            "java_path": str(settings.get("java_path") or "").strip(),
            "memory_mb": max(
                512,
                min(16384, int(settings.get("memory_mb") or 4096)),
            ),
            "default_version": str(
                settings.get("default_version") or ""
            ).strip(),
            "minimize_on_launch": bool(
                settings.get("minimize_on_launch")
            ),
            "auto_select_last_folder": bool(
                settings.get("auto_select_last_folder", True)
            ),
            "dark_mode": bool(settings.get("dark_mode")),
            "wallpaper_path": str(
                settings.get("wallpaper_path") or ""
            ).strip(),
        }
        data = self._read_config()
        data["settings"] = saved
        self._write_config(data)
        self._wallpaper_uri_cache.clear()
        self._java_choice_cache.clear()
        self._java_candidates_cache = None
        return {**saved, "ok": True, "message": "设置已保存"}

    def browse_java(self):
        try:
            selected = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN,
                file_types=("Java 可执行文件 (*.exe)",),
            )
        except Exception as exc:
            return {"ok": False, "message": f"无法打开文件选择器：{exc}"}

        if not selected:
            return {"ok": False, "message": "未选择 Java"}

        return {
            "ok": True,
            "java_path": str(Path(selected[0]).resolve()),
        }

    def browse_wallpaper(self):
        try:
            selected = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN,
                file_types=(
                    "图片文件 (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp)",
                ),
            )
        except Exception as exc:
            return {"ok": False, "message": f"无法打开图片选择器：{exc}"}

        if not selected:
            return {"ok": False, "message": "未选择图片"}

        source = Path(selected[0])
        suffix = source.suffix.lower() or ".png"
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

        if suffix not in allowed:
            return {"ok": False, "message": "不支持的图片格式"}

        target = self.config_path.parent / f"wallpaper{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        self._wallpaper_uri_cache.clear()

        return {
            "ok": True,
            "wallpaper_path": str(target),
            "wallpaper_name": source.name,
            "wallpaper_uri": self._wallpaper_uri(target),
        }

    def _read_saved_account(self):
        account = None

        try:
            account = json.loads(
                self.auth_path.read_text(encoding="utf-8")
            )
        except Exception:
            account = None

        if not isinstance(account, dict):
            data = self._read_config()
            legacy = data.get("account")
            if isinstance(legacy, dict) and legacy.get("display_name"):
                account = {
                    "access_token": legacy.get("access_token", ""),
                    "refresh_token": legacy.get("refresh_token", ""),
                    "expires_at": legacy.get("expires_at", 0),
                    "username": legacy.get("display_name", ""),
                    "uuid": legacy.get("uuid", ""),
                }
                self._save_account(
                    account,
                    legacy_avatar=legacy.get("avatar_path", ""),
                )
                data.pop("account", None)
                self._write_config(data)

        if not isinstance(account, dict) or not account.get("username"):
            return None

        profile = self._read_config().get("account_profile") or {}
        return {
            **account,
            "display_name": account.get("username") or "Player",
            "avatar_path": profile.get("avatar_path", ""),
        }

    def _secure_auth_file(self):
        try:
            os.chmod(self.auth_path, 0o600)
        except Exception:
            pass

        if os.name == "nt":
            try:
                user = getpass.getuser()
                subprocess.run(
                    [
                        "icacls",
                        str(self.auth_path),
                        "/inheritance:r",
                        "/grant:r",
                        f"{user}:F",
                    ],
                    capture_output=True,
                    timeout=15,
                    **_hidden_process_kwargs(),
                )
            except Exception:
                pass

    def _save_account(self, account, legacy_avatar=""):
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)
        auth_data = {
            "access_token": account.get("access_token", ""),
            "refresh_token": account.get("refresh_token", ""),
            "expires_at": account.get("expires_at", 0),
            "username": (
                account.get("username")
                or account.get("display_name")
                or ""
            ),
            "uuid": account.get("uuid", ""),
        }
        self.auth_path.write_text(
            json.dumps(auth_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._secure_auth_file()

        data = self._read_config()
        data["account_profile"] = {
            "avatar_path": (
                account.get("avatar_path")
                or legacy_avatar
                or ""
            )
        }
        data.pop("account", None)
        self._write_config(data)
        self._account_payload_cache = None
        self._avatar_uri_cache.clear()

    def _avatar_uri(self, avatar_path):
        path = Path(avatar_path)

        try:
            stat = path.stat()
            key = (
                str(path),
                stat.st_mtime_ns,
                stat.st_size,
            )
        except Exception:
            key = str(path)

        cached = self._avatar_uri_cache.get(key)
        if cached is not None:
            return cached

        uri = _avatar_data_uri(path)
        if not uri:
            uri = path.as_uri()
        self._avatar_uri_cache[key] = uri
        return uri

    def _account_payload(self, account):
        if not account:
            return {"ok": True, "signed_in": False}

        if self._account_payload_cache is not None:
            return self._account_payload_cache

        avatar_path = account.get("avatar_path") or ""
        avatar_uri = ""

        if avatar_path and Path(avatar_path).exists():
            avatar_uri = self._avatar_uri(avatar_path)

        payload = {
            "ok": True,
            "signed_in": True,
            "display_name": account.get("display_name") or "Player",
            "uuid": account.get("uuid") or "",
            "avatar_path": avatar_uri,
        }
        self._account_payload_cache = payload
        return payload

    def get_account_info(self):
        return self._account_payload(self._read_saved_account())

    def logout_account(self):
        data = self._read_config()
        account = data.pop("account", None)
        profile = data.pop("account_profile", None)
        self._write_config(data)
        self._account_payload_cache = None
        self._avatar_uri_cache.clear()
        try:
            self.auth_path.unlink(missing_ok=True)
        except Exception:
            pass

        avatar_path = ""
        if isinstance(profile, dict):
            avatar_path = profile.get("avatar_path") or ""
        elif isinstance(account, dict):
            avatar_path = account.get("avatar_path") or ""

        if avatar_path:
            try:
                path = Path(avatar_path).resolve()
                if path.parent == self.config_path.parent.resolve():
                    path.unlink(missing_ok=True)
            except Exception:
                pass

        self._set_premium_state("idle", "已退出正版账号")
        return {
            "ok": True,
            "signed_in": False,
            "message": "已退出正版账号",
        }

    def _friendly_auth_error(self, exc):
        text = str(exc)
        code = getattr(exc, "code", "")

        if code == "expired_token":
            return "验证码已过期，请重新发起正版验证"
        if code == "authorization_declined":
            return "你已取消微软授权"
        if code == "slow_down":
            return "微软要求降低轮询频率，请稍候"
        if code == "authorization_pending":
            return "等待微软授权"

        if "AADSTS700016" in text or "AADSTS7000218" in text:
            return (
                "正版验证失败：Azure 应用未开放个人微软账户登录。"
                "请在应用注册中把“支持的账户类型”改为个人 Microsoft 账户，"
                "并在身份验证中开启允许公共客户端流后重试"
            )

        if "HTTP 403" in text or "Invalid app registration" in text:
            return (
                "正版验证失败：微软拒绝了 Minecraft 接口访问（HTTP 403）。"
                "这通常是新建 Azure 应用未获得 Minecraft Java API 权限导致的。"
                "本版本已改用 Minecraft 官方客户端 ID，请重新进行正版验证；"
                "若仍出现 403，请检查微软账号是否已购买 Minecraft Java 版。"
            )

        xerr_codes = {
            "2148916227": "该 Xbox 账号已被封禁，无法进行正版验证",
            "2148916233": "该微软账号还没有 Xbox 档案，请先创建 Xbox 档案后重试",
            "2148916235": "当前地区不支持 Xbox Live，无法进行正版验证",
            "2148916236": "该账号需要完成 Xbox 成人验证后才能正版验证",
            "2148916237": "该账号需要完成 Xbox 成人验证后才能正版验证",
            "2148916238": "该账号是未成年账号，需要加入 Xbox 家庭组后才能正版验证",
        }

        for code, message in xerr_codes.items():
            if f'"{code}"' in text:
                return f"正版验证失败：{message}。请处理 Xbox 账号状态后重试"

        return text

    def _set_premium_state(self, state, message="", error="", account=None):
        with self.premium_login_state.lock:
            self.premium_login_state.state = state
            self.premium_login_state.message = message
            self.premium_login_state.error = error
            self.premium_login_state.account = account

    def start_premium_login(self):
        current = self.premium_login_state.snapshot()

        if current["state"] == "pending":
            return {**current, "ok": True}

        self._set_premium_state("pending", "正在请求微软授权")

        try:
            device = _post_form(
                DEVICE_CODE_URL,
                {
                    "client_id": MICROSOFT_CLIENT_ID,
                    "scope": MICROSOFT_SCOPE,
                    "response_type": "device_code",
                },
            )
        except Exception as exc:
            self._set_premium_state(
                "error",
                "",
                self._friendly_auth_error(exc),
            )
            return {**self.premium_login_state.snapshot(), "ok": False}

        verification_uri = device.get("verification_uri") or (
            "https://microsoft.com/link"
        )

        try:
            webbrowser.open(verification_uri)
        except Exception:
            pass

        message = device.get("message") or (
            f"请在浏览器打开的页面中输入代码 {device.get('user_code', '')}"
        )
        self._set_premium_state("pending", message)

        thread = threading.Thread(
            target=self._premium_login_worker,
            args=(device,),
            daemon=True,
        )
        thread.start()

        return {**self.premium_login_state.snapshot(), "ok": True}

    def get_premium_login_status(self):
        status = self.premium_login_state.snapshot()
        account = status.get("account")

        return {
            **status,
            "account": self._account_payload(account) if account else {},
        }

    def _premium_login_worker(self, device):
        try:
            expires_at = (
                time.time()
                + max(int(device.get("expires_in") or 900), 60)
            )
            interval = max(int(device.get("interval") or 5), 5)
            token = None

            while time.time() < expires_at:
                time.sleep(interval)

                try:
                    token = _post_form(
                        MICROSOFT_TOKEN_URL,
                        {
                            "grant_type": "device_code",
                            "client_id": MICROSOFT_CLIENT_ID,
                            "device_code": device.get("device_code", ""),
                        },
                    )
                    break
                except MicrosoftAuthError as exc:
                    if exc.code == "authorization_pending":
                        continue
                    if exc.code == "slow_down":
                        interval += 5
                        continue
                    raise

            if not token:
                raise RuntimeError("授权已超时，请重新进行正版验证")

            self._complete_microsoft_login(token)
        except Exception as exc:
            self._set_premium_state(
                "error",
                "",
                self._friendly_auth_error(exc),
            )

    def _microsoft_token_to_minecraft(self, microsoft_token):
        xbl = _post_json(
            XBL_AUTH_URL,
            {
                "Properties": {
                    "AuthMethod": "RPS",
                    "SiteName": "user.auth.xboxlive.com",
                    "RpsTicket": f"t={microsoft_token}",
                },
                "RelyingParty": "http://auth.xboxlive.com",
                "TokenType": "JWT",
            },
            headers={"x-xbl-contract-version": "1"},
        )
        xbl_token = xbl["Token"]
        user_hash = xbl["DisplayClaims"]["xui"][0]["uhs"]

        xsts = _post_json(
            XSTS_AUTH_URL,
            {
                "Properties": {
                    "SandboxId": "RETAIL",
                    "UserTokens": [xbl_token],
                },
                "RelyingParty": "rp://api.minecraftservices.com/",
                "TokenType": "JWT",
            },
            headers={"x-xbl-contract-version": "1"},
        )
        xsts_token = xsts["Token"]

        minecraft = _post_json(
            MINECRAFT_LOGIN_URL,
            {
                "identityToken": (
                    f"XBL3.0 x={user_hash};{xsts_token}"
                )
            },
        )

        return (
            minecraft.get("access_token", ""),
            int(minecraft.get("expires_in") or 86400),
        )

    def _complete_microsoft_login(self, token):
        microsoft_token = token.get("access_token", "")

        if not microsoft_token:
            raise RuntimeError("微软未返回访问令牌，请重新验证")

        minecraft_token, expires_in = (
            self._microsoft_token_to_minecraft(microsoft_token)
        )
        auth_headers = {"Authorization": f"Bearer {minecraft_token}"}
        entitlements = _get_json(
            MINECRAFT_ENTITLEMENTS_URL,
            headers=auth_headers,
        )
        owned_items = {
            item.get("name", "")
            for item in entitlements.get("items", [])
        }

        if not (
            "product_minecraft" in owned_items
            or "game_minecraft" in owned_items
        ):
            raise RuntimeError(
                "该微软账号未购买 Minecraft Java 版，无法以正版状态登录"
            )

        profile = _get_json(
            MINECRAFT_PROFILE_URL,
            headers=auth_headers,
        )

        if not profile.get("id") or not profile.get("name"):
            raise RuntimeError("未读取到正版玩家资料，请确认账号已设置 Minecraft 名称")

        skins = profile.get("skins") or []
        skin_url = skins[0].get("url") if skins else ""
        avatar_path = ""

        if skin_url:
            avatar_path = _download_file(
                skin_url,
                self.config_path.parent / "avatar.png",
            )

        account = {
            "display_name": profile["name"],
            "uuid": profile["id"],
            "access_token": minecraft_token,
            "refresh_token": token.get("refresh_token", ""),
            "expires_at": time.time() + expires_in,
            "avatar_path": avatar_path,
        }
        self._save_account(account)
        self._set_premium_state(
            "success",
            "正版验证成功",
            account=account,
        )

    def _refresh_premium_account(self):
        account = self._read_saved_account()

        if not account:
            return None

        if (
            account.get("access_token")
            and account.get("expires_at", 0) > time.time() + 300
        ):
            return account

        refresh_token = account.get("refresh_token")

        if not refresh_token:
            raise RuntimeError("正版登录状态已失效，请重新验证")

        token = _post_form(
            MICROSOFT_TOKEN_URL,
            {
                "client_id": MICROSOFT_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": MICROSOFT_SCOPE,
            },
        )
        minecraft_token, expires_in = (
            self._microsoft_token_to_minecraft(
                token.get("access_token", "")
            )
        )
        account["access_token"] = minecraft_token
        account["expires_at"] = time.time() + expires_in

        if token.get("refresh_token"):
            account["refresh_token"] = token["refresh_token"]

        self._save_account(account)
        return account

    def _load_imported_info(self):
        if not self._get_settings().get("auto_select_last_folder", True):
            return self.imported_info

        data = self._migrate_imported_list(self._read_config())
        folders = data.get("imported_folders", [])
        selected = data.get("selected_folder")

        for folder in folders:
            if folder.get("source_folder") == selected:
                return folder

        if folders:
            return folders[0]

        legacy = data.get("imported")
        return legacy if isinstance(legacy, dict) else None

    def get_imported_folders(self):
        data = self._migrate_imported_list(self._read_config())
        folders = data.get("imported_folders", [])
        selected = data.get("selected_folder") or ""

        return {
            "ok": True,
            "selected_folder": selected,
            "folders": [
                {
                    "source_folder": folder.get("source_folder", ""),
                    "folder_name": Path(
                        folder.get("source_folder", "")
                    ).name
                    or folder.get("display_name", "")
                    or folder.get("version_id", ""),
                    "version_id": folder.get("version_id", ""),
                    "selected_version_id": folder.get(
                        "selected_version_id"
                    )
                    or folder.get("version_id", ""),
                    "display_name": folder.get("display_name")
                    or folder.get("version_id", ""),
                }
                for folder in folders
            ],
        }

    def _discover_versions(self, selected):
        selected = Path(selected).resolve()
        cache_key = str(selected)
        cached = self._version_cache.get(cache_key)

        if cached and time.time() - cached[0] < 1:
            return cached[1]

        candidates = []

        def add_candidate(folder):
            folder = Path(folder)
            if not folder.is_dir():
                return

            for json_path in folder.glob("*.json"):
                jar_path = folder / f"{json_path.stem}.jar"
                if jar_path.exists():
                    try:
                        data = json.loads(
                            json_path.read_text(encoding="utf-8")
                        )
                    except Exception:
                        data = {}
                    candidates.append((folder, json_path, jar_path, data))

        add_candidate(selected)

        version_root = selected / "versions"
        if selected.name == "versions":
            version_root = selected

        if version_root.is_dir():
            for child in version_root.iterdir():
                add_candidate(child)

        candidates.sort(key=lambda candidate: candidate[0].name.lower())
        self._version_cache[cache_key] = (time.time(), candidates)
        return candidates

    def _discover_version_folder(self, selected, preferred_version=None):
        candidates = self._discover_versions(selected)

        if not candidates:
            return None

        for folder, json_path, jar_path, data in candidates:
            if preferred_version and data.get("id") == preferred_version:
                return folder, json_path, jar_path, data

        return max(
            candidates,
            key=lambda candidate: candidate[1].stat().st_mtime_ns,
        )

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

    def _build_import_info(
        self,
        selected,
        version_id=None,
        preferred_version=None,
    ):
        selected = Path(selected).resolve()
        found = None

        if version_id is not None:
            for (
                version_folder,
                version_json_path,
                version_jar_path,
                version_data,
            ) in self._discover_versions(selected):
                candidate_id = (
                    version_data.get("id")
                    or version_json_path.stem
                )
                if candidate_id == version_id:
                    found = (
                        version_folder,
                        version_json_path,
                        version_jar_path,
                        version_data,
                    )
                    break
        else:
            found = self._discover_version_folder(
                selected,
                preferred_version,
            )

        if not found:
            return None

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

        return {
            "source_folder": str(selected),
            "version_id": version_id,
            "game_version": self._minecraft_version(
                version_data,
                version_id,
            ),
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
            "display_name": version_id,
        }

    def _prepare_folder_entry(
        self,
        info,
        existing,
        selected_version_id=None,
    ):
        names = dict(existing.get("version_names", {})) if existing else {}
        version_id = info["version_id"]

        if not names.get(version_id):
            names[version_id] = (
                existing.get("display_name")
                if existing
                and existing.get("version_id") == version_id
                and existing.get("display_name")
                else version_id
            )

        if selected_version_id is None:
            selected_version_id = version_id
            if (
                existing
                and existing.get("selected_version_id") == version_id
            ):
                selected_version_id = existing["selected_version_id"]

        info["version_names"] = names
        info["selected_version_id"] = selected_version_id
        info["display_name"] = (
            names.get(selected_version_id)
            or names.get(version_id)
            or version_id
        )
        return info

    def import_path(self, selected):
        selected = Path(selected).resolve()
        data = self._read_config()
        existing = self._find_imported_entry(data, selected)
        preferred_version = (
            existing.get("selected_version_id")
            or existing.get("version_id")
            if existing
            else None
        )
        info = self._build_import_info(
            selected,
            preferred_version=preferred_version,
        )

        if not info:
            return {
                "ok": False,
                "message": "未找到游戏版本配置，请选择包含 versions 或版本 json+jar 的文件夹",
            }

        info = self._prepare_folder_entry(info, existing)

        self._upsert_imported(info)
        self.imported_info = info
        return {
            **info,
            "ok": True,
            "message": f"已导入 {info['display_name']}",
        }

    def select_folder(self, source_folder):
        selected = Path(source_folder).resolve()
        data = self._read_config()
        existing = self._find_imported_entry(data, selected)
        preferred_version = (
            existing.get("selected_version_id")
            or existing.get("version_id")
            if existing
            else None
        )
        info = self._build_import_info(
            selected,
            preferred_version=preferred_version,
        )

        if not info:
            return {
                "ok": False,
                "message": "未找到游戏版本配置，请选择包含 versions 或版本 json+jar 的文件夹",
            }

        info = self._prepare_folder_entry(info, existing)

        self._upsert_imported(info)
        self.imported_info = info
        return {
            **info,
            "ok": True,
            "message": f"已切换到 {info['display_name']}",
        }

    def get_versions(self, source_folder):
        selected = Path(source_folder).resolve()
        data = self._migrate_imported_list(self._read_config())
        existing = self._find_imported_entry(data, selected)
        names = dict(existing.get("version_names", {})) if existing else {}
        selected_version_id = (
            existing.get("selected_version_id")
            or existing.get("version_id")
            if existing
            else ""
        )

        versions = []
        selected_game_version = ""

        for (
            version_folder,
            version_json_path,
            _version_jar_path,
            version_data,
        ) in self._discover_versions(selected):
            version_id = (
                version_data.get("id")
                or version_json_path.stem
            )
            game_version = self._minecraft_version(
                version_data,
                version_id,
            )
            if version_id == selected_version_id:
                selected_game_version = game_version
            versions.append(
                {
                    "version_id": version_id,
                    "game_version": game_version,
                    "version_folder": str(version_folder),
                    "display_name": names.get(version_id, version_id),
                }
            )

        if not selected_game_version and versions:
            selected_game_version = versions[0]["game_version"]

        return {
            "ok": True,
            "selected_version_id": selected_version_id or "",
            "game_version": selected_game_version,
            "versions": versions,
        }

    def select_version(self, source_folder, version_id):
        selected = Path(source_folder).resolve()
        data = self._read_config()
        existing = self._find_imported_entry(data, selected)

        if not existing:
            return {"ok": False, "message": "请先导入该文件夹"}

        info = self._build_import_info(
            selected,
            version_id=version_id,
        )

        if not info:
            return {
                "ok": False,
                "message": "未找到该游戏版本，请确认版本 json 和 jar 仍然存在",
            }

        info = self._prepare_folder_entry(
            info,
            existing,
            selected_version_id=version_id,
        )
        self._upsert_imported(info)
        self.imported_info = info
        return {
            **info,
            "ok": True,
            "message": f"已切换到 {info['display_name']}",
        }

    def _version_manifest(self):
        now = time.time()

        if (
            self._manifest_cache
            and now - self._manifest_cache_time < 600
        ):
            return self._manifest_cache

        cache_path = (
            self.config_path.parent
            / "cache"
            / "version_manifest.json"
        )

        try:
            manifest = _fetch_json_urls(
                VERSION_MANIFEST_URLS,
                timeout=8,
                attempts=1,
            )
        except Exception:
            manifest = self._read_version_manifest_cache(cache_path)
            if not manifest:
                raise
            self._manifest_cache = manifest
            self._manifest_cache_time = now
            return manifest

        self._manifest_cache = manifest
        self._manifest_cache_time = now
        self._write_version_manifest_cache(cache_path, manifest)
        return manifest

    @staticmethod
    def _read_version_manifest_cache(path):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return None

        if not isinstance(data, dict):
            return None

        if time.time() - float(data.get("saved_at") or 0) > 2592000:
            return None

        manifest = data.get("manifest")
        return manifest if isinstance(manifest, dict) else None

    @staticmethod
    def _write_version_manifest_cache(path, manifest):
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(
                    {
                        "saved_at": time.time(),
                        "manifest": manifest,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            os.replace(temp, path)
        except Exception:
            pass

    def get_minecraft_versions(self):
        manifest = self._version_manifest()
        categories = (
            ("release", "正式版"),
            ("snapshot", "快照版"),
            ("old_beta", "旧版 Beta"),
            ("old_alpha", "旧版 Alpha"),
        )
        groups = []

        for version_type, label in categories:
            versions = [
                {
                    "id": item.get("id", ""),
                    "type": item.get("type", ""),
                    "release_time": item.get("releaseTime", ""),
                }
                for item in manifest.get("versions", [])
                if item.get("type") == version_type and item.get("id")
            ]
            versions.sort(
                key=lambda item: item["release_time"],
                reverse=True,
            )
            groups.append(
                {
                    "id": version_type,
                    "label": label,
                    "versions": versions,
                }
            )

        return {
            "ok": True,
            "source": "BMCLAPI",
            "groups": groups,
        }

    def _fabric_loaders(self, version_id):
        official_url = (
            "https://meta.fabricmc.net/v2/versions/loader/"
            f"{urllib.parse.quote(version_id)}"
        )
        mirror_url = (
            f"{BMCLAPI_BASE}/fabric-meta/v2/versions/loader/"
            f"{urllib.parse.quote(version_id)}"
        )
        loaders = _fetch_json_urls(
            (mirror_url, official_url),
            timeout=8,
            attempts=1,
        )
        result = []

        for item in loaders:
            loader = item.get("loader") or {}
            version = loader.get("version")
            if not version or not loader.get("stable", True):
                continue
            result.append(
                {
                    "id": f"fabric:{version}",
                    "name": "Fabric",
                    "version": version,
                    "description": "主流模组加载器，适合大多数整合包",
                }
            )
            if len(result) >= 8:
                break

        return result

    def _maven_versions(
        self,
        mirror_url,
        official_url,
        attempts=1,
    ):
        for url in (mirror_url, official_url):
            for _attempt in range(max(1, attempts)):
                try:
                    text = _fetch_text_urls(
                        (url,),
                        timeout=6,
                        attempts=1,
                    )
                    versions = re.findall(
                        r"<version>([^<]+)</version>",
                        text,
                        flags=re.IGNORECASE,
                    )
                    if versions:
                        return versions
                except Exception:
                    continue

        return []

    @staticmethod
    def _version_sort_key(value):
        parts = re.split(r"[.\-+]", str(value))
        return tuple(
            (0, int(part))
            if part.isdigit()
            else (1, part.lower())
            for part in parts
        )

    def _forge_loaders(self, version_id):
        matching = []

        try:
            builds = _fetch_json_urls(
                (
                    f"{BMCLAPI_BASE}/forge/minecraft/"
                    f"{urllib.parse.quote(version_id)}",
                ),
                timeout=6,
                attempts=1,
            )
            matching = [
                f"{version_id}-{item['version']}"
                for item in builds
                if isinstance(item, dict) and item.get("version")
            ]
        except Exception:
            matching = []

        if not matching:
            versions = self._maven_versions(
                (
                    f"{BMCLAPI_BASE}/maven/net/minecraftforge/forge/"
                    "maven-metadata.xml"
                ),
                (
                    "https://maven.minecraftforge.net/net/minecraftforge/"
                    "forge/maven-metadata.xml"
                ),
            )
            matching = [
                version
                for version in versions
                if version.startswith(f"{version_id}-")
            ]

        matching = list(dict.fromkeys(matching))
        matching.sort(
            key=self._version_sort_key,
            reverse=True,
        )
        return [
            {
                "id": f"forge:{version}",
                "name": "Forge",
                "version": version,
                "description": "兼容范围广的传统模组加载器",
            }
            for version in matching[:8]
        ]

    def _neoforge_loaders(self, version_id):
        versions = self._maven_versions(
            (
                f"{BMCLAPI_BASE}/maven/net/neoforged/neoforge/"
                "maven-metadata.xml"
            ),
            (
                "https://maven.neoforged.net/releases/net/neoforged/"
                "neoforge/maven-metadata.xml"
            ),
            attempts=2,
        )
        parts = version_id.split(".")
        prefix = (
            f"{parts[1]}.{parts[2]}"
            if len(parts) >= 3
            else f"{parts[1]}.0"
        )
        matching = [
            version
            for version in versions
            if version.startswith(f"{prefix}.")
        ]
        matching.sort(
            key=self._version_sort_key,
            reverse=True,
        )
        return [
            {
                "id": f"neoforge:{version}",
                "name": "NeoForge",
                "version": version,
                "description": "面向新版本 Minecraft 的现代加载器",
            }
            for version in matching[:8]
        ]

    def get_version_loaders(self, version_id):
        cached = self._loader_cache.get(version_id)

        if cached and time.time() - cached[0] < 86400:
            return cached[1]

        disk = self._read_loader_cache(version_id)

        if disk:
            self._loader_cache[version_id] = (time.time(), disk)
            return disk

        loaders = [
            {
                "id": "vanilla",
                "name": "原版",
                "version": "",
                "description": "Minecraft 官方版本，不加载模组",
            }
        ]
        warnings = []
        executor = ThreadPoolExecutor(max_workers=3)
        futures = {
            executor.submit(self._fabric_loaders, version_id): "Fabric",
            executor.submit(self._forge_loaders, version_id): "Forge",
            executor.submit(self._neoforge_loaders, version_id): "NeoForge",
        }

        try:
            for future in as_completed(futures, timeout=10):
                label = futures[future]
                try:
                    loaders.extend(future.result())
                except Exception as exc:
                    warnings.append(f"{label} 获取失败：{exc}")
        except TimeoutError:
            warnings.append("部分加载器信息超时")
        finally:
            executor.shutdown(wait=False)

        result = {
            "ok": True,
            "version_id": version_id,
            "loaders": loaders,
            "warning": "；".join(warnings),
        }
        self._loader_cache[version_id] = (time.time(), result)

        if len(loaders) > 1:
            self._write_loader_cache(
                version_id,
                result,
                partial=bool(warnings),
            )

        return result

    def _loader_cache_path(self, version_id):
        safe = re.sub(r'[<>:"/\\|?*]+', "_", str(version_id))
        return (
            self.config_path.parent
            / "cache"
            / "loaders"
            / f"{safe}.json"
        )

    def _read_loader_cache(self, version_id):
        try:
            data = json.loads(
                self._loader_cache_path(version_id).read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            return None

        if not isinstance(data, dict):
            return None

        max_age = 600 if data.get("partial") else 86400

        if time.time() - float(data.get("saved_at") or 0) > max_age:
            return None

        result = data.get("result")
        return result if isinstance(result, dict) else None

    def _write_loader_cache(self, version_id, result, partial=False):
        try:
            path = self._loader_cache_path(version_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(
                    {
                        "saved_at": time.time(),
                        "partial": partial,
                        "result": result,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            os.replace(temp, path)
        except Exception:
            pass

    def _download_game_root(self):
        info = self.imported_info or self._load_imported_info()

        if info and info.get("game_root"):
            root = Path(info["game_root"])
            if root.is_dir():
                return root.resolve()

        return (self.config_path.parent / "minecraft").resolve()

    @staticmethod
    def _library_allowed(library):
        rules = library.get("rules")

        if not rules:
            return True

        allowed = False

        for rule in rules:
            os_name = (rule.get("os") or {}).get("name")
            if os_name and os_name != "windows":
                continue
            allowed = rule.get("action") == "allow"

        return allowed

    @staticmethod
    def _library_path(name, classifier=""):
        parts = str(name).split(":")

        if len(parts) < 3:
            return ""

        group, artifact, version = parts[:3]
        file_name = f"{artifact}-{version}"

        if len(parts) > 3 and parts[3]:
            file_name += f"-{parts[3]}"

        if classifier:
            file_name += f"-{classifier}"

        return (
            f"{group.replace('.', '/')}/{artifact}/{version}/"
            f"{file_name}.jar"
        )

    def _library_jobs(self, libraries, libraries_root):
        jobs = []
        native_files = []

        for library in libraries:
            if not self._library_allowed(library):
                continue

            name = library.get("name", "")
            downloads = library.get("downloads") or {}
            artifact = downloads.get("artifact") or {}
            classifiers = downloads.get("classifiers") or {}
            path = artifact.get("path", "")

            if not path and (artifact or not classifiers):
                path = self._library_path(name)

            if path:
                target = libraries_root / path
                jobs.append(
                    {
                        "urls": (
                            f"{DOWNLOAD_ENDPOINTS['libraries'][0]}/{path}",
                            artifact.get("url")
                            or (
                                f"{DOWNLOAD_ENDPOINTS['libraries'][1]}"
                                f"/{path}"
                            ),
                        ),
                        "target": target,
                        "sha1": artifact.get("sha1", ""),
                        "label": f"依赖库 {target.name}",
                    }
                )
                named_classifier = (
                    name.split(":")[3]
                    if len(name.split(":")) > 3
                    else ""
                )
                if named_classifier.startswith("natives-"):
                    native_files.append(
                        {
                            "path": target,
                            "exclude": (
                                library.get("extract") or {}
                            ).get("exclude", []),
                        }
                    )
                    continue

            native_name = (library.get("natives") or {}).get("windows")
            if not native_name:
                continue

            native_artifact = (
                downloads.get("classifiers") or {}
            ).get(native_name) or {}
            native_path = (
                native_artifact.get("path")
                or self._library_path(name, native_name)
            )

            if not native_path:
                continue

            native_target = libraries_root / native_path
            jobs.append(
                {
                    "urls": (
                        (
                            f"{DOWNLOAD_ENDPOINTS['libraries'][0]}"
                            f"/{native_path}"
                        ),
                        native_artifact.get("url")
                        or (
                            f"{DOWNLOAD_ENDPOINTS['libraries'][1]}"
                            f"/{native_path}"
                        ),
                    ),
                    "target": native_target,
                    "sha1": native_artifact.get("sha1", ""),
                    "label": f"运行库 {native_target.name}",
                }
            )
            native_files.append(
                {
                    "path": native_target,
                    "exclude": (library.get("extract") or {}).get(
                        "exclude",
                        [],
                    ),
                }
            )

        return jobs, native_files

    def _asset_jobs(self, asset_index, assets_root):
        jobs = []

        for relative, item in (asset_index.get("objects") or {}).items():
            digest = item.get("hash", "")
            if len(digest) < 2:
                continue
            target = (
                assets_root
                / "objects"
                / digest[:2]
                / digest
            )
            jobs.append(
                {
                    "urls": (
                        f"{DOWNLOAD_ENDPOINTS['assets'][0]}/{digest}",
                        (
                            f"{DOWNLOAD_ENDPOINTS['assets'][1]}/"
                            f"{digest[:2]}/{digest}"
                        ),
                    ),
                    "target": target,
                    "sha1": digest,
                    "label": f"资源文件 {relative}",
                }
            )

        return jobs

    @staticmethod
    def _extract_natives(version_folder, version_id, native_files):
        natives_dir = version_folder / f"{version_id}-natives"
        natives_dir.mkdir(parents=True, exist_ok=True)
        root = natives_dir.resolve()

        for native in native_files:
            archive_path = Path(native["path"])
            if not archive_path.exists():
                continue

            with zipfile.ZipFile(archive_path) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue

                    relative = Path(member.filename)
                    if relative.parts and relative.parts[0] == "META-INF":
                        continue
                    if any(
                        relative.match(pattern)
                        for pattern in native.get("exclude", [])
                    ):
                        continue

                    target = (natives_dir / relative).resolve()
                    if root != target and root not in target.parents:
                        continue

                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source:
                        with open(target, "wb") as output:
                            shutil.copyfileobj(source, output)

        return natives_dir

    def _run_download_jobs(self, jobs, workers=10):
        if not jobs:
            return

        unique_jobs = {}
        for job in jobs:
            unique_jobs.setdefault(str(job["target"]), job)
        jobs = list(unique_jobs.values())
        self.download_state.set_total(len(jobs))
        failures = []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _download_urls,
                    job["urls"],
                    job["target"],
                    job.get("sha1", ""),
                ): job
                for job in jobs
            }

            for future in as_completed(futures):
                job = futures[future]
                try:
                    future.result()
                    self.download_state.advance(job["label"])
                except Exception as exc:
                    failures.append(f"{job['label']}：{exc}")
                    self.download_state.advance(job["label"])

        if failures:
            raise RuntimeError(
                "部分文件下载失败：" + "；".join(failures[:3])
            )

    def _install_version_files(
        self,
        game_root,
        version_id,
        version_json,
        entry,
    ):
        versions_root = game_root / "versions"
        libraries_root = game_root / "libraries"
        assets_root = game_root / "assets"
        version_folder = versions_root / version_id
        version_folder.mkdir(parents=True, exist_ok=True)

        client = (version_json.get("downloads") or {}).get("client") or {}
        client_target = version_folder / f"{version_id}.jar"
        client_job = {
            "urls": (
                f"{BMCLAPI_BASE}/version/{version_id}/client",
                client.get("url", ""),
            ),
            "target": client_target,
            "sha1": client.get("sha1", ""),
            "label": f"客户端 {version_id}.jar",
        }

        library_jobs, native_files = self._library_jobs(
            version_json.get("libraries", []),
            libraries_root,
        )

        asset_index_id = (
            version_json.get("assets")
            or (version_json.get("assetIndex") or {}).get("id")
            or "legacy"
        )
        asset_index_data = {}
        asset_index = version_json.get("assetIndex") or {}

        if asset_index.get("url"):
            index_target = (
                assets_root / "indexes" / f"{asset_index_id}.json"
            )
            _download_urls(
                (asset_index["url"],),
                index_target,
                asset_index.get("sha1", ""),
            )
            asset_index_data = json.loads(
                index_target.read_text(encoding="utf-8")
            )

        logging_config = (
            (version_json.get("logging") or {}).get("client") or {}
        )
        logging_file = logging_config.get("file") or {}
        if logging_file.get("url"):
            _download_urls(
                (logging_file["url"],),
                (
                    assets_root
                    / "log_configs"
                    / logging_file.get("id", "client.xml")
                ),
                logging_file.get("sha1", ""),
            )

        asset_jobs = self._asset_jobs(
            asset_index_data,
            assets_root,
        )
        jobs = [client_job] + library_jobs + asset_jobs
        self._run_download_jobs(jobs, workers=48)
        self._extract_natives(
            version_folder,
            version_id,
            native_files,
        )

        json_target = version_folder / f"{version_id}.json"
        json_target.write_text(
            json.dumps(
                version_json,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return {
            "version_folder": version_folder,
            "version_json": version_json,
            "client_target": client_target,
            "native_files": native_files,
        }

    def _install_fabric_version(
        self,
        game_root,
        base_version,
        base_json,
        base_entry,
        loader_version,
        base_native_files=None,
    ):
        profile_url = (
            f"{BMCLAPI_BASE}/fabric-meta/v2/versions/loader/"
            f"{urllib.parse.quote(base_version)}/"
            f"{urllib.parse.quote(loader_version)}/profile/json"
        )
        official_url = (
            "https://meta.fabricmc.net/v2/versions/loader/"
            f"{urllib.parse.quote(base_version)}/"
            f"{urllib.parse.quote(loader_version)}/profile/json"
        )
        self.download_state.update(
            96,
            f"正在获取 Fabric {loader_version} 配置",
        )
        profile = _fetch_json_urls((official_url, profile_url))
        generated_fabric_id = profile.get("id") or (
            f"fabric-loader-{loader_version}-{base_version}"
        )

        merged = dict(base_json)
        merged["id"] = base_version
        merged["inheritsFrom"] = base_version
        merged["fabricLoaderVersion"] = loader_version
        merged["mainClass"] = profile.get(
            "mainClass",
            base_json.get("mainClass", "net.minecraft.client.main.Main"),
        )
        merged["libraries"] = (
            list(base_json.get("libraries", []))
            + list(profile.get("libraries", []))
        )
        merged["releaseTime"] = profile.get(
            "releaseTime",
            base_json.get("releaseTime", ""),
        )
        merged["time"] = profile.get(
            "time",
            base_json.get("time", ""),
        )

        versions_root = game_root / "versions"
        libraries_root = game_root / "libraries"
        version_folder = versions_root / base_version
        version_folder.mkdir(parents=True, exist_ok=True)

        library_jobs, fabric_native_files = self._library_jobs(
            profile.get("libraries", []),
            libraries_root,
        )
        native_files = list(base_native_files or []) + fabric_native_files
        self.download_state.update(
            96,
            f"正在安装 Fabric {loader_version} 依赖",
        )
        self._run_download_jobs(library_jobs, workers=6)
        self._extract_natives(
            version_folder,
            base_version,
            native_files,
        )

        json_target = version_folder / f"{base_version}.json"
        json_target.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        generated_folder = versions_root / generated_fabric_id
        versions_root_resolved = versions_root.resolve()
        generated_resolved = generated_folder.resolve()
        if (
            generated_folder != version_folder
            and generated_folder.is_dir()
            and generated_resolved.parent == versions_root_resolved
        ):
            allowed_names = {
                f"{generated_fabric_id}.json",
                f"{generated_fabric_id}.jar",
                f"{generated_fabric_id}-natives",
            }
            migratable_names = {
                "mods",
                "config",
                "saves",
                "shaderpacks",
                "resourcepacks",
                ".fabric",
                "logs",
            }
            can_remove = True

            for entry in generated_folder.iterdir():
                if entry.name in allowed_names:
                    continue

                if entry.name not in migratable_names:
                    can_remove = False
                    continue

                target = version_folder / entry.name
                target.mkdir(parents=True, exist_ok=True)

                for child in entry.iterdir():
                    child_target = target / child.name
                    if child.is_dir():
                        shutil.copytree(
                            child,
                            child_target,
                            dirs_exist_ok=True,
                        )
                    elif not child_target.exists():
                        shutil.copy2(child, child_target)

            if can_remove:
                shutil.rmtree(generated_folder)

        self.download_state.update(
            97,
            "正在注册 Fabric 版本",
        )

        return base_version

    def _install_installer_loader(
        self,
        game_root,
        base_version,
        loader_id,
        java_path,
    ):
        loader_name, version = loader_id.split(":", 1)
        if loader_name == "forge":
            artifact_path = (
                "net/minecraftforge/forge/"
                f"{version}/forge-{version}-installer.jar"
            )
            installer_urls = (
                f"{BMCLAPI_BASE}/maven/{artifact_path}",
                (
                    "https://maven.minecraftforge.net/"
                    f"{artifact_path}"
                ),
            )
        elif loader_name == "neoforge":
            artifact_path = (
                "net/neoforged/neoforge/"
                f"{version}/neoforge-{version}-installer.jar"
            )
            installer_urls = (
                f"{BMCLAPI_BASE}/maven/{artifact_path}",
                (
                    "https://maven.neoforged.net/releases/"
                    f"{artifact_path}"
                ),
            )
        else:
            raise RuntimeError("暂不支持该模组加载器")

        installer = (
            self.config_path.parent
            / "cache"
            / Path(artifact_path).name
        )
        launcher_profiles = game_root / "launcher_profiles.json"
        if not launcher_profiles.exists():
            launcher_profiles.write_text(
                json.dumps(
                    {
                        "profiles": {},
                        "settings": {},
                        "version": 3,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        self.download_state.update(
            93,
            f"正在下载 {loader_name.title()} 安装器",
        )
        _download_urls(installer_urls, installer)

        log_path = self.config_path.parent / "logs" / "loader-install.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.download_state.update(
            94,
            f"正在安装 {loader_name.title()} {version}",
        )

        with open(
            log_path,
            "a",
            encoding="utf-8",
            errors="replace",
        ) as log:
            log.write(
                f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"{loader_id} -> {game_root}\n"
            )
            result = subprocess.run(
                [
                    str(java_path),
                    "-jar",
                    str(installer),
                    "--installClient",
                    str(game_root),
                ],
                cwd=str(game_root),
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
                **_hidden_process_kwargs(),
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"{loader_name.title()} 安装器返回错误码 "
                f"{result.returncode}，请查看 {log_path}"
            )

        versions_root = game_root / "versions"
        candidates = []

        for folder in versions_root.iterdir():
            if not folder.is_dir():
                continue

            for json_path in folder.glob("*.json"):
                try:
                    data = json.loads(
                        json_path.read_text(encoding="utf-8")
                    )
                except Exception:
                    continue

                candidate_id = str(data.get("id") or json_path.stem)
                main_class = str(data.get("mainClass") or "").lower()
                if data.get("inheritsFrom") != base_version:
                    continue
                if loader_name not in candidate_id.lower() and loader_name not in main_class:
                    continue
                candidates.append((json_path.stat().st_mtime_ns, candidate_id))

        if not candidates:
            raise RuntimeError(
                f"{loader_name.title()} 安装完成，但未找到版本配置"
            )

        candidates.sort(reverse=True)
        installed_id = candidates[0][1]
        installed_json = (
            versions_root / installed_id / f"{installed_id}.json"
        )
        base_json_path = (
            versions_root / base_version / f"{base_version}.json"
        )

        try:
            generated_json = json.loads(
                installed_json.read_text(encoding="utf-8")
            )
            base_json = json.loads(
                base_json_path.read_text(encoding="utf-8")
            )
            merged = dict(base_json)
            merged.update(generated_json)
            merged["id"] = installed_id
            merged["inheritsFrom"] = base_version

            library_map = {}
            for library in (
                list(base_json.get("libraries", []))
                + list(generated_json.get("libraries", []))
            ):
                name = str(library.get("name", ""))
                key = name
                if key:
                    library_map[key] = library
            merged["libraries"] = list(library_map.values())

            merged_arguments = {}
            base_arguments = base_json.get("arguments") or {}
            child_arguments = generated_json.get("arguments") or {}
            for key in ("jvm", "game"):
                merged_arguments[key] = (
                    list(base_arguments.get(key, []))
                    + list(child_arguments.get(key, []))
                )
            merged["arguments"] = merged_arguments
            installed_json.write_text(
                json.dumps(
                    merged,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            raise RuntimeError(
                f"{loader_name.title()} 版本配置合并失败：{exc}"
            )

        base_jar = (
            game_root
            / "versions"
            / base_version
            / f"{base_version}.jar"
        )
        installed_folder = versions_root / installed_id
        installed_jar = installed_folder / f"{installed_id}.jar"
        base_natives = (
            game_root
            / "versions"
            / base_version
            / f"{base_version}-natives"
        )
        installed_natives = (
            installed_folder / f"{installed_id}-natives"
        )

        if base_jar.exists() and not installed_jar.exists():
            shutil.copyfile(base_jar, installed_jar)

        if base_natives.is_dir():
            installed_natives.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                base_natives,
                installed_natives,
                dirs_exist_ok=True,
            )

        return installed_id

    def _register_installed_version(self, game_root, version_id):
        info = self._build_import_info(
            game_root,
            version_id=version_id,
        )

        if not info:
            return None

        data = self._read_config()
        existing = self._find_imported_entry(data, game_root)
        info = self._prepare_folder_entry(
            info,
            existing,
            selected_version_id=version_id,
        )
        self._upsert_imported(info)
        self.imported_info = info
        return info

    def start_version_download(self, version_id, loader_id):
        current = self.download_state.snapshot()

        if current["running"]:
            return {
                "ok": False,
                "message": "已有下载任务正在进行",
            }

        if not version_id:
            return {"ok": False, "message": "未选择 Minecraft 版本"}

        if (
            loader_id != "vanilla"
            and not loader_id.startswith("fabric:")
            and not loader_id.startswith("forge:")
            and not loader_id.startswith("neoforge:")
        ):
            return {"ok": False, "message": "暂不支持该模组加载器"}

        thread = threading.Thread(
            target=self._download_worker,
            args=(version_id, loader_id),
            daemon=True,
        )
        thread.start()
        return {"ok": True, "message": "已开始下载"}

    def _download_worker(self, version_id, loader_id):
        self.download_state.begin(f"正在获取 Minecraft {version_id}")

        try:
            manifest = self._version_manifest()
            entry = next(
                (
                    item
                    for item in manifest.get("versions", [])
                    if item.get("id") == version_id
                ),
                None,
            )

            if not entry:
                raise RuntimeError("未找到该 Minecraft 版本")

            version_json_path = (
                self.config_path.parent
                / "cache"
                / "version-json"
                / f"{version_id}.json"
            )
            urls = (
                entry.get("url", ""),
                f"{BMCLAPI_BASE}/version/{version_id}/json",
            )
            _download_urls(
                urls,
                version_json_path,
                entry.get("sha1", ""),
            )
            version_json = json.loads(
                version_json_path.read_text(encoding="utf-8")
            )
            game_root = self._download_game_root()
            game_root.mkdir(parents=True, exist_ok=True)

            self.download_state.update(
                5,
                f"正在下载原版 {version_id}",
            )
            base_install = self._install_version_files(
                game_root,
                version_id,
                version_json,
                entry,
            )

            java_config = version_json.get("javaVersion") or {}
            required_java = int(
                java_config.get("majorVersion") or 0
            )
            if required_java:
                java = self._ensure_java_runtime(
                    java_config.get("component", ""),
                    required_java,
                )
            else:
                java = self._find_java()

            installed_id = version_id

            if loader_id.startswith("fabric:"):
                loader_version = loader_id.split(":", 1)[1]
                self.download_state.update(
                    96,
                    f"正在安装 Fabric {loader_version}",
                )
                installed_id = self._install_fabric_version(
                    game_root,
                    version_id,
                    version_json,
                    entry,
                    loader_version,
                    base_install.get("native_files", []),
                )
            elif loader_id.startswith(
                ("forge:", "neoforge:")
            ):
                installed_id = self._install_installer_loader(
                    game_root,
                    version_id,
                    loader_id,
                    java,
                )

            info = self._register_installed_version(
                game_root,
                installed_id,
            )
            result = {
                "version_id": installed_id,
                "game_root": str(game_root),
                "source_folder": str(info.get("source_folder"))
                if info
                else str(game_root),
                "display_name": info.get("display_name", installed_id)
                if info
                else installed_id,
            }
            self.download_state.finish(
                result,
                f"{installed_id} 下载完成",
            )
        except DownloadCancelled:
            self.download_state.cancel()
        except Exception as exc:
            try:
                log_path = (
                    self.config_path.parent / "logs" / "download.log"
                )
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(
                    log_path,
                    "a",
                    encoding="utf-8",
                    errors="replace",
                ) as log:
                    log.write(
                        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                        f"{version_id} / {loader_id}\n"
                    )
                    log.write(traceback.format_exc())
                    log.write("\n")
            except Exception:
                pass
            self.download_state.fail(exc)

    def get_download_status(self):
        return self.download_state.snapshot()

    def cancel_download(self):
        if not self.download_state.snapshot()["running"]:
            return {"ok": False, "message": "没有进行中的下载"}
        self.download_state.cancel()
        return {"ok": True, "message": "已取消"}

    def _content_context(self):
        info = self.imported_info or self._load_imported_info()

        if not info:
            raise RuntimeError("请先导入游戏文件夹")

        version_json_path = Path(info.get("version_json", ""))
        version_data = {}
        if version_json_path.exists():
            try:
                version_data = json.loads(
                    version_json_path.read_text(encoding="utf-8")
                )
            except Exception:
                version_data = {}

        version_id = (
            info.get("version_id")
            or version_data.get("id")
            or ""
        )
        main_class = (
            info.get("main_class")
            or version_data.get("mainClass")
            or ""
        ).lower()
        version_lower = version_id.lower()
        loader = ""

        if version_data.get("fabricLoaderVersion"):
            loader = "fabric"
        elif "neoforge" in version_lower or "neoforge" in main_class:
            loader = "neoforge"
        elif "forge" in version_lower or "forge" in main_class:
            loader = "forge"

        return {
            "info": info,
            "game_version": (
                info.get("game_version") or version_id
            ),
            "loader": loader,
            "game_root": Path(info["game_root"]),
            "version_folder": Path(info["version_folder"]),
        }

    def _mcmod_translation(self, title, slug=""):
        keys = [
            value.strip().lower()
            for value in (slug, title)
            if value and value.strip()
        ]

        self._load_translation_cache()

        for key in keys:
            if key in self._translation_cache:
                return self._translation_cache[key]

        queries = []

        for value in (slug, title):
            text = str(value or "").strip()
            if text and text not in queries:
                queries.append(text)

        for query in queries:
            names = self._mcmod_fetch_names(query)

            if not names:
                continue

            translation = self._mcmod_chinese_name(
                names,
                title or query,
                slug or query,
            )

            if translation:
                for key in keys:
                    self._translation_cache[key] = translation
                self._save_translation_cache()
                return translation

            # 页面正常但没有中文名，换关键词也不会改变结果
            break

        # ponytail: 空结果也落盘缓存，避免每次开启动器都重新请求；
        # 译名后续新增时删掉 translations.json 即可刷新
        for key in keys:
            self._translation_cache.setdefault(key, "")
            self._translation_misses.add(key)
        self._save_translation_cache()

        return ""

    def _load_translation_cache(self):
        if self._translation_loaded:
            return

        self._translation_loaded = True

        try:
            data = json.loads(
                self._translation_path.read_text(encoding="utf-8")
            )
        except Exception:
            return

        if not isinstance(data, dict):
            return

        for key, value in (data.get("names") or {}).items():
            if isinstance(value, str) and value:
                self._translation_cache.setdefault(key, value)

        for key in data.get("missing") or []:
            if isinstance(key, str) and key:
                self._translation_cache.setdefault(key, "")
                self._translation_misses.add(key)

    def _save_translation_cache(self):
        try:
            self._translation_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            self._translation_path.write_text(
                json.dumps(
                    {
                        "names": {
                            key: value
                            for key, value in self._translation_cache.items()
                            if value
                        },
                        "missing": sorted(self._translation_misses),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    @staticmethod
    def _mcmod_fetch_names(query):
        for attempt in range(2):
            try:
                url = (
                    "https://www.mcmod.cn/s?key="
                    + urllib.parse.quote(str(query))
                )
                html = _fetch_text_urls((url,), timeout=10)
            except Exception:
                html = ""

            names = Api._mcmod_candidates(html) if html else []

            if names:
                return names

            if attempt == 0:
                time.sleep(0.3)

        return []

    @staticmethod
    def _mcmod_candidates(html):
        entries = re.findall(
            (
                r'href="(?:https?:)?//www\.mcmod\.cn/class/'
                r'\d+\.html"[^>]*>(.*?)</a>'
            ),
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        names = []

        for raw in entries:
            text = unescape(re.sub(r"<[^>]+>", " ", raw))
            text = re.sub(r"\s+", " ", text).strip()
            if text and not text.startswith("www.mcmod.cn"):
                names.append(text)

        return names

    @staticmethod
    def _mcmod_chinese_name(names, title, slug):
        target = re.sub(r"[^a-z0-9]", "", str(title or "").lower())
        slug_target = re.sub(r"[^a-z0-9]", "", str(slug or "").lower())

        for candidate in names:
            key = re.sub(r"[^a-z0-9]", "", candidate.lower())

            if (
                target
                and target not in key
                and (not slug_target or slug_target not in key)
            ):
                continue

            name = candidate.split("(", 1)[0].strip()

            if name.startswith("[") and "]" in name:
                name = name.split("]", 1)[1].strip()

            if name and re.search(r"[\u4e00-\u9fff]", name):
                return name

        return ""

    @staticmethod
    def _minecraft_version(version_data, version_id):
        for key in ("clientVersion", "inheritsFrom"):
            value = str(version_data.get(key) or "").strip()
            if value:
                return value

        match = re.search(r"\d+\.\d+(?:\.\d+)?", str(version_id or ""))
        return match.group(0) if match else str(version_id or "")

    @staticmethod
    def _safe_content_name(value):
        text = re.sub(r'[<>:"/\\|?*]+', "", str(value or ""))
        text = re.sub(r"\s+", "-", text.strip())
        return text or "content"

    def _search_modrinth(
        self,
        category,
        query,
        game_version,
        loader,
        limit,
    ):
        project_type = MODRINTH_PROJECT_TYPE[category]
        facets = [[f"project_type:{project_type}"]]

        if game_version:
            facets.append([f"versions:{game_version}"])

        if category == "mods" and loader:
            facets.append([f"categories:{loader}"])

        params = urllib.parse.urlencode(
            {
                "query": query or "",
                "limit": limit,
                "offset": 0,
                "index": "downloads",
                "facets": json.dumps(facets, separators=(",", ":")),
            }
        )
        data = _fetch_json_urls(
            (
                f"{MCIM_BASE}/modrinth/v2/search?{params}",
                f"https://api.modrinth.com/v2/search?{params}",
            ),
            timeout=6,
            attempts=1,
        )
        results = []
        exact_slug = str(query or "").strip().lower()

        for hit in data.get("hits", []):
            project_id = hit.get("project_id")
            if not project_id:
                continue
            title = hit.get("title") or project_id
            slug = hit.get("slug") or ""
            searchable = (
                f"{title} {slug} {hit.get('description', '')}".lower()
            )
            if query and query.lower() not in searchable:
                continue
            results.append(
                {
                    "source": "modrinth",
                    "source_label": "Modrinth",
                    "project_id": project_id,
                    "slug": slug,
                    "title": title,
                    "description": hit.get("description") or "",
                    "downloads": int(hit.get("downloads") or 0),
                    "icon_url": hit.get("icon_url") or "",
                    "versions": hit.get("versions") or [],
                }
            )

        if exact_slug and not any(
            item["slug"].lower() == exact_slug
            for item in results
        ):
            try:
                exact = _fetch_json_urls(
                    (
                        f"{MCIM_BASE}/modrinth/v2/project/"
                        f"{urllib.parse.quote(exact_slug)}",
                        (
                            "https://api.modrinth.com/v2/project/"
                            f"{urllib.parse.quote(exact_slug)}"
                        ),
                    ),
                    timeout=8,
                    attempts=1,
                )
                if exact.get("project_type") == project_type:
                    results.append(
                        {
                            "source": "modrinth",
                            "source_label": "Modrinth",
                            "project_id": exact.get("id"),
                            "slug": exact.get("slug") or exact_slug,
                            "title": exact.get("title") or exact_slug,
                            "description": exact.get("description") or "",
                            "downloads": int(
                                exact.get("downloads") or 0
                            ),
                            "icon_url": exact.get("icon_url") or "",
                            "versions": exact.get("game_versions") or [],
                        }
                    )
            except Exception:
                pass

        return results, int(data.get("total_hits") or len(results))

    def _search_curseforge(
        self,
        category,
        query,
        game_version,
        loader,
        limit,
    ):
        class_ids = {
            "mods": 6,
            "shaders": 6552,
            "resourcepacks": 12,
        }
        loader_types = {
            "forge": 1,
            "fabric": 4,
            "quilt": 5,
            "neoforge": 6,
        }
        params = {
            "gameId": CURSEFORGE_GAME_ID,
            "searchFilter": query or "",
            "classId": class_ids[category],
            "gameVersion": game_version,
            "pageSize": limit,
            "index": 0,
            "sortField": 2,
            "sortOrder": "desc",
        }

        if category == "mods" and loader in loader_types:
            params["modLoaderType"] = loader_types[loader]

        url = (
            f"{MCIM_BASE}/curseforge/v1/mods/search?"
            + urllib.parse.urlencode(params)
        )
        data = _fetch_json_urls((url,), timeout=6, attempts=1)
        results = []

        for item in data.get("data", []):
            project_id = item.get("id")
            if not project_id:
                continue
            title = item.get("name") or str(project_id)
            slug = item.get("slug") or ""
            searchable = f"{title} {slug}".lower()
            if query and query.lower() not in searchable:
                continue
            logo = item.get("logo") or {}
            results.append(
                {
                    "source": "curseforge",
                    "source_label": "CurseForge",
                    "project_id": str(project_id),
                    "slug": slug,
                    "title": title,
                    "description": item.get("summary") or "",
                    "downloads": int(item.get("downloadCount") or 0),
                    "icon_url": logo.get("url") or "",
                    "versions": [
                        value.get("gameVersion")
                        for value in item.get("latestFilesIndexes", [])
                        if value.get("gameVersion")
                    ],
                }
            )

        pagination = data.get("pagination") or {}
        return results, int(
            pagination.get("totalCount") or len(results)
        )

    def search_content(
        self,
        category,
        query,
        game_version,
        loader,
        page,
    ):
        if category not in MODRINTH_PROJECT_TYPE:
            return {
                "ok": False,
                "message": "该分类暂不支持在线搜索",
            }

        page = max(int(page or 1), 1)
        cache_key = (
            category,
            str(query or "").strip().lower(),
            str(game_version or ""),
            str(loader or ""),
            page,
        )
        cached = self._content_search_cache.get(cache_key)
        if cached and time.time() - cached[0] < 300:
            return cached[1]

        if not loader:
            try:
                loader = self._content_context().get("loader", "")
            except Exception:
                loader = ""

        page_size = 20
        fetch_count = min(page * page_size, 200)
        results = []
        totals = []

        executor = ThreadPoolExecutor(max_workers=2)
        futures = [
            executor.submit(
                self._search_modrinth,
                category,
                query,
                game_version,
                loader,
                fetch_count,
            ),
            executor.submit(
                self._search_curseforge,
                category,
                query,
                game_version,
                loader,
                fetch_count,
            ),
        ]
        succeeded = 0

        try:
            # 慢源不让用户干等：拿到快源结果就返回，慢源下次命中缓存
            for future in as_completed(futures, timeout=6):
                try:
                    items, total = future.result()
                except Exception:
                    continue
                succeeded += 1
                results.extend(items)
                totals.append(total)
        except TimeoutError:
            pass
        finally:
            executor.shutdown(wait=False)

        if not succeeded and not results:
            return {
                "ok": False,
                "message": "内容源连接超时，请稍后重试",
            }

        deduped = {}
        for item in results:
            key = (
                item.get("slug") or item.get("title", "")
            ).strip().lower()
            current = deduped.get(key)
            if not current or item["downloads"] > current["downloads"]:
                deduped[key] = item

        ordered = sorted(
            deduped.values(),
            key=lambda item: item["downloads"],
            reverse=True,
        )
        start = (page - 1) * page_size
        items = ordered[start:start + page_size]
        total = max(totals or [len(ordered)])

        response = {
            "ok": True,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": page * page_size < total,
            "items": items,
        }
        self._content_search_cache[cache_key] = (
            time.time(),
            response,
        )
        return response

    def get_content_versions(
        self,
        category,
        source,
        project_id,
        game_version,
        loader,
    ):
        if category not in MODRINTH_PROJECT_TYPE:
            return {"ok": False, "message": "该分类暂不支持"}

        items = []

        if source == "modrinth":
            project = urllib.parse.quote(str(project_id))
            versions = _fetch_json_urls(
                (
                    f"{MCIM_BASE}/modrinth/v2/project/{project}/version",
                    f"https://api.modrinth.com/v2/project/{project}/version",
                ),
                timeout=10,
                attempts=1,
            )

            for version in versions:
                files = version.get("files") or []
                primary = next(
                    (
                        item
                        for item in files
                        if item.get("primary")
                    ),
                    files[0] if files else None,
                )
                if not primary:
                    continue
                items.append(
                    {
                        "version_id": version.get("id", ""),
                        "version_name": (
                            version.get("version_number")
                            or version.get("name")
                            or ""
                        ),
                        "game_versions": version.get("game_versions") or [],
                        "loaders": version.get("loaders") or [],
                        "file_name": primary.get("filename") or "",
                        "date": version.get("date_published") or "",
                    }
                )
        elif source == "curseforge":
            data = _fetch_json_urls(
                (
                    f"{MCIM_BASE}/curseforge/v1/mods/"
                    f"{urllib.parse.quote(str(project_id))}"
                    "/files?pageSize=50",
                ),
                timeout=10,
                attempts=1,
            )
            loader_names = {
                "Forge": "forge",
                "Fabric": "fabric",
                "NeoForge": "neoforge",
                "Quilt": "quilt",
            }

            for item in data.get("data", []):
                game_versions = item.get("gameVersions") or []
                items.append(
                    {
                        "version_id": str(item.get("id") or ""),
                        "version_name": (
                            item.get("displayName")
                            or item.get("fileName")
                            or ""
                        ),
                        "game_versions": [
                            value
                            for value in game_versions
                            if re.match(r"^\d+\.\d+", value)
                        ],
                        "loaders": [
                            loader_names[value]
                            for value in game_versions
                            if value in loader_names
                        ],
                        "file_name": item.get("fileName") or "",
                        "date": item.get("fileDate") or "",
                    }
                )
        else:
            return {"ok": False, "message": "未知的下载源"}

        items.sort(
            key=lambda item: item.get("date") or "",
            reverse=True,
        )

        target_dir = ""
        current_game_version = ""
        current_loader = ""

        try:
            context = self._content_context()
            current_game_version = context["game_version"]
            current_loader = context["loader"]
            folder = {
                "mods": "mods",
                "shaders": "shaderpacks",
                "resourcepacks": "resourcepacks",
            }[category]
            target_dir = str(context["version_folder"] / folder)
        except Exception:
            pass

        return {
            "ok": True,
            "items": items,
            "target_dir": target_dir,
            "game_version": game_version,
            "loader": loader,
            "current_game_version": current_game_version,
            "current_loader": current_loader,
        }

    def get_content_translations(self, items):
        if not isinstance(items, list):
            return {"ok": True, "translations": {}}

        unique = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            key = f"{item.get('source', '')}:{item.get('project_id', '')}"
            title = item.get("title") or ""
            slug = item.get("slug") or ""
            if key and title:
                unique[key] = (title, slug)

        translations = {}

        def translate(entry):
            key, (title, slug) = entry
            translation = self._mcmod_translation(title, slug)
            return key, translation or ""

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(translate, entry)
                for entry in unique.items()
            ]
            for future in as_completed(futures):
                try:
                    key, translated = future.result()
                    if translated:
                        translations[key] = translated
                except Exception:
                    continue

        return {
            "ok": True,
            "translations": translations,
        }

    def _content_file_modrinth(
        self,
        category,
        project_id,
        game_version,
        loader,
        version_id="",
    ):
        project = urllib.parse.quote(str(project_id))
        versions = _fetch_json_urls(
            (
                f"{MCIM_BASE}/modrinth/v2/project/{project}/version",
                f"https://api.modrinth.com/v2/project/{project}/version",
            ),
            timeout=10,
            attempts=1,
        )
        compatible = []

        for version in versions:
            if version_id:
                if version.get("id") != version_id:
                    continue
                compatible.append(version)
                continue

            if game_version and game_version not in version.get(
                "game_versions",
                [],
            ):
                continue

            if (
                category == "mods"
                and loader
                and loader not in version.get("loaders", [])
            ):
                continue

            compatible.append(version)

        compatible.sort(
            key=lambda item: item.get("date_published", ""),
            reverse=True,
        )

        if not compatible:
            raise RuntimeError(
                "未找到所选模组版本"
                if version_id
                else "没有找到兼容当前版本的文件"
            )

        version = compatible[0]
        files = version.get("files") or []
        file_info = next(
            (item for item in files if item.get("primary")),
            files[0] if files else None,
        )

        if not file_info:
            raise RuntimeError("项目没有可下载文件")

        return {
            "url": file_info.get("url", ""),
            "sha1": (file_info.get("hashes") or {}).get("sha1", ""),
            "file_name": file_info.get("filename", ""),
            "version": version.get("version_number", ""),
        }

    def _content_file_curseforge(
        self,
        category,
        project_id,
        game_version,
        loader,
        version_id="",
    ):
        url = (
            f"{MCIM_BASE}/curseforge/v1/mods/"
            f"{urllib.parse.quote(str(project_id))}/files"
            "?pageSize=50"
        )
        data = _fetch_json_urls((url,), timeout=10, attempts=1)
        compatible = []
        loader_names = {
            "forge": "Forge",
            "fabric": "Fabric",
            "neoforge": "NeoForge",
            "quilt": "Quilt",
        }

        for item in data.get("data", []):
            game_versions = item.get("gameVersions") or []
            if version_id:
                if str(item.get("id")) != str(version_id):
                    continue
                compatible.append(item)
                continue

            if game_version and game_version not in game_versions:
                continue

            if (
                category == "mods"
                and loader
                and loader_names.get(loader)
                not in game_versions
            ):
                continue

            compatible.append(item)

        compatible.sort(
            key=lambda item: item.get("fileDate", ""),
            reverse=True,
        )

        if not compatible:
            raise RuntimeError(
                "未找到所选模组版本"
                if version_id
                else "没有找到兼容当前版本的文件"
            )

        file_info = compatible[0]
        sha1 = ""
        for item in file_info.get("hashes", []):
            if item.get("algo") == 1:
                sha1 = item.get("value", "")
                break

        return {
            "url": file_info.get("downloadUrl", ""),
            "sha1": sha1,
            "file_name": file_info.get("fileName", ""),
            "version": file_info.get("displayName", ""),
        }

    def start_content_download(
        self,
        category,
        source,
        project_id,
        title,
        slug,
        game_version="",
        version_id="",
    ):
        current = self.download_state.snapshot()
        if current["running"]:
            return {"ok": False, "message": "已有下载任务正在进行"}

        thread = threading.Thread(
            target=self._content_download_worker,
            args=(
                category,
                source,
                str(project_id),
                title,
                slug,
                game_version,
                version_id,
            ),
            daemon=True,
        )
        thread.start()
        return {"ok": True, "message": "已开始下载"}

    def _content_download_worker(
        self,
        category,
        source,
        project_id,
        title,
        slug,
        game_version="",
        version_id="",
    ):
        self.download_state.begin(f"正在获取 {title}")

        try:
            context = self._content_context()
            game_version = (
                str(game_version or "").strip()
                or context["game_version"]
            )
            loader = context["loader"]

            if source == "modrinth":
                file_info = self._content_file_modrinth(
                    category,
                    project_id,
                    game_version,
                    loader,
                    version_id,
                )
            elif source == "curseforge":
                file_info = self._content_file_curseforge(
                    category,
                    project_id,
                    game_version,
                    loader,
                    version_id,
                )
            else:
                raise RuntimeError("未知的下载源")

            if not file_info.get("url"):
                raise RuntimeError("文件下载地址为空")

            translation = self._mcmod_translation(title, slug)
            english_name = self._safe_content_name(slug or title)
            prefix = (
                f"[{self._safe_content_name(translation)}]"
                if translation
                else ""
            )
            suffix = Path(file_info.get("file_name", "")).suffix
            if not suffix:
                suffix = Path(
                    urllib.parse.urlparse(
                        file_info["url"]
                    ).path
                ).suffix or ".jar"

            raw_version = (
                file_info.get("version")
                or Path(file_info.get("file_name", "")).stem
                or "latest"
            )
            if str(raw_version).lower().endswith(suffix.lower()):
                raw_version = str(raw_version)[:-len(suffix)]

            if game_version and game_version in str(raw_version):
                tail = str(raw_version).split(game_version, 1)[1]
                raw_version = tail.lstrip("-_.") or str(raw_version)

            file_version = self._safe_content_name(raw_version)

            target_folder = context["version_folder"] / {
                "mods": "mods",
                "shaders": "shaderpacks",
                "resourcepacks": "resourcepacks",
            }[category]
            target_folder.mkdir(parents=True, exist_ok=True)

            filename = (
                f"{prefix}{english_name}-{game_version}-"
                f"{file_version}{suffix}"
            )
            target = target_folder / filename
            self.download_state.update(
                10,
                f"正在下载 {title}",
            )
            self._run_download_jobs(
                [
                    {
                        "urls": (file_info["url"],),
                        "target": target,
                        "sha1": file_info.get("sha1", ""),
                        "label": f"下载 {filename}",
                    }
                ],
                workers=1,
            )
            result = {
                "category": category,
                "path": str(target),
                "filename": filename,
                "game_version": game_version,
                "loader": loader,
            }
            self.download_state.finish(
                result,
                f"{filename} 下载完成",
            )
        except DownloadCancelled:
            self.download_state.cancel()
        except Exception as exc:
            self.download_state.fail(exc)

    def _java_major_version(self, java_path):
        cache_key = str(java_path)
        cached = self._java_version_cache.get(cache_key)
        if cached and time.time() - cached[0] < 300:
            return cached[1]

        try:
            result = subprocess.run(
                [str(java_path), "-version"],
                capture_output=True,
                timeout=8,
                **_hidden_process_kwargs(),
            )
            output = (
                result.stdout + result.stderr
            ).decode("utf-8", errors="replace")
            match = re.search(
                r'version "(\d+)(?:\.(\d+))?',
                output,
            )

            if not match:
                self._java_version_cache[cache_key] = (time.time(), 0)
                return 0

            major = int(match.group(1))
            if major == 1 and match.group(2):
                major = int(match.group(2))
            self._java_version_cache[cache_key] = (time.time(), major)
            return major
        except Exception:
            self._java_version_cache[cache_key] = (time.time(), 0)
            return 0

    def _ensure_java_runtime(self, component, required_major):
        if not required_major:
            return None

        runtime_root = (
            self.config_path.parent
            / "runtime"
            / (component or f"java-{required_major}")
        )
        java_path = runtime_root / "bin" / "java.exe"

        if (
            java_path.exists()
            and self._java_major_version(java_path) >= required_major
        ):
            return java_path

        component_name = component or {
            8: "java-runtime-alpha",
            16: "java-runtime-beta",
            17: "java-runtime-gamma",
            21: "java-runtime-delta",
            25: "java-runtime-epsilon",
        }.get(required_major, "")

        if not component_name:
            raise RuntimeError(
                f"未找到 Java {required_major} 的自动安装配置"
            )

        runtime_manifest = _fetch_json_urls(
            (JAVA_RUNTIME_MANIFEST_URL,),
        )
        platform_key = (
            "windows-arm64"
            if platform.machine().lower() in ("arm64", "aarch64")
            else "windows-x64"
        )
        entries = (
            runtime_manifest.get(platform_key, {})
            .get(component_name, [])
        )

        if not entries:
            raise RuntimeError(
                f"当前平台没有可用的 Java {required_major} 运行时"
            )

        entry = entries[0]
        manifest_url = (
            (entry.get("manifest") or {}).get("url", "")
        )

        if not manifest_url:
            raise RuntimeError(
                f"Java {required_major} 运行时清单地址无效"
            )

        runtime_files = _fetch_json_urls((manifest_url,))
        jobs = []
        root = runtime_root.resolve()

        for relative_name, item in (
            runtime_files.get("files") or {}
        ).items():
            if item.get("type") != "file":
                continue

            raw = (item.get("downloads") or {}).get("raw") or {}
            if not raw.get("url"):
                continue

            relative = Path(relative_name)
            target = (runtime_root / relative).resolve()
            if root != target and root not in target.parents:
                continue

            jobs.append(
                {
                    "urls": (raw["url"],),
                    "target": target,
                    "sha1": raw.get("sha1", ""),
                    "label": f"Java 运行时 {relative.name}",
                }
            )

        self.download_state.update(
            96,
            f"正在准备 Java {required_major} 运行时",
        )
        self._run_download_jobs(jobs, workers=32)

        if (
            not java_path.exists()
            or self._java_major_version(java_path) < required_major
        ):
            raise RuntimeError(
                f"Java {required_major} 运行时安装失败"
            )

        return java_path

    def _registry_java_homes(self):
        if winreg is None:
            return []

        homes = []
        roots = (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\WOW6432Node\JavaSoft",
            ),
        )

        for hive, root in roots:
            for product in (
                "Java Runtime Environment",
                "Java Development Kit",
            ):
                try:
                    with winreg.OpenKey(hive, f"{root}\\{product}") as key:
                        current, _ = winreg.QueryValueEx(
                            key,
                            "CurrentVersion",
                        )
                    with winreg.OpenKey(
                        hive,
                        f"{root}\\{product}\\{current}",
                    ) as key:
                        home, _ = winreg.QueryValueEx(key, "JavaHome")
                        homes.append(Path(home))
                except Exception:
                    continue

        return homes

    def _java_candidates(self):
        if (
            self._java_candidates_cache is not None
            and time.time() - self._java_candidates_cache_time < 60
        ):
            return self._java_candidates_cache

        candidates = []
        configured = self._get_settings().get("java_path")
        if configured:
            candidates.append(Path(configured))

        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            candidates.append(Path(java_home) / "bin" / "java.exe")

        for home in self._registry_java_homes():
            candidates.append(home / "bin" / "java.exe")

        patterns = (
            r"C:\Program Files\Eclipse Adoptium\*\bin\java.exe",
            r"C:\Program Files\Eclipse Foundation\*\bin\java.exe",
            r"C:\Program Files\Amazon Corretto\*\bin\java.exe",
            r"C:\Program Files\Microsoft\jdk-*\bin\java.exe",
            r"C:\Program Files\Zulu\*\bin\java.exe",
            r"C:\Program Files\BellSoft\*\bin\java.exe",
            r"C:\Program Files\Java\*\bin\java.exe",
            r"C:\Program Files\*\bin\java.exe",
            r"I:\hmcl\bin\java.exe",
            r"I:\ModrinthApp\meta\java_versions\*\bin\java.exe",
        )

        for pattern in patterns:
            candidates.extend(
                Path(path)
                for path in glob.glob(pattern)
            )

        candidates.extend(
            Path(path)
            for path in glob.glob(
                str(
                    self.config_path.parent
                    / "runtime"
                    / "*"
                    / "bin"
                    / "java.exe"
                )
            )
        )

        which = shutil.which("javaw") or shutil.which("java")
        if which:
            candidates.append(Path(which))

        unique = []
        seen = set()
        for candidate in candidates:
            try:
                key = str(candidate.resolve()).lower()
            except Exception:
                key = str(candidate).lower()
            if key in seen or not candidate.exists():
                continue
            seen.add(key)
            unique.append(candidate)

        self._java_candidates_cache = unique
        self._java_candidates_cache_time = time.time()
        return unique

    def _java_label(self, java_path):
        text = str(java_path).lower()
        if "minecraftlauncher" in text and "runtime" in text:
            return "Mojang"
        labels = (
            ("temurin", "Temurin"),
            ("adoptium", "Temurin"),
            ("corretto", "Corretto"),
            ("microsoft", "Microsoft"),
            ("zulu", "Zulu"),
            ("bellsoft", "Liberica"),
            ("hmcl", "HMCL"),
        )
        for needle, label in labels:
            if needle in text:
                return label
        return "Java"

    @staticmethod
    def _select_java(records, required):
        if required:
            exact = [item for item in records if item[0] == required]
            if exact:
                return exact[0], "exact"

            higher = sorted(
                (item for item in records if item[0] > required),
                key=lambda item: item[0],
            )
            if higher:
                return higher[0], "higher"

            lower = sorted(
                (item for item in records if item[0] < required),
                key=lambda item: item[0],
                reverse=True,
            )
            if lower:
                return lower[0], "lower"
            return None, "missing"

        return (records[0], "available") if records else (None, "missing")

    def _required_java(self, version_id=""):
        info = None
        if version_id:
            info = self._build_import_info(
                self._download_game_root(),
                version_id=version_id,
            )
        if not info:
            info = self.imported_info or self._load_imported_info()

        if not info:
            return 0

        try:
            data = json.loads(
                Path(info["version_json"]).read_text(encoding="utf-8")
            )
            return int(
                (data.get("javaVersion") or {}).get("majorVersion")
                or 0
            )
        except Exception:
            return 0

    def get_java_status(self, version_id=""):
        required = self._required_java(version_id)
        records = []
        for candidate in self._java_candidates():
            major = self._java_major_version(candidate)
            if major:
                records.append((major, candidate))

        selected, state = self._select_java(records, required)

        if not selected:
            return {
                "ok": False,
                "state": "missing",
                "required": required,
                "message": (
                    f"需要 Java {required}，点击安装"
                    if required
                    else "未找到 Java"
                ),
                "install_url": (
                    "https://adoptium.net/temurin/releases/"
                    + (
                        f"?version={required}&os=windows&arch=x64"
                        if required
                        else "?os=windows&arch=x64"
                    )
                ),
            }

        major, path = selected
        label = self._java_label(path)

        if state == "exact":
            message = f"已找到 Java {major} ({label})"
        elif state == "higher":
            message = (
                f"需要 Java {required}，当前将使用 Java "
                f"{major} ({label})"
            )
        elif state == "lower":
            message = (
                f"需要 Java {required}，当前仅有 Java "
                f"{major}，可能导致无法启动"
            )
        else:
            message = f"已找到 Java {major} ({label})"

        return {
            "ok": state in ("exact", "higher", "available"),
            "state": state,
            "required": required,
            "major": major,
            "path": str(path),
            "label": label,
            "message": message,
        }

    def install_java(self, version_id=""):
        status = self.get_java_status(version_id)
        required = int(status.get("required") or 0)

        if not required:
            return status
        if status.get("state") in ("exact", "higher"):
            return status

        try:
            java = self._ensure_java_runtime("", required)
            self._java_candidates_cache = None
            self._java_choice_cache.clear()
            self._java_version_cache.pop(str(java), None)
            return {
                **self.get_java_status(version_id),
                "path": str(java),
                "message": f"Java {required} 已安装",
            }
        except Exception as exc:
            return {
                **status,
                "ok": False,
                "error": str(exc),
            }

    def _find_java(self, required_major=0):
        cached = self._java_choice_cache.get(required_major)
        if (
            cached
            and Path(cached).exists()
            and time.time() - self._java_choice_cache.get(
                f"{required_major}:time",
                time.time(),
            ) < 300
        ):
            return Path(cached)

        records = []

        for candidate in self._java_candidates():
            major = self._java_major_version(candidate)
            if major:
                records.append((major, candidate))

        selected, state = self._select_java(records, required_major)

        if required_major and state == "missing":
            runtime = self._ensure_java_runtime("", required_major)
            if runtime:
                selected = (required_major, runtime)

        if not selected:
            return None

        chosen = selected[1]
        self._java_choice_cache[required_major] = str(chosen)
        self._java_choice_cache[f"{required_major}:time"] = time.time()
        return chosen

    @staticmethod
    def _performance_jvm_args(memory_mb):
        return [
            f"-Xms{min(memory_mb, 2048)}m",
            f"-Xmx{memory_mb}m",
            "-XX:+UseG1GC",
            "-XX:+ParallelRefProcEnabled",
            "-XX:MaxGCPauseMillis=200",
            "-XX:+UnlockExperimentalVMOptions",
            "-XX:+DisableExplicitGC",
            "-XX:G1NewSizePercent=30",
            "-XX:G1MaxNewSizePercent=40",
            "-XX:G1HeapRegionSize=8M",
            "-XX:G1ReservePercent=20",
            "-XX:G1HeapWastePercent=5",
            "-XX:G1MixedGCCountTarget=4",
            "-XX:InitiatingHeapOccupancyPercent=15",
            "-XX:G1MixedGCLiveThresholdPercent=90",
            "-XX:G1RSetUpdatingPauseTimePercent=5",
            "-XX:SurvivorRatio=32",
            "-XX:MaxTenuringThreshold=1",
            "-Dusing.aikars.flags=https://mcflags.emc.gs",
            "-Daikars.new.flags=true",
        ]

    def _build_launch_command(self, info):
        version_json = json.loads(
            Path(info["version_json"]).read_text(encoding="utf-8")
        )
        libraries_root = Path(info["libraries_root"])
        classpath = [info["version_jar"]]

        for library in version_json.get("libraries", []):
            if not self._library_allowed(library):
                continue

            name_parts = str(library.get("name", "")).split(":")
            if (
                len(name_parts) > 3
                and name_parts[3].startswith("natives-")
            ):
                continue

            artifact_path = (
                library.get("downloads", {}).get("artifact", {}).get("path")
            )

            if artifact_path:
                library_file = libraries_root / artifact_path
            else:
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

        required_java = int(
            (version_json.get("javaVersion") or {}).get(
                "majorVersion"
            )
            or 0
        )
        java = self._find_java(required_java)
        if not java:
            raise RuntimeError("未找到可用的 Java")

        memory_mb = self._get_settings().get("memory_mb", 4096)
        natives = info["natives"]
        premium_account = self._refresh_premium_account()

        if premium_account:
            username = premium_account.get("display_name") or info["username"]
            profile_id = premium_account.get("uuid") or info["uuid"]
            access_token = premium_account.get("access_token", "0")
            client_id = ""
            xuid = ""
            user_type = "msa"
        else:
            username = info["username"]
            profile_id = info["uuid"]
            access_token = "0"
            client_id = info["uuid"]
            xuid = ""
            user_type = "legacy"

        variables = {
            "auth_player_name": username,
            "version_name": info["version_id"],
            "game_directory": info["version_folder"],
            "assets_root": info["assets_root"],
            "game_assets": info["assets_root"],
            "assets_index_name": info["asset_index"],
            "auth_uuid": profile_id,
            "auth_access_token": access_token,
            "auth_session": access_token,
            "clientid": client_id,
            "auth_xuid": xuid,
            "user_type": user_type,
            "version_type": "release",
            "natives_directory": natives,
            "launcher_name": "MinecraftLauncher",
            "launcher_version": "1.0",
            "classpath": os.pathsep.join(classpath),
            "classpath_separator": os.pathsep,
            "library_directory": str(libraries_root),
            "resolution_width": "854",
            "resolution_height": "480",
        }
        arguments = version_json.get("arguments") or {}
        has_modern_arguments = bool(
            arguments.get("jvm") or arguments.get("game")
        )

        if has_modern_arguments:
            jvm_args = self._resolve_version_arguments(
                arguments.get("jvm", []),
                variables,
            )
            game_args = self._resolve_version_arguments(
                arguments.get("game", []),
                variables,
            )

            if (
                "forge" in str(info["version_id"]).lower()
                or "forge" in str(info["main_class"]).lower()
            ):
                jvm_args.insert(
                    0,
                    f"-DlegacyClassPath={os.pathsep.join(classpath)}",
                )

            return [
                str(java),
                *self._performance_jvm_args(memory_mb),
                *jvm_args,
                info["main_class"],
                *game_args,
            ], Path(info["version_folder"])

        minecraft_arguments = version_json.get("minecraftArguments")
        if minecraft_arguments:
            game_args = [
                self._expand_version_argument(
                    value,
                    variables,
                )
                for value in shlex.split(minecraft_arguments)
            ]
            return [
                str(java),
                *self._performance_jvm_args(memory_mb),
                f"-Djava.library.path={natives}",
                f"-Djna.tmpdir={natives}",
                f"-Dorg.lwjgl.system.SharedLibraryExtractPath={natives}",
                f"-Dio.netty.native.workdir={natives}",
                "-cp",
                os.pathsep.join(classpath),
                info["main_class"],
                *game_args,
            ], Path(info["version_folder"])

        if (
            "forge" in str(info["version_id"]).lower()
            or "forge" in str(info["main_class"]).lower()
        ):
            raise RuntimeError("Forge 版本缺少启动参数")

        args = [
            str(java),
            *self._performance_jvm_args(memory_mb),
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
            username,
            "--version",
            info["version_id"],
            "--gameDir",
            info["version_folder"],
            "--assetsDir",
            info["assets_root"],
            "--assetIndex",
            info["asset_index"],
            "--uuid",
            profile_id,
            "--accessToken",
            access_token,
            "--clientId",
            client_id,
            "--xuid",
            xuid,
            "--userType",
            user_type,
            "--versionType",
            "release",
        ]

        return args, Path(info["version_folder"])

    @staticmethod
    def _rules_allow(rules):
        if not rules:
            return True

        allowed = False

        for rule in rules:
            os_rule = rule.get("os") or {}
            os_name = os_rule.get("name")
            if os_name and os_name != "windows":
                continue

            arch = os_rule.get("arch")
            if arch and arch not in ("x86_64", "amd64"):
                continue

            features = rule.get("features") or {}
            if any(bool(value) for value in features.values()):
                continue

            allowed = rule.get("action") == "allow"

        return allowed

    @staticmethod
    def _expand_version_argument(value, variables):
        return re.sub(
            r"\$\{([^}]+)\}",
            lambda match: str(
                variables.get(match.group(1), "")
            ),
            str(value),
        )

    def _resolve_version_arguments(self, arguments, variables):
        result = []

        for argument in arguments or []:
            if isinstance(argument, str):
                result.append(
                    self._expand_version_argument(
                        argument,
                        variables,
                    )
                )
                continue

            if not isinstance(argument, dict):
                continue
            if not self._rules_allow(argument.get("rules")):
                continue

            values = argument.get("value", [])
            if isinstance(values, str):
                values = [values]

            for value in values:
                result.append(
                    self._expand_version_argument(
                        value,
                        variables,
                    )
                )

        return result

    def launch_game(self):
        info = self.imported_info or self._load_imported_info()

        if not info:
            return {"ok": False, "message": "请先导入文件夹"}

        if self.launch_state.process and self.launch_state.process.poll() is None:
            return {"ok": False, "message": "游戏已经在启动"}

        self.imported_info = info
        self.launch_state.reset_log()
        self.launch_state.set_state("launching")
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

        self.launch_state.set_state("stopping")
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
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

        self.launch_state.set_state("stopped")
        self.launch_state.update(0, "游戏已关闭")

    def get_launch_status(self):
        snapshot = self.launch_state.snapshot()
        if (
            snapshot["state"] == "running"
            and not snapshot["running"]
        ):
            self.launch_state.set_state("stopped")
            snapshot["state"] = "stopped"
        return snapshot

    def get_launch_log(self):
        return self.launch_state.get_log()

    def _stream_process_output(self, process, log_path):
        try:
            with open(
                log_path,
                "a",
                encoding="utf-8",
                errors="replace",
            ) as log:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    self.launch_state.append_log(line)
        except Exception as exc:
            self.launch_state.append_log(f"[launcher] 日志读取失败：{exc}")

    def _launch_worker(self, info):
        try:
            self.launch_state.set_state("launching")
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
            process_kwargs = _hidden_process_kwargs()

            process = subprocess.Popen(
                args,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                **process_kwargs,
            )

            self.launch_state.set_process(process)
            self.launch_state.set_state("running")
            self.launch_state.update(100, "游戏已启动")

            if self._get_settings().get("minimize_on_launch"):
                try:
                    webview.windows[0].minimize()
                except Exception:
                    pass

            threading.Thread(
                target=self._stream_process_output,
                args=(process, log_path),
                daemon=True,
            ).start()
        except Exception as exc:
            self.launch_state.set_state("stopped")
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
