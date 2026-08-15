# 视饭AI:主机共享

跨网络的原生键鼠共享工具，用一套键盘鼠标控制多台 Windows / macOS 电脑。

## 核心功能

- **跨网络连接**：基于 Iroh / QUIC 建立端到端连接，支持 NAT 穿透、直连优先与中继回退。
- **键鼠实时共享**：同步鼠标移动、点击、滚轮与键盘输入，采用原生系统级捕获与注入。
- **自然跨屏切换**：按真实显示器方位配置左 / 右 / 上 / 下屏幕关系，鼠标越过边缘即可切换控制目标。
- **低延迟输入链路**：鼠标移动采用实时 Datagram 与 latest-only 策略，减少旧坐标积压；控制事件保持独立可靠发送。
- **安全连接密钥**：连接密钥包含设备身份、授权凭据及可用网络路径，可随时重新生成并撤销旧授权。
- **跨平台原生构建**：提供 Windows x64、macOS Apple Silicon 与 macOS Intel 安装包。

## 技术架构

`Rust` · `Tauri` · `React` · `TypeScript` · `Iroh / QUIC` · `Windows Native Input` · `macOS CoreGraphics`

实时输入使用 QUIC Datagram，Windows 使用 Low-Level Hook / SendInput，macOS 使用 CoreGraphics / Accessibility。

## 下载

通过 GitHub Releases 获取对应平台安装包：

- `ShifanAI-HostShare-Windows-x64-Setup.exe`
- `ShifanAI-HostShare-macOS-AppleSilicon.dmg`
- `ShifanAI-HostShare-macOS-Intel.dmg`

## License

第三方组件与许可证信息见 [`native_v1/THIRD_PARTY_NOTICES.md`](native_v1/THIRD_PARTY_NOTICES.md)。
