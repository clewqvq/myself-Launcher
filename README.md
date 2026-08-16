# Minecraft Launcher

一个极简白色主义风格的 Minecraft 启动器原型，使用 HTML/CSS/JavaScript 构建界面，Python + PyWebView + PyInstaller 打包为 Windows 单文件 exe。

## 功能

- 版本号跳转、重命名和持久化
- 导入本地 Minecraft 整合包文件夹
- 自动读取版本 json、Fabric 配置和账号信息
- 点击开始按钮启动 Minecraft，并显示启动进度环
- 游戏运行中再次点击开始按钮可关闭游戏
- 右键玩家头像可进行 Microsoft 正版验证，登录后使用正版玩家名、头像和令牌启动游戏

## 正版验证说明

正版验证使用 Minecraft 官方客户端 ID 完成设备码登录，不需要额外注册 Azure 应用，也不需要向 Mojang 单独申请 Minecraft API 权限。验证时需要该微软账号已购买 Minecraft Java 版。

## 运行

使用下方打包命令生成 `dist\MinecraftLauncher.exe` 后运行。

## 打包

```powershell
.venv\bin\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name MinecraftLauncher --add-data "index.html;." --add-data "styles.css;." --add-data "script.js;." --add-data "assets/player-avatar.png;assets" launcher.py
```

## 发布安全

每次推送到 GitHub 前会通过本地 `pre-push` 钩子运行 `release_check.py`，检查已跟踪文件里是否包含玩家名、UUID、GitHub 令牌、本地配置、日志或头像缓存。当前项目已启用 `.githooks`。
