# Minecraft Launcher

一个极简白色主义风格的 Minecraft 启动器原型，使用 HTML/CSS/JavaScript 构建界面，Python + PyWebView + PyInstaller 打包为 Windows 单文件 exe。

## 功能

- 版本号跳转、重命名和持久化
- 导入本地 Minecraft 整合包文件夹
- 自动读取版本 json、Fabric 配置和账号信息
- 点击开始按钮启动 Minecraft，并显示启动进度环
- 游戏运行中再次点击开始按钮可关闭游戏

## 运行

直接运行 `dist\MinecraftLauncher.exe`。

## 打包

```powershell
.venv\bin\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name MinecraftLauncher --add-data "index.html;." --add-data "styles.css;." --add-data "script.js;." --add-data "assets/player-avatar.png;assets" launcher.py
```
