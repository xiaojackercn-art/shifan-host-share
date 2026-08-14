# 视饭AI:主机共享

面向 Windows / macOS 的软件 KVM：一套键盘鼠标控制多台电脑，支持鼠标跨屏、键盘跟随、滚轮和文本剪贴板同步。

> 当前开发线已经彻底停止 v0.x 的 Python + Deskflow + TCP 24800 方案。新版使用 Rust/Tauri 原生核心、UDP 局域网发现和 QUIC/TLS 通道。

## 普通用户怎么用

只需要记住两个角色：

- **主控电脑**：键盘和鼠标实际插在这台电脑上。
- **被控电脑**：另一台电脑，不需要再准备一套键盘鼠标。

首次启动时两台电脑分别选择自己的角色。之后：

1. 被控电脑保持软件打开；
2. 主控电脑进入 **连接电脑**；
3. 点击 **自动查找另一台电脑**；
4. 找到后点 **连接这台电脑**；
5. 被控电脑出现 `XXXX-XXXX-XXXX` 配对码，输入到主控电脑；
6. 在 **屏幕位置** 中把第二台屏幕拖到真实的左 / 右 / 上 / 下；
7. 鼠标推到屏幕边缘即可跨过去，键盘自动跟随。

正常使用 **不需要输入 IP、不需要填写端口、不需要配置 TCP 24800**。

## 当前架构

- UI / 桌面壳：Tauri + React
- 核心：Rust
- 局域网发现：UDP
- 键鼠与剪贴板：QUIC + TLS
- Windows：原生键鼠 Hook / SendInput 路径
- macOS：CoreGraphics / Accessibility 路径
- 配对：一次性 `XXXX-XXXX-XXXX` 挑战码 + 持久化可信控制端

原生核心基于 MIT 许可的 MyKVM 架构并锁定到固定上游提交，再通过 `native_v1/rebrand_upstream.py` 应用视饭AI产品层。第三方许可见 `native_v1/THIRD_PARTY_NOTICES.md`。

## 仓库结构

```text
.github/workflows/build-v1-native.yml   Windows / macOS 构建与 Release
native_v1/VERSION                       当前原生版本
native_v1/rebrand_upstream.py           产品名称、配对、交互流程覆盖
native_v1/product_overrides.css         视饭AI界面样式
native_v1/icon_fallback.b64             指定产品图标的内置离线源
native_v1/materialize_icon_fallback.py  构建时生成产品 PNG
native_v1/REAL_DEVICE_TEST.md            两台实体电脑验收标准
native_v1/ARCHITECTURE.md                原生架构说明
```

旧的 v0.9 代码已经完整保存在分支 `legacy-v0.9`，不会与新版主线混在一起。

## 发布包

Release 会生成：

- `ShifanAI-HostShare-Windows-x64-Setup.exe`
- `ShifanAI-HostShare-macOS-AppleSilicon.dmg`
- `ShifanAI-HostShare-macOS-Intel.dmg`

macOS 首次使用必须授予辅助功能 / 输入监控权限；这是系统对键鼠控制软件的安全要求。

## 版本门槛

当前 alpha 只在下面条件全部通过后才升级 beta：

- Windows -> Windows 能自动发现和配对；
- 鼠标真实跨屏；
- 键盘跟随；
- 滚轮有效；
- 文本剪贴板至少双向成功一次；
- 停止 / 再启动不会出现假连接或按钮卡死。

详细步骤见 `native_v1/REAL_DEVICE_TEST.md`。
