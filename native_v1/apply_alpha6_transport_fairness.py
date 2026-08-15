#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    path = args.root.resolve() / "src-tauri" / "src" / "quic_transport.rs"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''    let (ready_tx, ready_rx) = mpsc::channel();
    let (command_tx, command_rx) = tokio_mpsc::unbounded_channel();
    let peer_health: HealthMap = Arc::new(Mutex::new(HashMap::new()));''',
        '''    let (ready_tx, ready_rx) = mpsc::channel();
    let (command_tx, command_rx) = tokio_mpsc::unbounded_channel();
    let loop_command_tx = command_tx.clone();
    let peer_health: HealthMap = Arc::new(Mutex::new(HashMap::new()));''',
        "clone transport sender for fair mouse rescheduling",
    )

    text = replace_once(
        text,
        '''                secret,
                command_rx,
                on_datagram,''',
        '''                secret,
                command_rx,
                loop_command_tx,
                on_datagram,''',
        "pass transport sender into event loop",
    )

    text = replace_once(
        text,
        '''    secret: SecretKey,
    mut commands: tokio_mpsc::UnboundedReceiver<TransportCommand>,
    on_datagram: DatagramHandler,''',
        '''    secret: SecretKey,
    mut commands: tokio_mpsc::UnboundedReceiver<TransportCommand>,
    command_tx: tokio_mpsc::UnboundedSender<TransportCommand>,
    on_datagram: DatagramHandler,''',
        "transport event loop sender argument",
    )

    old_flush = '''                    TransportCommand::FlushLatest { key } => {
                        // If the path is reconnecting, new mouse events keep replacing the
                        // same slot. Once the connection is usable we send the newest state,
                        // not every coordinate accumulated while waiting.
                        loop {
                            let snapshot = latest_datagrams
                                .lock()
                                .ok()
                                .and_then(|latest| {
                                    latest.get(&key).map(|slot| {
                                        (slot.peer.clone(), slot.payload.clone(), slot.generation)
                                    })
                                });
                            let Some((peer, payload, generation)) = snapshot else {
                                break;
                            };

                            send_datagram_now(&endpoint, &connections, &health, peer, payload).await;

                            let complete = if let Ok(mut latest) = latest_datagrams.lock() {
                                match latest.get(&key) {
                                    Some(slot) if slot.generation == generation => {
                                        latest.remove(&key);
                                        true
                                    }
                                    Some(_) => false,
                                    None => true,
                                }
                            } else {
                                true
                            };
                            if complete {
                                break;
                            }
                        }
                    }'''
    new_flush = '''                    TransportCommand::FlushLatest { key } => {
                        // Send at most ONE current mouse state per scheduler turn. If a newer
                        // coordinate arrived while it was being sent, put one new FlushLatest
                        // token at the BACK of the command queue. This preserves latest-only
                        // mouse semantics while guaranteeing keyboard, clicks and wheel events
                        // already queued can run between mouse frames instead of being starved
                        // by an inner loop during continuous 1000 Hz pointer movement.
                        let snapshot = latest_datagrams
                            .lock()
                            .ok()
                            .and_then(|latest| {
                                latest.get(&key).map(|slot| {
                                    (slot.peer.clone(), slot.payload.clone(), slot.generation)
                                })
                            });
                        let Some((peer, payload, generation)) = snapshot else {
                            continue;
                        };

                        send_datagram_now(&endpoint, &connections, &health, peer, payload).await;

                        let needs_reschedule = if let Ok(mut latest) = latest_datagrams.lock() {
                            match latest.get_mut(&key) {
                                Some(slot) if slot.generation == generation => {
                                    latest.remove(&key);
                                    false
                                }
                                Some(slot) => {
                                    slot.scheduled = true;
                                    true
                                }
                                None => false,
                            }
                        } else {
                            false
                        };

                        if needs_reschedule
                            && command_tx
                                .send(TransportCommand::FlushLatest { key: key.clone() })
                                .is_err()
                        {
                            if let Ok(mut latest) = latest_datagrams.lock() {
                                latest.remove(&key);
                            }
                        }
                    }'''
    text = replace_once(text, old_flush, new_flush, "fair latest-only mouse scheduler")

    path.write_text(text, encoding="utf-8")
    print("alpha.6 transport fairness overlay applied")


if __name__ == "__main__":
    main()
