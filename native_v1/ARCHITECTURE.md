# 视饭AI:主机共享 Native 架构说明

## 1. 设计目标

Native 版本的目标不是在旧版 Python + Deskflow 外面继续增加兼容层，而是把键鼠共享的关键路径收敛到一个可控的原生桌面进程中：

- Windows / macOS 原生输入捕获；
- Rust 输入与连接核心；
- QUIC 实时输入通道；
- 不依赖 TCP 24800；
- 不要求同一局域网；
- 用户不需要维护公网 IP、端口或路由器映射；
- 被控电脑生成连接密钥，主控电脑粘贴即可建立连接。

旧版 Python + Deskflow 实现只作为历史版本保留，不与 Native 运行时混用。

## 2. 技术基础

Native 核心基于 MIT 许可的 MyKVM Rust/Tauri 架构，并固定使用上游提交：

```text
a2ea4164861de31b562c8417eeb7879dbc8c23cb
```

构建时不会直接追随上游最新代码，而是对固定提交依次应用产品 Overlay，避免上游变化在没有验收的情况下进入正式安装包。

构建顺序：

```text
固定上游 MyKVM
  ↓
rebrand_upstream.py
  ↓
apply_wan_overlay.py
  ↓
apply_input_quality_overlay.py
  ↓
Tauri / Rust / React 构建
  ↓
Windows NSIS / macOS DMG
```

## 3. 公网连接模型

公网连接使用 Iroh 1.0.3 提供的 Endpoint / QUIC 能力。

每台电脑拥有持久化的 Iroh SecretKey，并由此得到稳定的 EndpointId。被控电脑生成的 `SFAI1-` 连接密钥中包含：

- 目标 EndpointId；
- 设备名称与平台；
- cluster id；
- pair secret；
- 屏幕拓扑信息。

主控电脑解析连接密钥后，先对 EndpointId 进行连接探测，再把该设备保存为 `wan-key` 类型的远端设备。

主控侧不需要知道对方的公网 IP。Iroh 负责底层路径建立；网络条件允许时优先建立端到端路径，直连条件不足时使用其可用的中继路径完成连接。

## 4. 信任与授权

`SFAI1-` 连接密钥属于能力型授权信息。拥有完整密钥的设备能够尝试连接目标 EndpointId，并携带对应 cluster / pair secret 通过输入授权校验。

因此：

- 连接密钥只应交给可信设备；
- 不应写入公开日志、Issue、公开聊天或截图；
- 被控端仍会校验 cluster / pair secret；
- QUIC 传输层同时基于目标 EndpointId 建立加密连接；
- WAN 输入目标不会因为局域网发现状态变化而被误判离线。

当前模型面向用户自己控制的可信设备，不定位为多租户远程桌面访问控制系统。

## 5. 输入数据平面

### 5.1 Windows 主控捕获

Windows 使用低级系统 Hook：

```text
WH_MOUSE_LL
WH_KEYBOARD_LL
```

Hook 线程持续处理 Windows 消息队列，避免通过固定 sleep 轮询造成事件成批到达和额外延迟。

鼠标进入远端屏幕后，本机指针被锚定在边缘附近，物理鼠标增量用于计算远端指针位置。键盘在远端激活期间由同一控制上下文捕获并转发。

### 5.2 鼠标：最新状态优先

鼠标移动和键盘按键不能使用完全相同的队列策略。

鼠标坐标属于“当前状态”。如果公网链路短暂抖动，继续排队并在恢复后逐个发送历史坐标，只会让远端鼠标追赶旧轨迹，形成明显延迟和卡顿。

因此 Native WAN 输入使用：

```text
采样频率：约 250Hz（4ms）
传输：QUIC Datagram
待发送策略：每个目标只保留最新一个鼠标移动状态
```

当一个鼠标包正在发送时，新坐标会覆盖该目标的待发送坐标。网络恢复后发送的是最新位置，而不是回放完整历史队列。

这项设计的目标是消除软件自身制造的排队延迟。公网实际体验仍受物理 RTT、Wi‑Fi 质量、运营商路由和是否走中继影响，因此不把“0ms 网络延迟”作为不现实的产品承诺。

### 5.3 键盘 / 点击 / 滚轮：状态转换不可合并

键盘、鼠标按钮和滚轮属于状态转换：

- KeyDown / KeyUp；
- ButtonDown / ButtonUp；
- Scroll delta。

这些事件继续使用非合并 Datagram 发送，不能因为后续事件到来而覆盖前一个状态，否则会造成按键卡住、点击丢失等错误。

鼠标 latest-only 合并只应用于 `MouseMove`。

### 5.4 WAN 键盘目标一致性

WAN 设备的 `Device.host` 保存的是产品内部地址：

```text
wan://<endpointId>/<clusterId>/<pairSecret>
```

鼠标路径使用构建好的 `InputTarget` 缓存。键盘如果重新从 `Device.host` 拼接传统 socket 地址，会与已经验证可用的 WAN 鼠标目标产生不同路由。

因此 WAN 键盘事件固定复用同一个已构建并验证的 `InputTarget`：

- 相同 EndpointId；
- 相同 WAN peer；
- 相同 cluster / pair secret；
- 相同协议版本。

仅在需要跨平台修饰键映射时尝试读取实时布局；获取不到布局锁时仍使用缓存目标，不阻塞键盘 Hook。

## 6. Windows 输入注入

Windows 普通桌面使用 `SendInput` 注入远端事件。

### 鼠标

- 绝对虚拟桌面坐标；
- `MOUSEEVENTF_ABSOLUTE`；
- `MOUSEEVENTF_VIRTUALDESK`；
- 失败时保留必要的 CursorPos 回退路径。

### 键盘

优先使用：

```text
MapVirtualKeyW(VK → Scan Code)
KEYEVENTF_SCANCODE
SendInput
```

对于有有效扫描码的键，`wVk` 置 0，以物理扫描码方式注入；只有无法映射扫描码的键才回退到 Virtual-Key 方式。

这样更接近真实键盘输入路径，也能覆盖部分只接受扫描码语义的应用。

扩展键继续附带 `KEYEVENTF_EXTENDEDKEY`，KeyUp 继续附带 `KEYEVENTF_KEYUP`。

### Windows 权限边界

Windows UIPI 仍然存在：普通权限进程不能可靠向更高完整性级别窗口注入输入。普通桌面直接由当前用户进程注入；安全桌面 / UAC / Ctrl+Alt+Del 等场景需要高权限输入辅助服务。

因此排障时必须区分：

1. 网络是否收到事件；
2. 普通桌面是否能注入；
3. 是否只有管理员 / UIAccess 窗口拒绝输入。

## 7. 接收端处理

被控端收到 Datagram 后：

1. MessagePack 解码；
2. 校验输入协议；
3. 校验或刷新来源授权缓存；
4. 校验目标设备；
5. 将事件映射为本机 `InputCommand`；
6. 在布局锁之外执行系统输入注入。

把系统调用移出布局锁可以避免慢系统调用阻塞后续实时输入包。

## 8. macOS

macOS 使用 CoreGraphics / Accessibility 输入路径。

系统安全模型要求用户授予相应的辅助功能 / 输入监控权限。连接成功但权限未授予时，必须把问题归类为系统输入权限，而不是 QUIC 网络失败。

另外，macOS Secure Keyboard Entry 打开时系统可能主动拒绝合成键盘事件，应在诊断中独立提示。

## 9. 界面与品牌层

产品界面使用 React + TypeScript，通过 Tauri 桌面壳运行。

产品层原则：

- 主流程只保留普通用户需要的角色、密钥、设备和屏幕位置；
- 不把 IP / 端口 / 底层协议参数暴露为默认操作；
- 使用系统 UI 字体，保证 Windows 高 DPI 下文字清晰；
- 主界面使用 SVG 矢量图形，不依赖放大后的低分辨率 Logo；
- 原生应用图标在构建时生成 1024px 高分辨率源，再由 Tauri 生成 Windows `.ico` 和 macOS `.icns`；
- Windows NSIS 固定使用简体中文安装界面。

## 10. 构建与发布

GitHub Actions 分别构建：

```text
Windows x64 NSIS
macOS Apple Silicon DMG
macOS Intel DMG
```

Windows 发布前至少经过：

- React / TypeScript 构建；
- Rust `cargo check`；
- Tauri release build；
- NSIS installer 生成；
- Release asset 上传。

构建成功只代表工程完整性，不自动等价于真实网络体验已经达到 Stable 标准。

## 11. 版本门槛

Alpha 阶段优先完成：

- Windows → Windows 不同网络连接；
- 鼠标跨屏；
- 鼠标无软件队列追赶；
- 键盘字母、数字、修饰键和组合键；
- 点击、拖拽与滚轮；
- 断网 / 恢复不回放历史鼠标轨迹。

Beta 前增加：

- Windows ↔ macOS；
- 30 分钟持续输入；
- 休眠 / 唤醒；
- 网络切换；
- 重启 / 重连；
- 权限场景诊断。

Stable 前继续完成长时间后台运行、资源占用和多种真实网络环境验收。
