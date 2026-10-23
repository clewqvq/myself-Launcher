# Minecraft Launcher

一个极简、拟态玻璃风格的 Minecraft 启动器，使用 HTML/CSS/JavaScript 构建界面，Python + PyWebView + PyInstaller 打包为 Windows 桌面程序。支持多版本管理、模组下载与本地内容管理、正版登录，以及带进度反馈的一键启动。

## 功能

- 导入多个游戏文件夹，按导入顺序展示文件夹与版本，支持版本重命名和切换
- 下载原版、Fabric、Forge、NeoForge，使用 BMCLAPI / 官方多源回退与 SHA1 校验
- 搜索并下载模组、光影、材质包；支持中文关键词、MC 百科译名、游戏版本/加载器/模组版本选择
- 下载前使用 Windows 原生文件夹选择器，可保存到当前版本对应目录或自定义位置
- 模组、光影、材质包本地管理：查看详情、禁用（`.disabled`）和删除到 Windows 回收站
- 下载兼容性提醒、取消下载、进度环和游戏进程控制
- Microsoft 正版登录与退出，使用正版玩家名、头像和令牌启动游戏
- 设置 Java 路径、启动内存、默认版本、深色模式和自定义壁纸
- 极简拟态玻璃界面，支持浅色/深色主题与窄屏布局

## 正版验证说明

正版验证使用 Minecraft 官方客户端 ID 完成设备码登录，不需要额外注册 Azure 应用，也不需要向 Mojang 单独申请 Minecraft API 权限。验证时需要该微软账号已购买 Minecraft Java 版。

## 运行

使用下方打包命令生成 `dist\MinecraftLauncher\MinecraftLauncher.exe` 后运行。

## 打包

```powershell
.venv\bin\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name MinecraftLauncher --add-data "index.html;." --add-data "styles.css;." --add-data "script.js;." --add-data "assets/player-avatar.png;assets" launcher.py
```

## 发布安全

每次推送到 GitHub 前会通过本地 `pre-push` 钩子运行 `release_check.py`，检查已跟踪文件里是否包含玩家名、UUID、GitHub 令牌、本地配置、日志或头像缓存。当前项目已启用 `.githooks`。

## 自动发布

推送 `v*` 标签（例如 `v1.0.0`）会触发 GitHub Actions：在 Windows 上运行发布检查、使用 PyInstaller 构建 `--onedir` 版本，并创建附带 `MinecraftLauncher-windows-x64.zip` 的 GitHub Release。

## 许可证

本项目使用 MIT License，详见 [LICENSE](LICENSE)。
