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

    # 1000 Hz was counterproductive on real Windows machines: the low-level hook
    # thread ended up doing work faster than the transport/desktop could consume it.
    # 500 Hz is still far above normal display refresh rates while leaving headroom
    # for keyboard/button events and preventing rubber-banding under high-poll mice.
    text = replace_once(
        text,
        "const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 1;\nconst DRAG_MOVE_SEND_INTERVAL_MS: u64 = 1;",
        "const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 2;\nconst DRAG_MOVE_SEND_INTERVAL_MS: u64 = 2;",
        "500Hz pointer cadence",
    )

    marker = '''#[cfg(target_os = "windows")]
static WINDOWS_CAPTURE_CONTEXT: Mutex<Option<Arc<WindowsCaptureContext>>> = Mutex::new(None);
'''
    worker_code = r'''#[cfg(target_os = "windows")]
enum WindowsRealtimeEvent {
    Packet {
        target: InputTarget,
        event: InputEvent,
    },
    PositionedPacket {
        active: ActiveTarget,
        event: InputEvent,
    },
}

#[cfg(target_os = "windows")]
static WINDOWS_FIRST_KEY_CAPTURED: AtomicBool = AtomicBool::new(false);
#[cfg(target_os = "windows")]
static WINDOWS_FIRST_KEY_SENT: AtomicBool = AtomicBool::new(false);
#[cfg(target_os = "windows")]
static WINDOWS_FIRST_KEY_RECEIVED: AtomicBool = AtomicBool::new(false);

#[cfg(target_os = "windows")]
fn start_windows_control_worker(
    quic_transport: quic_transport::TransportHandle,
    layout_state: Arc<Mutex<LayoutState>>,
    input_events: Arc<AtomicU64>,
    stop: Arc<AtomicBool>,
    receiver: mpsc::Receiver<WindowsRealtimeEvent>,
) {
    let _ = thread::Builder::new()
        .name("shifanai-control-input".into())
        .spawn(move || {
            while !stop.load(Ordering::Relaxed) {
                let item = match receiver.recv_timeout(Duration::from_millis(100)) {
                    Ok(item) => item,
                    Err(mpsc::RecvTimeoutError::Timeout) => continue,
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                };

                match item {
                    WindowsRealtimeEvent::Packet { target, event } => {
                        if matches!(&event, InputEvent::Key { .. })
                            && !WINDOWS_FIRST_KEY_SENT.swap(true, Ordering::Relaxed)
                        {
                            log::info!("[diag] first Windows keyboard event left capture worker");
                        }
                        if !send_packet(
                            &quic_transport,
                            &target,
                            event,
                            &layout_state,
                            &input_events,
                        ) {
                            log::debug!("Windows realtime control packet send missed");
                        }
                    }
                    WindowsRealtimeEvent::PositionedPacket { active, event } => {
                        // A click/wheel event is uncommon and positional. Send one current
                        // mouse state immediately before it from this control worker so the
                        // hook thread never blocks on network work.
                        let _ = send_remote_mouse_move(
                            &quic_transport,
                            &active,
                            &layout_state,
                            &input_events,
                        );
                        if !send_packet(
                            &quic_transport,
                            &active.target,
                            event,
                            &layout_state,
                            &input_events,
                        ) {
                            log::debug!("Windows positioned control packet send missed");
                        }
                    }
                }
            }
        });
}

#[cfg(target_os = "windows")]
fn start_windows_mouse_worker(
    quic_transport: quic_transport::TransportHandle,
    layout_state: Arc<Mutex<LayoutState>>,
    input_events: Arc<AtomicU64>,
    stop: Arc<AtomicBool>,
    remote_active: Arc<AtomicBool>,
    latest_mouse: Arc<Mutex<Option<ActiveTarget>>>,
    receiver: mpsc::Receiver<()>,
) {
    let _ = thread::Builder::new()
        .name("shifanai-mouse-input".into())
        .spawn(move || {
            while !stop.load(Ordering::Relaxed) {
                match receiver.recv_timeout(Duration::from_millis(100)) {
                    Ok(()) => {}
                    Err(mpsc::RecvTimeoutError::Timeout) => continue,
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                }

                let latest = latest_mouse
                    .lock()
                    .ok()
                    .and_then(|mut slot| slot.take());
                let Some(active) = latest else {
                    continue;
                };
                if !remote_active.load(Ordering::Relaxed) {
                    continue;
                }

                // The producer throttles to 500 Hz and this queue has capacity one.
                // While a send is in flight, newer hook events overwrite latest_mouse;
                // the next token therefore sends only the newest coordinate, never an
                // accumulated trajectory that has to catch up later.
                if !send_remote_mouse_move(
                    &quic_transport,
                    &active,
                    &layout_state,
                    &input_events,
                ) {
                    log::debug!("Windows realtime mouse packet send missed");
                }
            }
        });
}

#[cfg(target_os = "windows")]
fn queue_windows_mouse_move(context: &WindowsCaptureContext, active: &ActiveTarget) -> bool {
    let Ok(mut latest) = context.latest_mouse.lock() else {
        return false;
    };
    *latest = Some(active.clone());
    drop(latest);

    match context.mouse_wake_tx.try_send(()) {
        Ok(()) | Err(mpsc::TrySendError::Full(())) => true,
        Err(mpsc::TrySendError::Disconnected(())) => false,
    }
}

#[cfg(target_os = "windows")]
fn queue_windows_packet(
    context: &WindowsCaptureContext,
    target: InputTarget,
    event: InputEvent,
) -> bool {
    if matches!(&event, InputEvent::Key { .. })
        && !WINDOWS_FIRST_KEY_CAPTURED.swap(true, Ordering::Relaxed)
    {
        log::info!("[diag] first Windows keyboard event captured and queued");
    }
    context
        .control_tx
        .send(WindowsRealtimeEvent::Packet { target, event })
        .is_ok()
}

#[cfg(target_os = "windows")]
fn queue_windows_positioned_packet(
    context: &WindowsCaptureContext,
    active: ActiveTarget,
    event: InputEvent,
) -> bool {
    context
        .control_tx
        .send(WindowsRealtimeEvent::PositionedPacket { active, event })
        .is_ok()
}

''' + marker
    text = replace_once(text, marker, worker_code, "Windows realtime workers")

    text = replace_once(
        text,
        '''    input_events: Arc<AtomicU64>,
    targets: Vec<InputTarget>,''',
        '''    input_events: Arc<AtomicU64>,
    control_tx: mpsc::Sender<WindowsRealtimeEvent>,
    mouse_wake_tx: mpsc::SyncSender<()>,
    latest_mouse: Arc<Mutex<Option<ActiveTarget>>>,
    targets: Vec<InputTarget>,''',
        "Windows capture realtime queue fields",
    )

    old_context = '''        refresh_windows_input_desktop_cache();
        let context = Arc::new(WindowsCaptureContext {
            quic_transport,
            layout_state,
            native_layout,
            active: Mutex::new(None),
            remote_active,
            main_window_focused,
            clipboard_target,
            input_events,
            targets,'''
    new_context = '''        refresh_windows_input_desktop_cache();

        // The Windows low-level hook thread must do almost no work. It owns the
        // system message loop; serialization, QUIC and SendInput-side scheduling
        // are deliberately moved to two independent realtime workers so high-rate
        // mouse traffic can never starve keyboard transitions.
        let (control_tx, control_rx) = mpsc::channel::<WindowsRealtimeEvent>();
        let (mouse_wake_tx, mouse_wake_rx) = mpsc::sync_channel::<()>(1);
        let latest_mouse = Arc::new(Mutex::new(None));
        start_windows_control_worker(
            quic_transport.clone(),
            Arc::clone(&layout_state),
            Arc::clone(&input_events),
            Arc::clone(&stop),
            control_rx,
        );
        start_windows_mouse_worker(
            quic_transport.clone(),
            Arc::clone(&layout_state),
            Arc::clone(&input_events),
            Arc::clone(&stop),
            Arc::clone(&remote_active),
            Arc::clone(&latest_mouse),
            mouse_wake_rx,
        );

        unsafe {
            let _ = windows_sys::Win32::System::Threading::SetThreadPriority(
                windows_sys::Win32::System::Threading::GetCurrentThread(),
                windows_sys::Win32::System::Threading::THREAD_PRIORITY_HIGHEST,
            );
        }

        let context = Arc::new(WindowsCaptureContext {
            quic_transport,
            layout_state,
            native_layout,
            active: Mutex::new(None),
            remote_active,
            main_window_focused,
            clipboard_target,
            input_events,
            control_tx,
            mouse_wake_tx,
            latest_mouse,
            targets,'''
    text = replace_once(text, old_context, new_context, "start Windows realtime workers before hooks")

    # Work only inside the Windows hook/handler section; macOS keeps its existing
    # CGEventTap behavior.
    win_start = text.index('#[cfg(target_os = "windows")]\nunsafe extern "system" fn windows_mouse_proc')
    win_end = text.index('#[cfg(target_os = "macos")]\nfn send_macos_mouse_button', win_start)
    win = text[win_start:win_end]

    old_key_send = '''        if send_packet(
            &context.quic_transport,
            &target,
            InputEvent::Key { key_code, down },
            &context.layout_state,
            &context.input_events,
        ) {
            track_forwarded_key(&context.pressed_keys, key_code, down);
            return 1;
        }'''
    new_key_send = '''        if queue_windows_packet(
            &context,
            target,
            InputEvent::Key { key_code, down },
        ) {
            track_forwarded_key(&context.pressed_keys, key_code, down);
            return 1;
        }'''
    win = replace_once(win, old_key_send, new_key_send, "keyboard hook queues without network")

    old_active_mouse = '''            if !send_remote_mouse_move(
                &context.quic_transport,
                active_target,
                &context.layout_state,
                &context.input_events,
            ) {'''
    new_active_mouse = '''            if !queue_windows_mouse_move(context, active_target) {'''
    win = replace_once(win, old_active_mouse, new_active_mouse, "active mouse move queues without network")

    old_cross_mouse = '''        if !send_remote_mouse_move(
            &context.quic_transport,
            &active_target,
            &context.layout_state,
            &context.input_events,
        ) {'''
    new_cross_mouse = '''        if !queue_windows_mouse_move(context, &active_target) {'''
    win = replace_once(win, old_cross_mouse, new_cross_mouse, "crossing mouse move queues without network")

    old_button_tail = '''    if !send_remote_mouse_move(
        &context.quic_transport,
        &active_target,
        &context.layout_state,
        &context.input_events,
    ) {
        return false;
    }
    mark_mouse_move_sent(&context.last_mouse_move_sent);

    let sent = send_packet(
        &context.quic_transport,
        &active_target.target,
        InputEvent::MouseButton { button, down },
        &context.layout_state,
        &context.input_events,
    );
    if sent {
        update_remote_button_mask(&context.remote_button_mask, button, down);
    }
    sent'''
    new_button_tail = '''    mark_mouse_move_sent(&context.last_mouse_move_sent);
    let sent = queue_windows_positioned_packet(
        context,
        active_target,
        InputEvent::MouseButton { button, down },
    );
    if sent {
        update_remote_button_mask(&context.remote_button_mask, button, down);
    }
    sent'''
    win = replace_once(win, old_button_tail, new_button_tail, "mouse button queues without network")

    old_scroll_tail = '''    if !send_remote_mouse_move(
        &context.quic_transport,
        &active_target,
        &context.layout_state,
        &context.input_events,
    ) {
        return false;
    }
    mark_mouse_move_sent(&context.last_mouse_move_sent);

    send_packet(
        &context.quic_transport,
        &active_target.target,
        InputEvent::Scroll { delta_x, delta_y },
        &context.layout_state,
        &context.input_events,
    )'''
    new_scroll_tail = '''    mark_mouse_move_sent(&context.last_mouse_move_sent);
    queue_windows_positioned_packet(
        context,
        active_target,
        InputEvent::Scroll { delta_x, delta_y },
    )'''
    win = replace_once(win, old_scroll_tail, new_scroll_tail, "scroll queues without network")

    text = text[:win_start] + win + text[win_end:]

    # Receiver-side breadcrumb. Combined with captured/worker/injection markers this
    # makes any future keyboard failure attributable to one exact layer.
    old_receive = '''        let carries_credentials = !packet.pair_secret.trim().is_empty();
        let command = {'''
    new_receive = '''        let carries_credentials = !packet.pair_secret.trim().is_empty();
        #[cfg(target_os = "windows")]
        if matches!(&packet.event, InputEvent::Key { .. })
            && !WINDOWS_FIRST_KEY_RECEIVED.swap(true, Ordering::Relaxed)
        {
            log::info!("[diag] first remote keyboard event received and authorized for dispatch");
        }
        let command = {'''
    text = replace_once(text, old_receive, new_receive, "keyboard receive diagnostic")

    path.write_text(text, encoding="utf-8")


def patch_windows_injection(root: Path) -> None:
    path = root / "src-tauri" / "src" / "windows_input.rs"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''    sync::{Mutex, OnceLock},''',
        '''    sync::{atomic::{AtomicBool, Ordering}, Mutex, OnceLock},''',
        "Windows key injection diagnostics imports",
    )

    old = '''pub fn inject_key(key_code: u16, down: bool) {
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        MapVirtualKeyW, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
        KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, MAPVK_VK_TO_VSC,
    };

    let mut base_flags = if down { 0 } else { KEYEVENTF_KEYUP };
    if is_extended_key_vk(key_code) {
        base_flags |= KEYEVENTF_EXTENDEDKEY;
    }
    let scan = unsafe { MapVirtualKeyW(key_code as u32, MAPVK_VK_TO_VSC) } as u16;

    // Virtual-key injection is the Windows-compatible default for normal desktop
    // applications. alpha.5 forced every key through SCANCODE-only mode, which
    // made keyboard control fail on some real Windows machines even while mouse
    // input kept working. Preserve the scan code as metadata, then fall back to
    // physical scan-code injection only if the primary SendInput call is refused.
    let primary = INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: key_code,
                wScan: scan,
                dwFlags: base_flags,
                time: 0,
                dwExtraInfo: 0,
            },
        },
    };

    unsafe {
        if SendInput(1, &primary, std::mem::size_of::<INPUT>() as i32) != 0 {
            return;
        }

        let primary_error = windows_sys::Win32::Foundation::GetLastError();
        if scan != 0 {
            let fallback = INPUT {
                r#type: INPUT_KEYBOARD,
                Anonymous: INPUT_0 {
                    ki: KEYBDINPUT {
                        wVk: 0,
                        wScan: scan,
                        dwFlags: base_flags | KEYEVENTF_SCANCODE,
                        time: 0,
                        dwExtraInfo: 0,
                    },
                },
            };
            if SendInput(1, &fallback, std::mem::size_of::<INPUT>() as i32) != 0 {
                log::debug!("keyboard virtual-key injection failed but scan-code fallback succeeded");
                return;
            }
        }
        note_injection_refused("key", primary_error);
    }
}
'''
    new = '''pub fn inject_key(key_code: u16, down: bool) {
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        MapVirtualKeyW, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
        KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, MAPVK_VK_TO_VSC,
    };

    static FIRST_REMOTE_KEY_INJECTED: AtomicBool = AtomicBool::new(false);

    // Primary path: canonical virtual-key injection. Do not mix a populated scan
    // code or EXTENDEDKEY flag into a VK-mode event; some Windows applications and
    // keyboard layouts interpret that hybrid form inconsistently.
    let primary_flags = if down { 0 } else { KEYEVENTF_KEYUP };
    let primary = INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: key_code,
                wScan: 0,
                dwFlags: primary_flags,
                time: 0,
                dwExtraInfo: 0,
            },
        },
    };

    unsafe {
        if SendInput(1, &primary, std::mem::size_of::<INPUT>() as i32) != 0 {
            if !FIRST_REMOTE_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                log::info!("[diag] first remote keyboard event injected through SendInput VK path");
            }
            return;
        }

        let primary_error = windows_sys::Win32::Foundation::GetLastError();
        let scan = MapVirtualKeyW(key_code as u32, MAPVK_VK_TO_VSC) as u16;
        if scan != 0 {
            let mut scan_flags = KEYEVENTF_SCANCODE;
            if !down {
                scan_flags |= KEYEVENTF_KEYUP;
            }
            if is_extended_key_vk(key_code) {
                scan_flags |= KEYEVENTF_EXTENDEDKEY;
            }
            let fallback = INPUT {
                r#type: INPUT_KEYBOARD,
                Anonymous: INPUT_0 {
                    ki: KEYBDINPUT {
                        wVk: 0,
                        wScan: scan,
                        dwFlags: scan_flags,
                        time: 0,
                        dwExtraInfo: 0,
                    },
                },
            };
            if SendInput(1, &fallback, std::mem::size_of::<INPUT>() as i32) != 0 {
                if !FIRST_REMOTE_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                    log::info!("[diag] first remote keyboard event injected through SendInput scan-code fallback");
                }
                return;
            }
        }
        note_injection_refused("key", primary_error);
    }
}
'''
    text = replace_once(text, old, new, "clean Windows keyboard SendInput modes")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()

    patch_input(root)
    patch_windows_injection(root)
    print("alpha.8 realtime hook/worker and keyboard injection fixes applied")


if __name__ == "__main__":
    main()
