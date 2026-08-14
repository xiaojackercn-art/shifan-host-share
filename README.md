# 视饭AI：主机共享

<p align="center">
  <strong>一套键盘鼠标，自然跨屏控制多台电脑。</strong><br>
  Windows / macOS 软件 KVM · 局域网自动发现 · QUIC/TLS 低延迟输入
</p>

---

## 产品简介

**视饭AI：主机共享**是一款面向桌面多机工作场景的软件 KVM。键盘和鼠标只需要连接在主控电脑上，光标越过屏幕边缘后即可继续操作另一台电脑，键盘焦点同步跟随，无需额外购买硬件切换器。

当前主线已经完全迁移到 Rust + Tauri 原生架构，不再使用旧版 Python / Deskflow / TCP 24800 方案。

### 核心功能

- **鼠标跨屏**：按真实屏幕位置从左、右、上、下自然切换电脑。
- **键盘跟随**：光标进入被控电脑后，键盘输入自动切换到对应设备。
- **局域网自动发现**：正常使用无需填写 IP、端口或主机名。
- **安全配对**：使用 `XXXX-XXXX-XXXX` 一次性配对码建立可信设备关系。
- **剪贴板同步**：支持文本剪贴板跨设备同步。
- **Windows 原生输入**：低级键鼠 Hook + 原生输入注入；锁屏/UAC 场景可使用系统级输入辅助服务。
- **加密传输**：键鼠和剪贴板数据通过 QUIC/TLS 1.3 通道传输。
- **多屏布局**：可按真实桌面摆放方式调整远端显示器位置。

## 快速开始

### 1. 安装

在两台电脑上安装相同版本的视饭AI：主机共享。

Windows 发布包：

```text
ShifanAI-HostShare-Windows-x64-Setup.exe
```

macOS 发布包：

```text
ShifanAI-HostShare-macOS-AppleSilicon.dmg
ShifanAI-HostShare-macOS-Intel.dmg
```

Windows 安装程序固定使用**简体中文界面**。macOS 首次使用时，需要在系统设置中授权“辅助功能”和“输入监控”。

### 2. 选择电脑角色

- **主控电脑**：键盘、鼠标实际连接在这台电脑上。
- **被控电脑**：另一台需要被控制的电脑。

每台电脑首次启动时选择一次角色即可，后续可以在“设置与排障”中修改。

### 3. 建立连接

1. 两台电脑连接到同一个局域网，并保持软件运行。
2. 被控电脑选择“被控电脑”。
3. 主控电脑进入“连接电脑”。
4. 点击“自动查找另一台电脑”。
5. 找到目标电脑后点击“连接这台电脑”。
6. 将被控电脑显示的 `XXXX-XXXX-XXXX` 配对码输入主控电脑。
7. 进入“屏幕位置”，把第二台屏幕拖到真实的左 / 右 / 上 / 下位置。
8. 将鼠标推到对应屏幕边缘，即可跨屏控制。

正常使用不需要配置 TCP 24800，也不需要手动填写 IP。

## v1.0.0-alpha.3 重点优化

本版本针对两台 Windows 真机测试中暴露的输入体验问题进行专项修正：

- Windows 远端鼠标移动采用更短的原生绝对定位路径，减少每帧输入注入开销。
- 鼠标移动发送节奏由约 125 Hz 提升到约 250 Hz，改善高刷新率显示器上的跟手感。
- 键盘路由与高频鼠标状态锁解耦，避免持续移动鼠标时键盘 Hook 被阻塞。
- Windows 键盘注入优先使用扫描码路径，提高 WebView、输入法和普通桌面应用中的兼容性。
- 修复品牌替换误改 Windows 输入服务内部标识的问题。
- Windows NSIS 安装界面固定为简体中文，安装过程中的自定义状态文案同步中文化。
- 全面调整桌面 UI：字体体系、间距、层级、卡片、按钮、焦点状态和图标显示策略重新统一。

> 当前仍标记为 Alpha，是因为“编译通过”和“真机长时间稳定”是两个不同的验收阶段。Windows → Windows 的键鼠连续控制通过后，再进入 Beta。

## 技术架构

| 模块 | 实现 |
|---|---|
| 桌面界面 | Tauri + React |
| 原生核心 | Rust |
| 局域网发现 | UDP |
| 键鼠低延迟通道 | QUIC Datagram + TLS 1.3 |
| 剪贴板 / 文件通道 | QUIC Stream |
| Windows 输入捕获 | `WH_MOUSE_LL` / `WH_KEYBOARD_LL` |
| Windows 输入注入 | `SetCursorPos` / `SendInput` |
| macOS 输入 | CoreGraphics / Accessibility |
| 配对 | 一次性配对码 + 持久化可信控制端 |

默认网络端口：

- UDP `47833`：局域网发现
- UDP `47834`：QUIC 键鼠及剪贴板传输

更完整的实现说明见 [`native_v1/ARCHITECTURE.md`](native_v1/ARCHITECTURE.md)。

## 真机验收

发布构建必须先通过编译检查，再进行两台实体电脑测试。重点验证：

- 鼠标连续快速移动时没有明显停顿、追帧或周期性卡顿；
- 键盘普通按键、组合键、长按和快速连打均能跟随；
- 鼠标左/右/中键和滚轮正常；
- 跨回主控电脑后不会残留 Ctrl / Shift / Alt 或鼠标按下状态；
- 停止、重新启动和重新连接不会出现假连接；
- 30 分钟连续使用无输入中断后，才具备进入 Beta 的条件。

详细测试方法见 [`native_v1/REAL_DEVICE_TEST.md`](native_v1/REAL_DEVICE_TEST.md)。

## 仓库结构

```text
.github/workflows/build-v1-native.yml   Windows / macOS 构建与预发布
native_v1/VERSION                       当前版本号
native_v1/rebrand_upstream.py           产品名称、配对与交互层覆盖
native_v1/harden_native.py              输入性能、键盘、安装器与兼容性加固
native_v1/product_overrides.css         产品级桌面视觉系统
native_v1/icon_fallback.png             离线产品图标源
native_v1/prepare_icon.py               生成原生多尺寸图标源
native_v1/ARCHITECTURE.md               技术架构与输入链路说明
native_v1/REAL_DEVICE_TEST.md           两台实体电脑验收规范
docs/USER_GUIDE.md                      用户使用说明
docs/CHANGELOG.md                       版本变更记录
```

旧版 v0.9 代码保留在 `legacy-v0.9` 分支，不与当前原生主线混用。

## 构建与发布

主分支更新后，GitHub Actions 会：

1. 拉取固定版本的原生上游源码；
2. 应用视饭AI产品层；
3. 应用输入性能和 Windows 安装加固；
4. 执行前端构建与 Rust `cargo check`；
5. 生成 Windows NSIS 安装包和 macOS DMG；
6. 上传到对应的预发布版本。

第三方开源许可与归属信息见 [`native_v1/THIRD_PARTY_NOTICES.md`](native_v1/THIRD_PARTY_NOTICES.md)。

## 当前状态

当前版本：**v1.0.0-alpha.3**

当前优先级是把 Windows → Windows 真机体验做到稳定、连续、低延迟，再逐步完成 Windows ↔ macOS 和长时间稳定性验收。
