import base64
import json
import os
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

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
        self.imported_info = None
        self.launch_state = LaunchState()
        self.premium_login_state = PremiumLoginState()

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

    def _read_saved_account(self):
        data = self._read_config()
        account = data.get("account")

        if isinstance(account, dict) and account.get("display_name"):
            return account

        return None

    def _save_account(self, account):
        data = self._read_config()
        data["account"] = account
        self._write_config(data)

    def _account_payload(self, account):
        if not account:
            return {"ok": True, "signed_in": False}

        avatar_path = account.get("avatar_path") or ""
        avatar_uri = ""

        if avatar_path and Path(avatar_path).exists():
            avatar_uri = _avatar_data_uri(avatar_path)
            if not avatar_uri:
                avatar_uri = Path(avatar_path).as_uri()

        return {
            "ok": True,
            "signed_in": True,
            "display_name": account.get("display_name") or "Player",
            "uuid": account.get("uuid") or "",
            "avatar_path": avatar_uri,
        }

    def get_account_info(self):
        return self._account_payload(self._read_saved_account())

    def _friendly_auth_error(self, exc):
        text = str(exc)

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
            versions.append(
                {
                    "version_id": version_id,
                    "version_folder": str(version_folder),
                    "display_name": names.get(version_id, version_id),
                }
            )

        return {
            "ok": True,
            "selected_version_id": selected_version_id or "",
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
        premium_account = self._refresh_premium_account()

        if premium_account:
            username = premium_account.get("display_name") or info["username"]
            profile_id = premium_account.get("uuid") or info["uuid"]
            access_token = premium_account.get("access_token", "0")
            client_id = "MinecraftLauncher"
            xuid = ""
            user_type = "msa"
        else:
            username = info["username"]
            profile_id = info["uuid"]
            access_token = "0"
            client_id = info["uuid"]
            xuid = ""
            user_type = "legacy"

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
