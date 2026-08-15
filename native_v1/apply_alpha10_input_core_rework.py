#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_input(root: Path) -> None:
    path = root / "src-tauri" / "src" / "input.rs"
    text = path.read_text(encoding="utf-8")

    # Real, frontend-visible counters. The previous alpha.8 breadcrumbs only went
    # to log::info! and several of them fired before authorization/send completion.
    diag_anchor = '''#[cfg(target_os = "windows")]
static WINDOWS_INPUT_DESKTOP_DEFAULT_CACHE: AtomicBool = AtomicBool::new(true);
'''
    diag_block = diag_anchor + r'''

static DIAG_KEY_HOOK_CAPTURED: AtomicU64 = AtomicU64::new(0);
static DIAG_KEY_FALLBACK_CAPTURED: AtomicU64 = AtomicU64::new(0);
static DIAG_KEY_QUEUED: AtomicU64 = AtomicU64::new(0);
static DIAG_KEY_SEND_ACCEPTED: AtomicU64 = AtomicU64::new(0);
static DIAG_KEY_SEND_FAILED: AtomicU64 = AtomicU64::new(0);
static DIAG_KEY_RECEIVED: AtomicU64 = AtomicU64::new(0);
static DIAG_KEY_AUTH_REJECTED: AtomicU64 = AtomicU64::new(0);
static DIAG_KEY_TARGET_REJECTED: AtomicU64 = AtomicU64::new(0);
static DIAG_KEY_INJECT_ATTEMPTED: AtomicU64 = AtomicU64::new(0);
static DIAG_KEY_INJECT_SUCCESS: AtomicU64 = AtomicU64::new(0);
static DIAG_KEY_INJECT_FAILED: AtomicU64 = AtomicU64::new(0);
static DIAG_MOUSE_CAPTURED: AtomicU64 = AtomicU64::new(0);
static DIAG_MOUSE_SNAPSHOT_SKIPPED: AtomicU64 = AtomicU64::new(0);
static DIAG_MOUSE_SEND_ACCEPTED: AtomicU64 = AtomicU64::new(0);
static DIAG_MOUSE_SEND_FAILED: AtomicU64 = AtomicU64::new(0);
#[cfg(target_os = "windows")]
static DIAG_WINDOWS_KEYBOARD_HOOK_INSTALLED: AtomicBool = AtomicBool::new(false);
#[cfg(target_os = "windows")]
static DIAG_WINDOWS_KEYBOARD_FALLBACK_ACTIVE: AtomicBool = AtomicBool::new(false);
#[cfg(target_os = "windows")]
static DIAG_LAST_KEY_HOOK_MS: AtomicU64 = AtomicU64::new(0);

fn diag_clock_ms() -> u64 {
    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now).elapsed().as_millis() as u64
}

fn diag_last_error_cell() -> &'static Mutex<String> {
    static LAST: OnceLock<Mutex<String>> = OnceLock::new();
    LAST.get_or_init(|| Mutex::new(String::new()))
}

fn set_input_diag_error(error: impl Into<String>) {
    if let Ok(mut last) = diag_last_error_cell().lock() {
        *last = error.into();
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InputDiagnostics {
    pub remote_active: bool,
    pub keyboard_hook_installed: bool,
    pub keyboard_fallback_active: bool,
    pub keyboard_hook_captured: u64,
    pub keyboard_fallback_captured: u64,
    pub keyboard_queued: u64,
    pub keyboard_send_accepted: u64,
    pub keyboard_send_failed: u64,
    pub keyboard_received: u64,
    pub keyboard_auth_rejected: u64,
    pub keyboard_target_rejected: u64,
    pub keyboard_inject_attempted: u64,
    pub keyboard_inject_success: u64,
    pub keyboard_inject_failed: u64,
    pub mouse_captured: u64,
    pub mouse_snapshot_skipped: u64,
    pub mouse_send_accepted: u64,
    pub mouse_send_failed: u64,
    pub last_error: String,
}

pub fn input_diagnostics_snapshot(remote_active: bool) -> InputDiagnostics {
    InputDiagnostics {
        remote_active,
        keyboard_hook_installed: {
            #[cfg(target_os = "windows")]
            { DIAG_WINDOWS_KEYBOARD_HOOK_INSTALLED.load(Ordering::Relaxed) }
            #[cfg(not(target_os = "windows"))]
            { false }
        },
        keyboard_fallback_active: {
            #[cfg(target_os = "windows")]
            { DIAG_WINDOWS_KEYBOARD_FALLBACK_ACTIVE.load(Ordering::Relaxed) }
            #[cfg(not(target_os = "windows"))]
            { false }
        },
        keyboard_hook_captured: DIAG_KEY_HOOK_CAPTURED.load(Ordering::Relaxed),
        keyboard_fallback_captured: DIAG_KEY_FALLBACK_CAPTURED.load(Ordering::Relaxed),
        keyboard_queued: DIAG_KEY_QUEUED.load(Ordering::Relaxed),
        keyboard_send_accepted: DIAG_KEY_SEND_ACCEPTED.load(Ordering::Relaxed),
        keyboard_send_failed: DIAG_KEY_SEND_FAILED.load(Ordering::Relaxed),
        keyboard_received: DIAG_KEY_RECEIVED.load(Ordering::Relaxed),
        keyboard_auth_rejected: DIAG_KEY_AUTH_REJECTED.load(Ordering::Relaxed),
        keyboard_target_rejected: DIAG_KEY_TARGET_REJECTED.load(Ordering::Relaxed),
        keyboard_inject_attempted: DIAG_KEY_INJECT_ATTEMPTED.load(Ordering::Relaxed),
        keyboard_inject_success: DIAG_KEY_INJECT_SUCCESS.load(Ordering::Relaxed),
        keyboard_inject_failed: DIAG_KEY_INJECT_FAILED.load(Ordering::Relaxed),
        mouse_captured: DIAG_MOUSE_CAPTURED.load(Ordering::Relaxed),
        mouse_snapshot_skipped: DIAG_MOUSE_SNAPSHOT_SKIPPED.load(Ordering::Relaxed),
        mouse_send_accepted: DIAG_MOUSE_SEND_ACCEPTED.load(Ordering::Relaxed),
        mouse_send_failed: DIAG_MOUSE_SEND_FAILED.load(Ordering::Relaxed),
        last_error: diag_last_error_cell().lock().map(|v| v.clone()).unwrap_or_default(),
    }
}

pub(crate) fn note_keyboard_injection_result(success: bool, error: Option<u32>) {
    DIAG_KEY_INJECT_ATTEMPTED.fetch_add(1, Ordering::Relaxed);
    if success {
        DIAG_KEY_INJECT_SUCCESS.fetch_add(1, Ordering::Relaxed);
    } else {
        DIAG_KEY_INJECT_FAILED.fetch_add(1, Ordering::Relaxed);
        set_input_diag_error(format!("Windows SendInput 键盘注入失败，错误码 {}", error.unwrap_or(0)));
    }
}
'''
    text = replace_once(text, diag_anchor, diag_block, "frontend-visible input diagnostics")

    # Add a mouse snapshot completely separate from ActiveTarget. The alpha.9
    # worker used active.try_lock(); every failed lock consumed the one-slot wake
    # and produced the exact uneven/stuttering cursor seen on real machines.
    text = replace_once(
        text,
        '''    control_tx: mpsc::Sender<WindowsRealtimeEvent>,
    mouse_wake_tx: mpsc::SyncSender<()>,
    targets: Vec<InputTarget>,''',
        '''    control_tx: mpsc::Sender<WindowsRealtimeEvent>,
    mouse_wake_tx: mpsc::SyncSender<()>,
    mouse_snapshot: Mutex<Option<ActiveTarget>>,
    targets: Vec<InputTarget>,''',
        "separate realtime mouse snapshot field",
    )
    text = replace_once(
        text,
        '''            control_tx,
            mouse_wake_tx,
            targets,''',
        '''            control_tx,
            mouse_wake_tx,
            mouse_snapshot: Mutex::new(None),
            targets,''',
        "initialize separate realtime mouse snapshot",
    )

    old_worker_sample = '''                let latest = context
                    .active
                    .try_lock()
                    .ok()
                    .and_then(|active| active.as_ref().cloned());
                let Some(active) = latest else {
                    continue;
                };

                if !send_remote_mouse_move(
                    &context.quic_transport,
                    &active,
                    &context.layout_state,
                    &context.input_events,
                ) {
                    log::debug!("Windows realtime mouse packet send missed");
                }'''
    new_worker_sample = '''                let latest = context
                    .mouse_snapshot
                    .lock()
                    .ok()
                    .and_then(|active| active.as_ref().cloned());
                let Some(active) = latest else {
                    continue;
                };

                if send_remote_mouse_move(
                    &context.quic_transport,
                    &active,
                    &context.layout_state,
                    &context.input_events,
                ) {
                    DIAG_MOUSE_SEND_ACCEPTED.fetch_add(1, Ordering::Relaxed);
                } else {
                    DIAG_MOUSE_SEND_FAILED.fetch_add(1, Ordering::Relaxed);
                    set_input_diag_error("鼠标实时包发送失败");
                }'''
    text = replace_once(text, old_worker_sample, new_worker_sample, "mouse worker never samples ActiveTarget mutex")

    old_queue_mouse = '''fn queue_windows_mouse_move(context: &WindowsCaptureContext) -> bool {
    match context.mouse_wake_tx.try_send(()) {
        Ok(()) | Err(mpsc::TrySendError::Full(())) => true,
        Err(mpsc::TrySendError::Disconnected(())) => false,
    }
}'''
    new_queue_mouse = '''fn queue_windows_mouse_move(context: &WindowsCaptureContext, active: &ActiveTarget) -> bool {
    DIAG_MOUSE_CAPTURED.fetch_add(1, Ordering::Relaxed);
    match context.mouse_snapshot.try_lock() {
        Ok(mut snapshot) => *snapshot = Some(active.clone()),
        Err(_) => {
            // The worker only holds this independent snapshot long enough to clone
            // it. Missing one overwrite is harmless because the one-slot wake stays
            // live and the next physical event replaces it; never block the hook.
            DIAG_MOUSE_SNAPSHOT_SKIPPED.fetch_add(1, Ordering::Relaxed);
        }
    }
    match context.mouse_wake_tx.try_send(()) {
        Ok(()) | Err(mpsc::TrySendError::Full(())) => true,
        Err(mpsc::TrySendError::Disconnected(())) => false,
    }
}'''
    text = replace_once(text, old_queue_mouse, new_queue_mouse, "mouse hook publishes independent latest snapshot")

    # Both queue call sites have an ActiveTarget in scope after alpha.8.
    text = replace_once(text, "if !queue_windows_mouse_move(context) {", "if !queue_windows_mouse_move(context, active_target) {", "active mouse queue carries snapshot")
    text = replace_once(text, "if !queue_windows_mouse_move(context) {", "if !queue_windows_mouse_move(context, &active_target) {", "cross mouse queue carries snapshot")

    # Queue/send diagnostics for keyboard; count success only after send_packet has
    # accepted the packet into the transport path, never before the call.
    old_queue_packet = '''    if matches!(&event, InputEvent::Key { .. })
        && !WINDOWS_FIRST_KEY_CAPTURED.swap(true, Ordering::Relaxed)
    {
        log::info!("[diag] first Windows keyboard event captured and queued");
    }
    context
        .control_tx
        .send(WindowsRealtimeEvent::Packet { target, event })
        .is_ok()'''
    new_queue_packet = '''    let is_key = matches!(&event, InputEvent::Key { .. });
    if is_key {
        DIAG_KEY_QUEUED.fetch_add(1, Ordering::Relaxed);
    }
    let ok = context
        .control_tx
        .send(WindowsRealtimeEvent::Packet { target, event })
        .is_ok();
    if is_key && !ok {
        DIAG_KEY_SEND_FAILED.fetch_add(1, Ordering::Relaxed);
        set_input_diag_error("键盘捕获事件无法进入发送工作线程");
    }
    ok'''
    text = replace_once(text, old_queue_packet, new_queue_packet, "truthful keyboard queue diagnostics")

    old_control_send = '''                        if matches!(&event, InputEvent::Key { .. })
                            && !WINDOWS_FIRST_KEY_SENT.swap(true, Ordering::Relaxed)
                        {
                            log::info!("[diag] first Windows keyboard event left capture worker");
                        }
                        if !send_packet(
                            &context.quic_transport,
                            &target,
                            event,
                            &context.layout_state,
                            &context.input_events,
                        ) {
                            log::debug!("Windows realtime control packet send missed");
                        }'''
    new_control_send = '''                        let is_key = matches!(&event, InputEvent::Key { .. });
                        if send_packet(
                            &context.quic_transport,
                            &target,
                            event,
                            &context.layout_state,
                            &context.input_events,
                        ) {
                            if is_key {
                                DIAG_KEY_SEND_ACCEPTED.fetch_add(1, Ordering::Relaxed);
                            }
                        } else if is_key {
                            DIAG_KEY_SEND_FAILED.fetch_add(1, Ordering::Relaxed);
                            set_input_diag_error("键盘可靠通道发送失败");
                        }'''
    text = replace_once(text, old_control_send, new_control_send, "truthful keyboard send diagnostics")

    # Hook capture diagnostics and timestamp. This timestamp also gates the
    # physical-key fallback so healthy hooks never produce duplicate events.
    key_anchor = '''        let key_code = event.vkCode as u16;
        let down = matches!(message, WM_KEYDOWN | WM_SYSKEYDOWN);'''
    key_replacement = key_anchor + '''
        DIAG_KEY_HOOK_CAPTURED.fetch_add(1, Ordering::Relaxed);
        DIAG_LAST_KEY_HOOK_MS.store(diag_clock_ms(), Ordering::Relaxed);'''
    text = replace_once(text, key_anchor, key_replacement, "keyboard hook capture diagnostics")

    # Install-state diagnostics.
    hook_ready = '''        let _ = ready_tx.send(Ok(()));
        let mut message = MSG::default();'''
    hook_ready_replacement = '''        DIAG_WINDOWS_KEYBOARD_HOOK_INSTALLED.store(true, Ordering::Relaxed);
        let _ = ready_tx.send(Ok(()));
        let mut message = MSG::default();'''
    text = replace_once(text, hook_ready, hook_ready_replacement, "keyboard hook installed state")
    unhook = '''            let _ = UnhookWindowsHookEx(mouse_hook);
            let _ = UnhookWindowsHookEx(keyboard_hook);
        }
        show_windows_cursor_if_needed(&context);'''
    unhook_replacement = '''            let _ = UnhookWindowsHookEx(mouse_hook);
            let _ = UnhookWindowsHookEx(keyboard_hook);
        }
        DIAG_WINDOWS_KEYBOARD_HOOK_INSTALLED.store(false, Ordering::Relaxed);
        DIAG_WINDOWS_KEYBOARD_FALLBACK_ACTIVE.store(false, Ordering::Relaxed);
        show_windows_cursor_if_needed(&context);'''
    text = replace_once(text, unhook, unhook_replacement, "keyboard hook shutdown diagnostics")

    # Fallback physical-key sampler. It is dormant while the low-level hook has
    # delivered any key within the last 120ms and only wakes while remote control
    # is active. This prevents a silently-removed Windows hook from making the
    # keyboard completely dead while avoiding duplicate normal hook traffic.
    worker_anchor = '''#[cfg(target_os = "windows")]
fn queue_windows_mouse_move(context: &WindowsCaptureContext, active: &ActiveTarget) -> bool {'''
    fallback_worker = r'''#[cfg(target_os = "windows")]
fn start_windows_keyboard_fallback_worker(
    context: Arc<WindowsCaptureContext>,
    stop: Arc<AtomicBool>,
) {
    let _ = thread::Builder::new()
        .name("shifanai-keyboard-fallback".into())
        .spawn(move || {
            use windows_sys::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;
            let mut physical = [false; 256];
            let mut primed = false;
            while !stop.load(Ordering::Relaxed) {
                if !context.remote_active.load(Ordering::Relaxed) {
                    DIAG_WINDOWS_KEYBOARD_FALLBACK_ACTIVE.store(false, Ordering::Relaxed);
                    primed = false;
                    thread::sleep(Duration::from_millis(20));
                    continue;
                }

                let last_hook = DIAG_LAST_KEY_HOOK_MS.load(Ordering::Relaxed);
                if last_hook != 0 && diag_clock_ms().saturating_sub(last_hook) < 120 {
                    DIAG_WINDOWS_KEYBOARD_FALLBACK_ACTIVE.store(false, Ordering::Relaxed);
                    primed = false;
                    thread::sleep(Duration::from_millis(8));
                    continue;
                }

                let target = context
                    .active
                    .lock()
                    .ok()
                    .and_then(|active| active.as_ref().map(|active| active.target.clone()));
                let Some(target) = target else {
                    primed = false;
                    thread::sleep(Duration::from_millis(12));
                    continue;
                };

                DIAG_WINDOWS_KEYBOARD_FALLBACK_ACTIVE.store(true, Ordering::Relaxed);
                if !primed {
                    for vk in 8_u16..=254_u16 {
                        if matches!(vk, 0x10 | 0x11 | 0x12) { continue; }
                        physical[vk as usize] = unsafe { GetAsyncKeyState(vk as i32) } < 0;
                    }
                    primed = true;
                    thread::sleep(Duration::from_millis(8));
                    continue;
                }

                for vk in 8_u16..=254_u16 {
                    if matches!(vk, 0x10 | 0x11 | 0x12) { continue; }
                    let down = unsafe { GetAsyncKeyState(vk as i32) } < 0;
                    let slot = &mut physical[vk as usize];
                    if *slot == down { continue; }
                    *slot = down;
                    DIAG_KEY_FALLBACK_CAPTURED.fetch_add(1, Ordering::Relaxed);
                    if queue_windows_packet(&context, target.clone(), InputEvent::Key { key_code: vk, down }) {
                        track_forwarded_key(&context.pressed_keys, vk, down);
                    }
                }
                thread::sleep(Duration::from_millis(8));
            }
            DIAG_WINDOWS_KEYBOARD_FALLBACK_ACTIVE.store(false, Ordering::Relaxed);
        });
}

''' + worker_anchor
    text = replace_once(text, worker_anchor, fallback_worker, "physical keyboard fallback worker")

    start_workers = '''        start_windows_control_worker(Arc::clone(&context), Arc::clone(&stop), control_rx);
        start_windows_mouse_worker(Arc::clone(&context), Arc::clone(&stop), mouse_wake_rx);
        set_current_thread_input_priority();'''
    start_workers_replacement = '''        start_windows_control_worker(Arc::clone(&context), Arc::clone(&stop), control_rx);
        start_windows_mouse_worker(Arc::clone(&context), Arc::clone(&stop), mouse_wake_rx);
        start_windows_keyboard_fallback_worker(Arc::clone(&context), Arc::clone(&stop));
        set_current_thread_input_priority();'''
    text = replace_once(text, start_workers, start_workers_replacement, "start keyboard fallback worker")

    # Receiver diagnostics must distinguish decode/authorization/targeting instead
    # of claiming success immediately after MessagePack decode as alpha.8 did.
    old_receive_breadcrumb = '''        #[cfg(target_os = "windows")]
        if matches!(&packet.event, InputEvent::Key { .. })
            && !WINDOWS_FIRST_KEY_RECEIVED.swap(true, Ordering::Relaxed)
        {
            log::info!("[diag] first remote keyboard event reached receiver");
        }
        let command = {'''
    text = replace_once(text, old_receive_breadcrumb, '''        let is_key = matches!(&packet.event, InputEvent::Key { .. });
        if is_key {
            DIAG_KEY_RECEIVED.fetch_add(1, Ordering::Relaxed);
        }
        let command = {''', "truthful keyboard receive diagnostics")
    text = replace_once(
        text,
        '''                if !packet_authorized(&layout, &packet) {
                    warn_unauthorized_packet(&layout, &packet);
                    return true;
                }''',
        '''                if !packet_authorized(&layout, &packet) {
                    if is_key {
                        DIAG_KEY_AUTH_REJECTED.fetch_add(1, Ordering::Relaxed);
                        set_input_diag_error("被控端拒绝键盘包：连接密钥/授权不匹配");
                    }
                    warn_unauthorized_packet(&layout, &packet);
                    return true;
                }''',
        "keyboard authorization diagnostics",
    )
    text = replace_once(
        text,
        '''            if !packet_targets_local(&layout, &packet.target_device_id, &local_peer_id) {
                return true;
            }''',
        '''            if !packet_targets_local(&layout, &packet.target_device_id, &local_peer_id) {
                if is_key {
                    DIAG_KEY_TARGET_REJECTED.fetch_add(1, Ordering::Relaxed);
                    set_input_diag_error("被控端收到键盘包，但目标设备 ID 不匹配");
                }
                return true;
            }''',
        "keyboard target diagnostics",
    )

    # Non-mouse state transitions now use the reliable ordered QUIC input stream.
    text = replace_once(
        text,
        '''    let send_result = if low_latency_mouse {
        quic_transport.send_latest_datagram(peer, payload)
    } else {
        quic_transport.send_datagram(peer, payload)
    };''',
        '''    let send_result = if low_latency_mouse {
        quic_transport.send_latest_datagram(peer, payload)
    } else {
        quic_transport.send_reliable_input(peer, payload)
    };''',
        "keyboard/buttons/wheel use reliable ordered input stream",
    )

    path.write_text(text, encoding="utf-8")


def patch_windows_injection(root: Path) -> None:
    path = root / "src-tauri" / "src" / "windows_input.rs"
    text = path.read_text(encoding="utf-8")

    # Report actual SendInput success/failure to the frontend-visible diagnostics.
    old_primary = '''        let primary_sent = SendInput(1, &primary, std::mem::size_of::<INPUT>() as i32);
        if primary_sent != 0 {
            if !FIRST_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                log::info!("[diag] first remote keyboard event injected through SendInput vk={key_code}");
            }
            return;
        }'''
    new_primary = '''        let primary_sent = SendInput(1, &primary, std::mem::size_of::<INPUT>() as i32);
        if primary_sent != 0 {
            crate::input::note_keyboard_injection_result(true, None);
            if !FIRST_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                log::info!("[diag] first remote keyboard event injected through SendInput vk={key_code}");
            }
            return;
        }'''
    text = replace_once(text, old_primary, new_primary, "primary key injection diagnostics")

    old_fallback_tail = '''            if fallback_sent != 0 {
                if !FIRST_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                    log::info!("[diag] first remote keyboard event injected through scan-code fallback vk={key_code}");
                }
                return;
            }
        }

        note_injection_refused("key", windows_sys::Win32::Foundation::GetLastError());'''
    new_fallback_tail = '''            if fallback_sent != 0 {
                crate::input::note_keyboard_injection_result(true, None);
                if !FIRST_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                    log::info!("[diag] first remote keyboard event injected through scan-code fallback vk={key_code}");
                }
                return;
            }
        }

        let error = windows_sys::Win32::Foundation::GetLastError();
        crate::input::note_keyboard_injection_result(false, Some(error));
        note_injection_refused("key", error);'''
    text = replace_once(text, old_fallback_tail, new_fallback_tail, "fallback key injection diagnostics")
    path.write_text(text, encoding="utf-8")


def patch_transport(root: Path) -> None:
    path = root / "src-tauri" / "src" / "quic_transport.rs"
    text = path.read_text(encoding="utf-8")

    # Real network telemetry visible in the UI.
    marker = '''#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WanConnectionInfo {
    pub endpoint_id: String,
    pub relay_urls: Vec<String>,
    pub direct_addresses: Vec<String>,
    pub ready: bool,
}
'''
    telemetry = marker + '''
#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WanRealtimeDiagnostics {
    pub connected: bool,
    pub direct_path_available: bool,
    pub relay_path_available: bool,
    pub path_count: usize,
    pub lost_packets: u64,
    pub datagram_send_buffer_space: usize,
}
'''
    text = replace_once(text, marker, telemetry, "WAN realtime diagnostics model")

    peer_getter = '''    pub fn peer(&self, addr: String, public_key: String, protocol_version: u16) -> PeerEndpoint {
        PeerEndpoint {
            addr,
            public_key,
            protocol_version,
        }
    }
'''
    getter = peer_getter + '''
    pub fn realtime_diagnostics(&self) -> WanRealtimeDiagnostics {
        let connection = self
            .connections
            .lock()
            .ok()
            .and_then(|connections| connections.values().find(|connection| connection.close_reason().is_none()).cloned());
        let Some(connection) = connection else {
            return WanRealtimeDiagnostics::default();
        };
        let paths = connection.paths();
        let stats = connection.stats();
        WanRealtimeDiagnostics {
            connected: true,
            direct_path_available: paths.iter().any(|path| path.is_ip()),
            relay_path_available: paths.iter().any(|path| path.is_relay()),
            path_count: paths.len(),
            lost_packets: stats.lost_packets,
            datagram_send_buffer_space: connection.datagram_send_buffer_space(),
        }
    }

    pub fn send_reliable_input(&self, peer: PeerEndpoint, payload: Vec<u8>) -> Result<(), String> {
        self.validate_datagram(&peer, &payload)?;
        self.commands
            .send(TransportCommand::SendReliableInput { peer, payload })
            .map_err(|_| "WAN transport is stopped".to_string())
    }
'''
    text = replace_once(text, peer_getter, getter, "reliable input API and network diagnostics")

    # Command type for ordered reliable keyboard/button/wheel frames.
    text = replace_once(
        text,
        '''    SendDatagram {
        peer: PeerEndpoint,
        payload: Vec<u8>,
    },
    FlushLatest {''',
        '''    SendDatagram {
        peer: PeerEndpoint,
        payload: Vec<u8>,
    },
    SendReliableInput {
        peer: PeerEndpoint,
        payload: Vec<u8>,
    },
    FlushLatest {''',
        "reliable input transport command",
    )

    # One persistent uni stream per peer. Frame each input packet as u32 length +
    # MessagePack. A stream provides ordering and retransmission; mouse datagrams
    # remain independent so mouse loss can never block a key transition.
    loop_anchor = '''    let mut address_refresh = tokio::time::interval(Duration::from_secs(1));
    address_refresh.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {'''
    loop_replacement = '''    let mut address_refresh = tokio::time::interval(Duration::from_secs(1));
    address_refresh.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut reliable_input_streams: HashMap<String, iroh::endpoint::SendStream> = HashMap::new();

    loop {'''
    text = replace_once(text, loop_anchor, loop_replacement, "persistent reliable input stream map")

    handler_anchor = '''                    TransportCommand::SendDatagram { peer, payload } => {
                        send_datagram_now(&endpoint, &connections, &health, peer, payload).await;
                    }
                    TransportCommand::FlushLatest { key } => {'''
    handler_replacement = '''                    TransportCommand::SendDatagram { peer, payload } => {
                        send_datagram_now(&endpoint, &connections, &health, peer, payload).await;
                    }
                    TransportCommand::SendReliableInput { peer, payload } => {
                        send_reliable_input_now(
                            &endpoint,
                            &connections,
                            &health,
                            &mut reliable_input_streams,
                            peer,
                            payload,
                        ).await;
                    }
                    TransportCommand::FlushLatest { key } => {'''
    text = replace_once(text, handler_anchor, handler_replacement, "handle reliable input frames")

    send_anchor = '''async fn send_datagram_now(
    endpoint: &Endpoint,
    connections: &ConnectionMap,
    health: &HealthMap,
    peer: PeerEndpoint,
    payload: Vec<u8>,
) {'''
    reliable_fn = r'''async fn send_reliable_input_now(
    endpoint: &Endpoint,
    connections: &ConnectionMap,
    health: &HealthMap,
    streams: &mut HashMap<String, iroh::endpoint::SendStream>,
    peer: PeerEndpoint,
    payload: Vec<u8>,
) {
    const MAGIC: &[u8; 4] = b"SFI1";
    let key = health_key(&peer).to_string();
    for attempt in 0..2 {
        if !streams.contains_key(&key) {
            let connection = match ensure_connection(endpoint, connections, &peer).await {
                Ok(connection) => connection,
                Err(error) => {
                    record_peer_failure(health, &key, &error);
                    return;
                }
            };
            match connection.open_uni().await {
                Ok(mut stream) => {
                    if let Err(error) = stream.write_all(MAGIC).await {
                        record_peer_failure(health, &key, &format!("reliable input stream header: {error}"));
                        continue;
                    }
                    streams.insert(key.clone(), stream);
                }
                Err(error) => {
                    record_peer_failure(health, &key, &format!("open reliable input stream: {error}"));
                    return;
                }
            }
        }

        let length = (payload.len() as u32).to_be_bytes();
        let result = if let Some(stream) = streams.get_mut(&key) {
            if let Err(error) = stream.write_all(&length).await {
                Err(format!("reliable input frame length: {error}"))
            } else if let Err(error) = stream.write_all(&payload).await {
                Err(format!("reliable input frame payload: {error}"))
            } else {
                Ok(())
            }
        } else {
            Err("reliable input stream disappeared".to_string())
        };
        match result {
            Ok(()) => {
                record_peer_success(health, &key);
                return;
            }
            Err(error) => {
                streams.remove(&key);
                if attempt == 1 {
                    record_peer_failure(health, &key, &error);
                    return;
                }
            }
        }
    }
}

''' + send_anchor
    text = replace_once(text, send_anchor, reliable_fn, "reliable input stream sender")

    # Accept and continuously decode the persistent ordered input stream on every
    # connection, forwarding each framed payload to the exact same input handler
    # used by datagrams.
    bi_anchor = '''    tokio::spawn(async move {
        loop {
            let (mut send, mut recv) = match connection.accept_bi().await {'''
    uni_block = r'''    let uni_connection = connection.clone();
    let uni_handler = Arc::clone(&on_datagram);
    tokio::spawn(async move {
        loop {
            let mut recv = match uni_connection.accept_uni().await {
                Ok(stream) => stream,
                Err(_) => break,
            };
            let handler = Arc::clone(&uni_handler);
            tokio::spawn(async move {
                let mut magic = [0_u8; 4];
                if recv.read_exact(&mut magic).await.is_err() || &magic != b"SFI1" {
                    return;
                }
                loop {
                    let mut length = [0_u8; 4];
                    if recv.read_exact(&mut length).await.is_err() {
                        break;
                    }
                    let length = u32::from_be_bytes(length) as usize;
                    if length == 0 || length > MAX_DATAGRAM_BYTES {
                        break;
                    }
                    let mut payload = vec![0_u8; length];
                    if recv.read_exact(&mut payload).await.is_err() {
                        break;
                    }
                    handler(payload, source);
                }
            });
        }
    });

''' + bi_anchor
    text = replace_once(text, bi_anchor, uni_block, "receive persistent reliable input stream")
    path.write_text(text, encoding="utf-8")


def patch_backend(root: Path) -> None:
    path = root / "src-tauri" / "src" / "lib.rs"
    text = path.read_text(encoding="utf-8")

    command_anchor = '''#[tauri::command]
fn wan_connection_info(
    state: tauri::State<'_, AppRuntime>,
) -> Result<quic_transport::WanConnectionInfo, String> {'''
    diagnostics_command = r'''#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RealtimeDiagnostics {
    input: input::InputDiagnostics,
    network: quic_transport::WanRealtimeDiagnostics,
}

#[tauri::command]
fn input_diagnostics(state: tauri::State<'_, AppRuntime>) -> RealtimeDiagnostics {
    let input = input::input_diagnostics_snapshot(state.remote_input_active.load(Ordering::Relaxed));
    let network = state
        .quic_transport_handle()
        .map(|transport| transport.realtime_diagnostics())
        .unwrap_or_default();
    RealtimeDiagnostics { input, network }
}

''' + command_anchor
    text = replace_once(text, command_anchor, diagnostics_command, "input diagnostics command")

    text = replace_once(
        text,
        '''            scan_lan_peers,
            wan_connection_info,
            regenerate_wan_connection_key,''',
        '''            scan_lan_peers,
            wan_connection_info,
            input_diagnostics,
            regenerate_wan_connection_key,''',
        "register input diagnostics command",
    )
    path.write_text(text, encoding="utf-8")


def patch_frontend(root: Path) -> None:
    path = root / "src" / "App.tsx"
    text = path.read_text(encoding="utf-8")

    brand_anchor = '''function BrandMark({ compact = false }: { compact?: boolean }) {'''
    interfaces = r'''interface InputDiagnostics {
  remoteActive: boolean
  keyboardHookInstalled: boolean
  keyboardFallbackActive: boolean
  keyboardHookCaptured: number
  keyboardFallbackCaptured: number
  keyboardQueued: number
  keyboardSendAccepted: number
  keyboardSendFailed: number
  keyboardReceived: number
  keyboardAuthRejected: number
  keyboardTargetRejected: number
  keyboardInjectAttempted: number
  keyboardInjectSuccess: number
  keyboardInjectFailed: number
  mouseCaptured: number
  mouseSnapshotSkipped: number
  mouseSendAccepted: number
  mouseSendFailed: number
  lastError: string
}

interface WanRealtimeDiagnostics {
  connected: boolean
  directPathAvailable: boolean
  relayPathAvailable: boolean
  pathCount: number
  lostPackets: number
  datagramSendBufferSpace: number
}

interface RealtimeDiagnostics {
  input: InputDiagnostics
  network: WanRealtimeDiagnostics
}

''' + brand_anchor
    text = replace_once(text, brand_anchor, interfaces, "frontend diagnostics interfaces")

    state_anchor = '''  const [keyGeneratedAt, setKeyGeneratedAt] = useState('')
'''
    state_replacement = state_anchor + '''  const [diagnostics, setDiagnostics] = useState<RealtimeDiagnostics | null>(null)
'''
    text = replace_once(text, state_anchor, state_replacement, "diagnostics frontend state")

    effect_anchor = '''  useEffect(() => {
    void refreshKey()
  }, [refreshKey])
'''
    effect_replacement = effect_anchor + r'''

  useEffect(() => {
    let alive = true
    let timer = 0
    const poll = async () => {
      try {
        const next = await invoke<RealtimeDiagnostics>('input_diagnostics')
        if (alive) setDiagnostics(next)
      } catch {
        // Diagnostics must never interfere with control itself.
      }
      if (alive) timer = window.setTimeout(() => void poll(), 500)
    }
    void poll()
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [])
'''
    text = replace_once(text, effect_anchor, effect_replacement, "poll realtime diagnostics")

    message_anchor = '''        {message ? <div className={`toast ${message.includes('失败') || message.includes('invalid') ? 'error' : ''}`}>{message}</div> : null}
'''
    panel = r'''        <section className="panel diagnostics-panel">
          <div className="panel-heading horizontal diagnostics-heading">
            <div>
              <span className="section-kicker">实时诊断</span>
              <h2>键鼠链路</h2>
              <p>这里显示真实运行计数，不再依赖后台日志。数字持续变化表示该环节正在工作。</p>
            </div>
            <span className={`device-state ${diagnostics?.input.remoteActive ? 'ready' : ''}`}><i />{diagnostics?.input.remoteActive ? '正在控制远端' : '等待切入远端'}</span>
          </div>
          <div className="diagnostics-grid">
            <div className="diag-card">
              <strong>主控 · 键盘捕获</strong>
              <span>Hook：{diagnostics?.input.keyboardHookCaptured ?? 0}</span>
              <span>备用捕获：{diagnostics?.input.keyboardFallbackCaptured ?? 0}</span>
              <span>已入队：{diagnostics?.input.keyboardQueued ?? 0}</span>
              <small>{diagnostics?.input.keyboardHookInstalled ? '低级键盘 Hook 已安装' : '键盘 Hook 未安装'}{diagnostics?.input.keyboardFallbackActive ? ' · 备用捕获正在接管' : ''}</small>
            </div>
            <div className="diag-card">
              <strong>传输 · 可靠键盘通道</strong>
              <span>发送接受：{diagnostics?.input.keyboardSendAccepted ?? 0}</span>
              <span>发送失败：{diagnostics?.input.keyboardSendFailed ?? 0}</span>
              <span>被控接收：{diagnostics?.input.keyboardReceived ?? 0}</span>
              <small>键盘/按键不再和鼠标移动共用不可靠 datagram。</small>
            </div>
            <div className="diag-card">
              <strong>被控 · 鉴权与注入</strong>
              <span>鉴权拒绝：{diagnostics?.input.keyboardAuthRejected ?? 0}</span>
              <span>目标拒绝：{diagnostics?.input.keyboardTargetRejected ?? 0}</span>
              <span>注入成功 / 失败：{diagnostics?.input.keyboardInjectSuccess ?? 0} / {diagnostics?.input.keyboardInjectFailed ?? 0}</span>
              <small>{diagnostics?.input.lastError || '当前没有输入错误'}</small>
            </div>
            <div className="diag-card">
              <strong>鼠标 · 实时路径</strong>
              <span>捕获 / 发送：{diagnostics?.input.mouseCaptured ?? 0} / {diagnostics?.input.mouseSendAccepted ?? 0}</span>
              <span>快照竞争跳过：{diagnostics?.input.mouseSnapshotSkipped ?? 0}</span>
              <span>路径：{diagnostics?.network.directPathAvailable ? '存在直连' : diagnostics?.network.relayPathAvailable ? '中继/自动' : '未建立'}</span>
              <small>开放路径 {diagnostics?.network.pathCount ?? 0} · 丢包 {diagnostics?.network.lostPackets ?? 0} · Datagram 缓冲 {diagnostics?.network.datagramSendBufferSpace ?? 0} B</small>
            </div>
          </div>
        </section>

''' + message_anchor
    text = replace_once(text, message_anchor, panel, "visible realtime diagnostics panel")
    path.write_text(text, encoding="utf-8")

    css_path = root / "src" / "index.css"
    css = css_path.read_text(encoding="utf-8")
    css += r'''

.diagnostics-panel { margin-top: 18px; }
.diagnostics-heading { align-items: flex-start; }
.diagnostics-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
.diag-card { min-width: 0; padding: 15px; border: 1px solid #e1e8f1; border-radius: 14px; background: #f9fbfd; display: grid; gap: 7px; }
.diag-card strong { color: #182337; font-size: 13px; }
.diag-card span { color: #40516a; font-size: 12px; font-variant-numeric: tabular-nums; }
.diag-card small { color: #7a8799; font-size: 10.5px; line-height: 1.45; word-break: break-word; }
@media (max-width: 1180px) { .diagnostics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
'''
    css_path.write_text(css, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    patch_input(root)
    patch_windows_injection(root)
    patch_transport(root)
    patch_backend(root)
    patch_frontend(root)
    print("alpha.10 input core rework applied")


if __name__ == "__main__":
    main()
