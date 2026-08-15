#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import apply_alpha10_input_core_rework as overlay


def replace_first(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count < 1:
        raise RuntimeError(f"{label}: expected at least one match, found 0")
    return text.replace(old, new, 1)


def patch_input_final(root: Path) -> None:
    overlay.patch_input_original(root)
    path = root / "src-tauri" / "src" / "input.rs"
    text = path.read_text(encoding="utf-8")

    # Never wake the mouse worker with an old snapshot. If the worker owns the
    # tiny snapshot lock at this exact instant, skip only this replaceable
    # physical move; the next move will publish the newest state.
    old_mouse = '''fn queue_windows_mouse_move(context: &WindowsCaptureContext, active: &ActiveTarget) -> bool {
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
    new_mouse = '''fn queue_windows_mouse_move(context: &WindowsCaptureContext, active: &ActiveTarget) -> bool {
    DIAG_MOUSE_CAPTURED.fetch_add(1, Ordering::Relaxed);
    let updated = match context.mouse_snapshot.try_lock() {
        Ok(mut snapshot) => {
            *snapshot = Some(active.clone());
            true
        }
        Err(_) => {
            DIAG_MOUSE_SNAPSHOT_SKIPPED.fetch_add(1, Ordering::Relaxed);
            false
        }
    };
    if !updated {
        return true;
    }
    match context.mouse_wake_tx.try_send(()) {
        Ok(()) | Err(mpsc::TrySendError::Full(())) => true,
        Err(mpsc::TrySendError::Disconnected(())) => false,
    }
}'''
    text = replace_first(text, old_mouse, new_mouse, "never wake mouse worker with stale snapshot")

    # The keyboard fallback must not become a new source of mouse-hook stalls.
    # It samples at 8ms cadence, so skipping one cycle is preferable to waiting
    # on ActiveTarget while the low-level mouse hook owns it.
    old_target = '''                let target = context
                    .active
                    .lock()
                    .ok()
                    .and_then(|active| active.as_ref().map(|active| active.target.clone()));'''
    new_target = '''                let target = context
                    .active
                    .try_lock()
                    .ok()
                    .and_then(|active| active.as_ref().map(|active| active.target.clone()));'''
    text = replace_first(text, old_target, new_target, "keyboard fallback never waits on ActiveTarget")
    path.write_text(text, encoding="utf-8")


def patch_windows_injection_final(root: Path) -> None:
    path = root / "src-tauri" / "src" / "windows_input.rs"
    text = path.read_text(encoding="utf-8")

    primary_old = '''        if SendInput(1, &primary, std::mem::size_of::<INPUT>() as i32) != 0 {
            if !FIRST_REMOTE_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                log::info!("[diag] first remote keyboard event injected through SendInput VK path");
            }
            return;
        }'''
    primary_new = '''        if SendInput(1, &primary, std::mem::size_of::<INPUT>() as i32) != 0 {
            crate::input::note_keyboard_injection_result(true, None);
            if !FIRST_REMOTE_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                log::info!("[diag] first remote keyboard event injected through SendInput VK path");
            }
            return;
        }'''
    text = replace_first(text, primary_old, primary_new, "alpha10 primary key injection diagnostics")

    fallback_old = '''            if SendInput(1, &fallback, std::mem::size_of::<INPUT>() as i32) != 0 {
                if !FIRST_REMOTE_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                    log::info!("[diag] first remote keyboard event injected through SendInput scan-code fallback");
                }
                return;
            }
        }
        note_injection_refused("key", primary_error);'''
    fallback_new = '''            if SendInput(1, &fallback, std::mem::size_of::<INPUT>() as i32) != 0 {
                crate::input::note_keyboard_injection_result(true, None);
                if !FIRST_REMOTE_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                    log::info!("[diag] first remote keyboard event injected through SendInput scan-code fallback");
                }
                return;
            }
        }
        let final_error = windows_sys::Win32::Foundation::GetLastError();
        crate::input::note_keyboard_injection_result(false, Some(final_error));
        note_injection_refused("key", if final_error == 0 { primary_error } else { final_error });'''
    text = replace_first(text, fallback_old, fallback_new, "alpha10 fallback key injection diagnostics")
    path.write_text(text, encoding="utf-8")


def patch_frontend_final(root: Path) -> None:
    path = root / "src" / "App.tsx"
    text = path.read_text(encoding="utf-8")

    # WAN reliability replaced the old one-shot refreshKey effect with a retrying
    # readiness poll. Alpha10 only needs a stable insertion marker; temporarily
    # insert the old marker before chooseRole, let the regular overlay add the
    # diagnostics effect, then remove the redundant one-shot refresh again.
    old_effect = '''  useEffect(() => {
    void refreshKey()
  }, [refreshKey])

'''
    choose_role = '''  async function chooseRole(nextRole: MachineRole) {'''
    text = replace_first(text, choose_role, old_effect + choose_role, "temporary frontend diagnostics insertion marker")
    path.write_text(text, encoding="utf-8")

    overlay.patch_frontend_original(root)

    text = path.read_text(encoding="utf-8")
    text = replace_first(text, old_effect, "", "remove redundant one-shot key refresh")
    path.write_text(text, encoding="utf-8")


overlay.replace_once = replace_first
overlay.patch_input_original = overlay.patch_input
overlay.patch_input = patch_input_final
overlay.patch_windows_injection = patch_windows_injection_final
overlay.patch_frontend_original = overlay.patch_frontend
overlay.patch_frontend = patch_frontend_final

if __name__ == "__main__":
    overlay.main()
