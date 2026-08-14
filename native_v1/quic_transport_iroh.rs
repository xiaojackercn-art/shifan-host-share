use std::{
    collections::HashMap,
    fs,
    net::{IpAddr, Ipv4Addr, SocketAddr},
    path::{Path, PathBuf},
    sync::{mpsc, Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use iroh::{endpoint::presets, Endpoint, EndpointId, SecretKey};
use tokio::sync::mpsc as tokio_mpsc;

pub const PROTOCOL_VERSION: u16 = 2;

const ALPN: &[u8] = b"shifanai-host-share/2";
const MAX_DATAGRAM_BYTES: usize = 16 * 1024;
pub(crate) const MAX_STREAM_BYTES: usize = 48 * 1024 * 1024;
const DATAGRAM_FAIL_THRESHOLD: u32 = 3;
const DATAGRAM_RETRY_WINDOW: Duration = Duration::from_secs(3);
const MAX_HEALTH_PEERS: usize = 64;
const CONNECT_TIMEOUT: Duration = Duration::from_secs(12);
const ONLINE_WAIT: Duration = Duration::from_secs(4);
const IDENTITY_FILE: &str = "shifanai-iroh-secret.bin";

type DatagramHandler = Arc<dyn Fn(Vec<u8>, SocketAddr) + Send + Sync + 'static>;
type StreamHandler = Arc<dyn Fn(Vec<u8>, SocketAddr) -> bool + Send + Sync + 'static>;

#[derive(Clone, Debug)]
pub struct PeerEndpoint {
    pub addr: String,
    pub public_key: String,
    pub protocol_version: u16,
}

#[derive(Debug, Clone, Copy)]
struct PeerHealth {
    consecutive_failures: u32,
    last_failure: Instant,
}

type HealthMap = Arc<Mutex<HashMap<String, PeerHealth>>>;

fn health_key(peer: &PeerEndpoint) -> &str {
    if peer.public_key.trim().is_empty() {
        &peer.addr
    } else {
        &peer.public_key
    }
}

fn peer_fast_fail_active(health: &HealthMap, key: &str) -> bool {
    health
        .lock()
        .map(|health| {
            health.get(key).is_some_and(|entry| {
                entry.consecutive_failures >= DATAGRAM_FAIL_THRESHOLD
                    && entry.last_failure.elapsed() < DATAGRAM_RETRY_WINDOW
            })
        })
        .unwrap_or(false)
}

fn record_peer_failure(health: &HealthMap, key: &str, error: &str) {
    let Ok(mut health) = health.lock() else {
        return;
    };
    if health.len() >= MAX_HEALTH_PEERS && !health.contains_key(key) {
        if let Some(stale) = health
            .iter()
            .min_by_key(|(_, entry)| entry.last_failure)
            .map(|(key, _)| key.clone())
        {
            health.remove(&stale);
        }
    }
    let now = Instant::now();
    let entry = health.entry(key.to_string()).or_insert(PeerHealth {
        consecutive_failures: 0,
        last_failure: now,
    });
    entry.consecutive_failures = entry.consecutive_failures.saturating_add(1);
    entry.last_failure = now;
    if entry.consecutive_failures == 1 || entry.consecutive_failures == DATAGRAM_FAIL_THRESHOLD {
        log::warn!("WAN transport to {key} failed: {error}");
    } else {
        log::debug!("WAN transport to {key} still failing: {error}");
    }
}

fn record_peer_success(health: &HealthMap, key: &str) {
    if let Ok(mut health) = health.lock() {
        health.remove(key);
    }
}

#[derive(Clone)]
struct LatestDatagram {
    peer: PeerEndpoint,
    payload: Vec<u8>,
    generation: u64,
    scheduled: bool,
}

type LatestDatagramMap = Arc<Mutex<HashMap<String, LatestDatagram>>>;

#[derive(Clone)]
pub struct TransportHandle {
    commands: tokio_mpsc::UnboundedSender<TransportCommand>,
    port: u16,
    public_key: String,
    peer_health: HealthMap,
    latest_datagrams: LatestDatagramMap,
}

impl TransportHandle {
    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn public_key(&self) -> &str {
        &self.public_key
    }

    pub fn peer(&self, addr: String, public_key: String, protocol_version: u16) -> PeerEndpoint {
        PeerEndpoint {
            addr,
            public_key,
            protocol_version,
        }
    }

    fn validate_datagram(&self, peer: &PeerEndpoint, payload: &[u8]) -> Result<String, String> {
        if payload.len() > MAX_DATAGRAM_BYTES {
            return Err(format!("WAN datagram is too large: {} bytes", payload.len()));
        }
        if peer.protocol_version != PROTOCOL_VERSION {
            return Err(format!(
                "WAN peer protocol mismatch: local={} remote={}",
                PROTOCOL_VERSION, peer.protocol_version
            ));
        }
        let key = health_key(peer).to_string();
        if peer_fast_fail_active(&self.peer_health, &key) {
            return Err(format!("WAN peer {key} is temporarily unreachable"));
        }
        validate_endpoint_id(&peer.public_key)?;
        Ok(key)
    }

    /// Send a control-sensitive datagram without coalescing. Keyboard, buttons,
    /// wheel and protocol control packets use this path so no state transition is
    /// intentionally discarded.
    pub fn send_datagram(&self, peer: PeerEndpoint, payload: Vec<u8>) -> Result<(), String> {
        self.validate_datagram(&peer, &payload)?;
        self.commands
            .send(TransportCommand::SendDatagram { peer, payload })
            .map_err(|_| "WAN transport is stopped".to_string())
    }

    /// Mouse motion is state, not a transaction. If the WAN path stalls for a
    /// moment, replaying every queued historical coordinate creates visible lag
    /// and a "catch-up" cursor. Keep one pending item per peer and replace it with
    /// the newest coordinate while a send is in flight. The receiver therefore
    /// always converges to the current pointer instead of draining stale motion.
    pub fn send_latest_datagram(
        &self,
        peer: PeerEndpoint,
        payload: Vec<u8>,
    ) -> Result<(), String> {
        let key = self.validate_datagram(&peer, &payload)?;
        let should_schedule = {
            let mut latest = self
                .latest_datagrams
                .lock()
                .map_err(|_| "WAN realtime queue is unavailable".to_string())?;
            if let Some(slot) = latest.get_mut(&key) {
                slot.peer = peer;
                slot.payload = payload;
                slot.generation = slot.generation.wrapping_add(1);
                if slot.scheduled {
                    false
                } else {
                    slot.scheduled = true;
                    true
                }
            } else {
                latest.insert(
                    key.clone(),
                    LatestDatagram {
                        peer,
                        payload,
                        generation: 1,
                        scheduled: true,
                    },
                );
                true
            }
        };

        if should_schedule {
            if self
                .commands
                .send(TransportCommand::FlushLatest { key: key.clone() })
                .is_err()
            {
                if let Ok(mut latest) = self.latest_datagrams.lock() {
                    latest.remove(&key);
                }
                return Err("WAN transport is stopped".to_string());
            }
        }
        Ok(())
    }

    pub fn probe(&self, peer: PeerEndpoint) -> Result<(), String> {
        if peer.protocol_version != PROTOCOL_VERSION {
            return Err(format!(
                "WAN peer protocol mismatch: local={} remote={}",
                PROTOCOL_VERSION, peer.protocol_version
            ));
        }
        validate_endpoint_id(&peer.public_key)?;
        let (result_tx, result_rx) = mpsc::channel();
        self.commands
            .send(TransportCommand::Probe { peer, result: result_tx })
            .map_err(|_| "WAN transport is stopped".to_string())?;
        result_rx
            .recv_timeout(Duration::from_secs(20))
            .map_err(|_| "WAN connection probe timed out".to_string())?
    }

    pub fn send_stream_expect_ack(
        &self,
        peer: PeerEndpoint,
        payload: Vec<u8>,
    ) -> Result<(), String> {
        if payload.len() > MAX_STREAM_BYTES {
            return Err(format!("WAN stream payload is too large: {} bytes", payload.len()));
        }
        if peer.protocol_version != PROTOCOL_VERSION {
            return Err(format!(
                "WAN peer protocol mismatch: local={} remote={}",
                PROTOCOL_VERSION, peer.protocol_version
            ));
        }
        let key = health_key(&peer);
        if peer_fast_fail_active(&self.peer_health, key) {
            return Err(format!("WAN peer {key} is temporarily unreachable"));
        }
        validate_endpoint_id(&peer.public_key)?;

        let (result_tx, result_rx) = mpsc::channel();
        self.commands
            .send(TransportCommand::SendStream {
                peer,
                payload,
                result: result_tx,
            })
            .map_err(|_| "WAN transport is stopped".to_string())?;
        result_rx
            .recv_timeout(Duration::from_secs(20))
            .map_err(|_| "WAN stream send timed out".to_string())?
    }

    pub fn shutdown(&self) {
        let _ = self.commands.send(TransportCommand::Shutdown);
    }
}

pub fn validate_endpoint_id(value: &str) -> Result<(), String> {
    EndpointId::from_z32(value.trim())
        .map(|_| ())
        .map_err(|error| format!("invalid WAN endpoint id: {error}"))
}

enum TransportCommand {
    SendDatagram {
        peer: PeerEndpoint,
        payload: Vec<u8>,
    },
    FlushLatest {
        key: String,
    },
    SendStream {
        peer: PeerEndpoint,
        payload: Vec<u8>,
        result: mpsc::Sender<Result<(), String>>,
    },
    Probe {
        peer: PeerEndpoint,
        result: mpsc::Sender<Result<(), String>>,
    },
    Shutdown,
}

type ConnectionMap = Arc<Mutex<HashMap<String, iroh::endpoint::Connection>>>;

pub fn start(
    preferred_port: u16,
    identity_dir: PathBuf,
    on_datagram: DatagramHandler,
    on_stream: StreamHandler,
) -> Result<TransportHandle, String> {
    let secret = load_or_create_secret(&identity_dir)?;
    let (ready_tx, ready_rx) = mpsc::channel();
    let (command_tx, command_rx) = tokio_mpsc::unbounded_channel();
    let peer_health: HealthMap = Arc::new(Mutex::new(HashMap::new()));
    let latest_datagrams: LatestDatagramMap = Arc::new(Mutex::new(HashMap::new()));
    let loop_health = Arc::clone(&peer_health);
    let loop_latest = Arc::clone(&latest_datagrams);

    thread::Builder::new()
        .name("shifanai-wan-transport".into())
        .spawn(move || {
            let runtime = match tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .thread_name("shifanai-wan")
                .worker_threads(2)
                .build()
            {
                Ok(runtime) => runtime,
                Err(error) => {
                    let _ = ready_tx.send(Err(format!("failed to start WAN runtime: {error}")));
                    return;
                }
            };

            runtime.block_on(run_transport(
                preferred_port,
                secret,
                command_rx,
                on_datagram,
                on_stream,
                loop_health,
                loop_latest,
                ready_tx,
            ));
        })
        .map_err(|error| format!("failed to spawn WAN transport thread: {error}"))?;

    let ready = ready_rx
        .recv_timeout(Duration::from_secs(15))
        .map_err(|_| "WAN transport did not become ready".to_string())??;

    Ok(TransportHandle {
        commands: command_tx,
        port: ready.port,
        public_key: ready.public_key,
        peer_health,
        latest_datagrams,
    })
}

struct ReadyTransport {
    port: u16,
    public_key: String,
}

async fn run_transport(
    preferred_port: u16,
    secret: SecretKey,
    mut commands: tokio_mpsc::UnboundedReceiver<TransportCommand>,
    on_datagram: DatagramHandler,
    on_stream: StreamHandler,
    health: HealthMap,
    latest_datagrams: LatestDatagramMap,
    ready_tx: mpsc::Sender<Result<ReadyTransport, String>>,
) {
    let endpoint = match Endpoint::builder(presets::N0)
        .secret_key(secret)
        .alpns(vec![ALPN.to_vec()])
        .bind()
        .await
    {
        Ok(endpoint) => endpoint,
        Err(error) => {
            let _ = ready_tx.send(Err(format!("failed to bind WAN endpoint: {error}")));
            return;
        }
    };

    if tokio::time::timeout(ONLINE_WAIT, endpoint.online()).await.is_err() {
        log::warn!("WAN relay registration did not complete within {}s", ONLINE_WAIT.as_secs());
    }

    let port = endpoint
        .bound_sockets()
        .into_iter()
        .find(|addr| addr.is_ipv4())
        .map(|addr| addr.port())
        .filter(|port| *port != 0)
        .unwrap_or(preferred_port);
    let public_key = endpoint.id().to_z32();
    let _ = ready_tx.send(Ok(ReadyTransport {
        port,
        public_key: public_key.clone(),
    }));
    log::info!("WAN endpoint ready id={public_key} local_port={port}");

    let connections: ConnectionMap = Arc::new(Mutex::new(HashMap::new()));

    loop {
        tokio::select! {
            incoming = endpoint.accept() => {
                let Some(incoming) = incoming else { break; };
                let connections = Arc::clone(&connections);
                let on_datagram = Arc::clone(&on_datagram);
                let on_stream = Arc::clone(&on_stream);
                tokio::spawn(async move {
                    match incoming.await {
                        Ok(connection) => register_connection(connection, connections, on_datagram, on_stream),
                        Err(error) => log::debug!("incoming WAN handshake failed: {error}"),
                    }
                });
            }
            command = commands.recv() => {
                let Some(command) = command else { break; };
                match command {
                    TransportCommand::SendDatagram { peer, payload } => {
                        send_datagram_now(&endpoint, &connections, &health, peer, payload).await;
                    }
                    TransportCommand::FlushLatest { key } => {
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
                    }
                    TransportCommand::Probe { peer, result } => {
                        let key = health_key(&peer).to_string();
                        let outcome = ensure_connection(&endpoint, &connections, &peer).await.map(|_| ());
                        match &outcome {
                            Ok(()) => record_peer_success(&health, &key),
                            Err(error) => record_peer_failure(&health, &key, error),
                        }
                        let _ = result.send(outcome);
                    }
                    TransportCommand::SendStream { peer, payload, result } => {
                        let key = health_key(&peer).to_string();
                        let outcome = async {
                            let connection = ensure_connection(&endpoint, &connections, &peer).await?;
                            let (mut send, mut recv) = connection
                                .open_bi()
                                .await
                                .map_err(|error| format!("failed to open WAN stream: {error}"))?;
                            send.write_all(&payload)
                                .await
                                .map_err(|error| format!("failed to write WAN stream: {error}"))?;
                            send.finish()
                                .map_err(|error| format!("failed to finish WAN stream: {error}"))?;
                            let ack = recv
                                .read_to_end(64)
                                .await
                                .map_err(|error| format!("failed to read WAN stream ack: {error}"))?;
                            if ack == b"ok" {
                                Ok(())
                            } else {
                                Err("WAN peer rejected the stream payload".to_string())
                            }
                        }.await;
                        match &outcome {
                            Ok(()) => record_peer_success(&health, &key),
                            Err(error) => record_peer_failure(&health, &key, error),
                        }
                        let _ = result.send(outcome);
                    }
                    TransportCommand::Shutdown => {
                        endpoint.close().await;
                        break;
                    }
                }
            }
        }
    }
}

async fn send_datagram_now(
    endpoint: &Endpoint,
    connections: &ConnectionMap,
    health: &HealthMap,
    peer: PeerEndpoint,
    payload: Vec<u8>,
) {
    let key = health_key(&peer).to_string();
    match ensure_connection(endpoint, connections, &peer).await {
        Ok(connection) => match connection.send_datagram(payload.into()) {
            Ok(()) => record_peer_success(health, &key),
            Err(error) => record_peer_failure(health, &key, &error.to_string()),
        },
        Err(error) => record_peer_failure(health, &key, &error),
    }
}

async fn ensure_connection(
    endpoint: &Endpoint,
    connections: &ConnectionMap,
    peer: &PeerEndpoint,
) -> Result<iroh::endpoint::Connection, String> {
    let endpoint_id = EndpointId::from_z32(peer.public_key.trim())
        .map_err(|error| format!("invalid WAN endpoint id: {error}"))?;
    let key = endpoint_id.to_z32();
    if let Some(connection) = connections
        .lock()
        .ok()
        .and_then(|connections| connections.get(&key).cloned())
        .filter(|connection| connection.close_reason().is_none())
    {
        return Ok(connection);
    }

    let connection = tokio::time::timeout(CONNECT_TIMEOUT, endpoint.connect(endpoint_id, ALPN))
        .await
        .map_err(|_| format!("WAN connect to {key} timed out"))?
        .map_err(|error| format!("WAN connect to {key} failed: {error}"))?;

    if let Ok(mut map) = connections.lock() {
        map.insert(key.clone(), connection.clone());
    }
    Ok(connection)
}

fn register_connection(
    connection: iroh::endpoint::Connection,
    connections: ConnectionMap,
    on_datagram: DatagramHandler,
    on_stream: StreamHandler,
) {
    let endpoint_id = connection.remote_id();
    let key = endpoint_id.to_z32();
    if let Ok(mut map) = connections.lock() {
        map.insert(key, connection.clone());
    }
    let source = synthetic_source(endpoint_id);

    let datagram_connection = connection.clone();
    let datagram_handler = Arc::clone(&on_datagram);
    tokio::spawn(async move {
        loop {
            match datagram_connection.read_datagram().await {
                Ok(bytes) => datagram_handler(bytes.to_vec(), source),
                Err(_) => break,
            }
        }
    });

    tokio::spawn(async move {
        loop {
            let (mut send, mut recv) = match connection.accept_bi().await {
                Ok(stream) => stream,
                Err(_) => break,
            };
            let handler = Arc::clone(&on_stream);
            tokio::spawn(async move {
                let accepted = match recv.read_to_end(MAX_STREAM_BYTES).await {
                    Ok(payload) => handler(payload, source),
                    Err(error) => {
                        log::warn!("failed reading WAN stream: {error}");
                        false
                    }
                };
                let reply: &[u8] = if accepted { b"ok" } else { b"reject" };
                if let Err(error) = send.write_all(reply).await {
                    log::debug!("failed writing WAN stream ack: {error}");
                }
                let _ = send.finish();
            });
        }
    });
}

fn synthetic_source(endpoint_id: EndpointId) -> SocketAddr {
    let bytes = endpoint_id.as_bytes();
    let port = u16::from_be_bytes([bytes[3], bytes[4]]).max(1024);
    SocketAddr::new(
        IpAddr::V4(Ipv4Addr::new(10, bytes[0], bytes[1], bytes[2])),
        port,
    )
}

fn load_or_create_secret(identity_dir: &Path) -> Result<SecretKey, String> {
    fs::create_dir_all(identity_dir)
        .map_err(|error| format!("failed to create WAN identity directory: {error}"))?;
    let path = identity_dir.join(IDENTITY_FILE);
    if let Ok(bytes) = fs::read(&path) {
        if bytes.len() == 32 {
            let mut raw = [0_u8; 32];
            raw.copy_from_slice(&bytes);
            return Ok(SecretKey::from_bytes(&raw));
        }
        log::warn!("discarding invalid WAN identity file {}", path.display());
    }

    let secret = SecretKey::generate();
    let temp = path.with_extension("tmp");
    fs::write(&temp, secret.to_bytes())
        .map_err(|error| format!("failed to persist WAN identity: {error}"))?;
    fs::rename(&temp, &path)
        .map_err(|error| format!("failed to install WAN identity: {error}"))?;
    Ok(secret)
}
