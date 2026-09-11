# NowQTT Mesh Performance and Resilience Report

## Scope and constraints

This report follows the complete message path:

1. ESP32 application (`mowqtt-example/main`)
2. NowQTT utility layer (`mowqtt-example/submodules/nowqtt-util`)
3. ESP-NOW AODV mesh (`mowqtt-example/submodules/espnow-aodv`)
4. Gateway firmware (`nowqtt-gw/main`)
5. UART bridge
6. Python gateway (`NowqttGateway/src`)
7. MQTT and Home Assistant

Only the checked-out code in `mowqtt-example/submodules` was analyzed. No submodules were fetched.

The recommendations preserve user-visible behavior. Steps that require an internal wire-format change are explicitly marked as coordinated protocol changes and should be deployed with backward compatibility or as one coordinated firmware/gateway release.

## Executive findings

The largest causes of variable latency and message loss are not raw ESP-NOW throughput. They are reliability and backpressure gaps between otherwise independent stages:

- A QoS send can block its caller for about 2 seconds in gateway firmware and about 7 seconds in a normal node, but it returns no success/failure result.
- ACKs are identified only by service, not by message or destination. Concurrent QoS traffic on one service can acknowledge the wrong send.
- QoS retries call the receiving application repeatedly because there is no message ID or duplicate suppression.
- A packet with no route is discarded. Route discovery begins only after two QoS timeouts; non-QoS traffic never starts discovery.
- ESP-NOW local send completion is not observed. Successful queueing to the Wi-Fi task is treated like successful delivery.
- Queue-full, UART-full, and OTA-buffer-full conditions generally drop data silently.
- The UART protocol has no CRC, sequence number, acknowledgement, or robust resynchronization rule.
- Python has several concurrent UART writers and no single-writer queue.
- The single Python UART reader performs database work and can wait indefinitely for new MQTT clients to connect, allowing the UART receive buffer to fill.
- The default UART rates disagree: gateway firmware uses 230400 while the add-on configuration defaults to 115200.
- One MQTT client and thread is created per Home Assistant entity, multiplying connections, threads, reconnect work, and failure points.
- OTA has deterministic edge-case failures and does not apply backpressure.

The safest order is: measure first, close silent-loss and contract gaps, isolate blocking work, then improve the mesh protocol.

## Step 0: Establish a baseline without changing behavior

Implement this step first. Otherwise, improvements cannot be distinguished from changes in RF conditions.

### 0.1 Add counters at every loss boundary

Record monotonically increasing counters, high-water marks, and last-error codes for:

- AODV event queue full
- NowQTT node queue full
- allocation failure
- route not found
- ESP-NOW immediate send error by error code
- ESP-NOW asynchronous send success/failure
- QoS ACK timeout and final retry exhaustion
- malformed or truncated radio packet
- gateway UART TX space rejection
- Python UART framing/length/decode error
- serial write exception or short write
- OTA message-buffer full
- MQTT publish result and disconnect reason
- SQLite busy/locked/error result

Evidence:

- `espnow-aodv/src/aodv_task.c`, `send_to_queue()` frees a rejected item but does not count or report it.
- `nowqtt-util/src/nowqtt_common.c`, `put_in_send_queue()` and `putInQueue()` silently discard on a full 50-entry queue.
- `nowqtt-gw/main/app_main.c`, `data_cb()` discards when UART free space is below a threshold.
- `espnow-ota/src/aodv_ota.c`, `process_ota_msg()` ignores the result of `xMessageBufferSend(..., 0)`.
- Python MQTT publishes do not inspect `MQTTMessageInfo.rc` or wait for publication where delivery matters.

Keep counters in memory and expose them through a low-rate diagnostic message. Do not log every packet in normal operation; high-volume logging can itself create latency.

### 0.2 Add end-to-end timing at existing boundaries

Before changing the packet format, measure timestamps locally:

- enqueue-to-dequeue time in the node NowQTT queue
- enqueue-to-dequeue time in the AODV event queue
- QoS wait duration and retry count
- UART frame read duration
- Python parse-to-MQTT-publish duration
- MQTT reconnect duration
- trace database insertion duration

Report p50, p95, p99, maximum, and sample count. Averages alone hide retry stalls.

### 0.3 Create repeatable load and failure tests

Use a test matrix rather than testing only normal operation:

- 1, 5, 10, and maximum expected nodes
- 1, 2, and 4 hops
- simultaneous state, command, heartbeat, trace, and OTA traffic
- gateway restart, leaf restart, intermediate-node loss, broker restart, serial disconnect, and RF interference
- bursts above expected peak rate
- two concurrent QoS sends on service 1
- route loss immediately before a send

For each test, record attempted, accepted, delivered, duplicate, malformed, and timed-out messages plus end-to-end latency percentiles.

## Step 1: Close immediate contract and silent-failure gaps

These changes are small and preserve the current protocol and external behavior.

### 1.1 Make the UART configuration identical on both ends

Confirmed mismatch:

- `nowqtt-gw/main/app_main.c`, `uart_initialize(230400)`
- `NowqttGateway/config.yaml`, default `baudrate: 115200`

Verify the deployed Home Assistant option, then define the baud rate once in deployment configuration or make both defaults identical. Also verify data bits, parity, stop bits, and flow control. A mismatch here dominates every higher-level reliability measure.

### 1.2 Serialize all Python UART writes

Confirmed concurrent writers include:

- MQTT command callbacks in `gateway/mqtt_task.py`
- trace requests in `gateway/trace_route_task.py`
- network reset in `gateway/mqtt_metadata_device_task.py`
- config requests in `gateway/serial_task.py`
- OTA threads in `ota/aodv_ota_updater.py`

All write through the same `serial.Serial` object, but there is no shared lock or writer queue. Route every outgoing frame into one bounded queue consumed by one serial-writer thread. A lock around each complete frame is an acceptable first fix; a queue is better because it also provides ordering, depth metrics, priorities, and backpressure.

Define overload policy explicitly. Commands and reset/OTA control should not be silently displaced by trace requests. A practical priority order is control/ACK, commands, state/config, OTA data, then diagnostics.

### 1.3 Harden UART reads and resynchronization

`gateway/serial_task.py` assumes every `read(n)` returns all requested bytes and trusts a one-byte length. `nowqtt-gw/main/app_main.c` similarly trusts the service and length after finding the prefix.

Improvements:

- Implement `read_exact(n, deadline)` and reject partial frames.
- Validate minimum and maximum lengths before subtracting header sizes.
- Validate service IDs before indexing arrays.
- On an invalid frame, scan with an overlap-aware prefix matcher. The current reset-to-zero matcher can miss an overlapping `FF 13 AB` prefix.
- Do not decode payload with `errors='ignore'`; that hides corruption. Reject invalid UTF-8 for text message types and retain raw bytes for diagnostics.
- Add a bounded serial timeout and reconnect/resync state machine instead of either blocking forever or allowing a timeout exception to terminate the main loop.

The current Python `TimeoutError` branches are normally unreachable because `serial.Serial` is opened without a timeout. They become process-ending failures if a timeout is later configured.

### 1.4 Correct firmware bounds checks before indexing or casting

Confirmed cases:

- `nowqtt-gw/main/app_main.c` uses `if(service > MAX_SERVICE_COUNT)`; `service == MAX_SERVICE_COUNT` still indexes beyond `nowqtt_aodv_h`.
- `espnow-aodv/src/aodv_task.c`, `process_rx_msg()` accepts a one-byte packet and then reads a destination MAC or casts a full forwarding header.
- Peering and routing handlers cast input to structs without first checking the exact minimum size.
- `espnow-ota/src/aodv_ota.c`, `process_ota_msg()` reads `buff[0]` without checking `size > 0`.

Reject malformed packets before any `memcmp`, struct cast, or array access. This prevents corrupted radio data from causing out-of-bounds reads and unpredictable routing behavior.

### 1.5 Stop treating enqueue as delivery

Register the ESP-NOW send callback and track the result per next-hop transmission. `esp_now_send()` returning `ESP_OK` means the frame was accepted for transmission, not that it reached the peer.

For this protocol-compatible step:

- Count callback success/failure by peer.
- Mark or remove a route after a configurable run of confirmed next-hop failures, not only when immediate send returns `ESP_ERR_ESPNOW_NOT_FOUND`.
- Trigger route rediscovery after confirmed link failure.
- Avoid deleting a route on one transient failure.

### 1.6 Return or expose failure status

`aodv_send()` returns `void`, and queue helpers also hide rejection. Callers cannot distinguish delivered, queued, queue-full, no-route, or retry-exhausted states.

Without changing existing callers, add a parallel result callback or status API. Later, migrate internal callers to use it. At minimum, final QoS exhaustion must be visible in metrics.

### 1.7 Make SQLite use safe transaction and concurrency boundaries

One connection is shared across serial, availability, and web threads with `check_same_thread=False`. There is no database lock, and several update/insert/delete functions neither use a transaction context nor call `commit()`.

Use one of these conservative patterns:

- one connection per thread with short transactions and WAL mode, or
- one database worker queue owning one connection.

Also parameterize all SQL values. Several device-name, activity, filter, and limit queries interpolate strings directly. Besides security, quotes in a legitimate device name can fail a transaction and leave metadata stale.

### 1.8 Remove misleading or ineffective tuning controls

- `aodv_register_service(..., buffer_size, ...)` ignores `buffer_size`.
- `CONFIG_AODV_RX_BUFFER_SIZE` is declared but not used.
- `aodv_trace(handle, ...)` accepts a handle but does not use it.
- `aodv_ota_init(service_ID)` ignores `service_ID` and always registers service 0.

Either implement these controls or remove/deprecate them. At present they give operators false confidence that buffering and service allocation are configurable.

## Step 2: Remove avoidable latency and backpressure amplification

These are internal implementation changes that keep message semantics intact.

### 2.1 Keep the Python UART reader dedicated to reading

The sole UART reader currently performs parsing, SQLite inserts, device-tree mutation, MQTT-client creation, and MQTT publishing. Most importantly, `create_mqtt_client()` waits without a timeout until a new client reports connected. A slow or unavailable broker therefore stops serial consumption indefinitely.

Change the reader to:

1. read and validate a complete frame
2. timestamp it
3. place it on a bounded processing queue
4. immediately resume reading

Use separate workers for database/trace processing and MQTT/device processing. Define queue limits and overload behavior. State coalescing is safe only for entities where only the newest state matters; commands and config must retain ordering.

### 2.2 Replace per-entity MQTT clients with one gateway client

`gateway/nowqtt_device_tree.py` creates a new Paho client and daemon thread for every entity, plus another client for every device's hop-count entity and one metadata client.

Costs grow linearly with entity count:

- TCP connections and broker sessions
- threads and stacks
- keepalive traffic
- reconnect storms
- subscription and callback management
- time spent waiting for each connection during serial processing

Use one long-lived MQTT client for the gateway and dispatch topics to entities in memory. Preserve existing topic names, payloads, availability, and discovery messages. This is a major performance improvement without changing Home Assistant-visible functionality.

### 2.3 Decouple MQTT callbacks from UART I/O

Paho invokes `on_message()` on its network-loop thread. It currently writes to serial synchronously. Enqueue the command to the serial writer and return immediately so serial stalls cannot delay keepalive and MQTT receive processing.

Replace recursive MQTT connection retries with an iterative state machine and bounded exponential backoff with jitter. Recursive retries can grow the Python stack indefinitely during a long broker outage.

### 2.4 Make queues bounded, observable, and intentionally sized

Current queues are bounded but drops are silent:

- AODV event queue: 128 entries
- node NowQTT queue: 50 entries
- gateway UART RX/TX buffers: 2048 bytes
- OTA message buffer: 2048 bytes, enough for only about eight full messages after message-buffer overhead

Do not simply enlarge every queue. First measure high-water marks and service time. Larger queues can turn drops into seconds of stale latency. Use separate control and bulk queues where a large OTA or trace workload can otherwise delay commands and ACKs.

### 2.5 Reduce gateway UART copies and false drops

`nowqtt-gw/main/app_main.c`, `data_cb()` checks free TX space against `sizeof(cdc_msg)` even when the actual frame is much smaller. This can drop a short heartbeat or state frame despite sufficient room for that frame.

Compute the exact encoded frame size, build the complete frame once, and submit it in one UART write. Check the returned byte count. This reduces lock/copy overhead and makes each frame an atomic unit at the application level.

### 2.6 Keep diagnostics from becoming production traffic

The trace thread sends one mesh trace per known device, one second apart, then repeats after 30 seconds. This scales linearly with device count, consumes UART and mesh airtime, writes multiple database rows per trace, and refreshes route ages as a side effect.

Improvements:

- make the interval and maximum traces per cycle configurable
- pause or reduce tracing during OTA or congestion
- add jitter to avoid synchronization with heartbeats and maintenance
- batch trace database inserts into one transaction
- skip trace work when no consumer needs fresh topology data

Tracing should be the first traffic class dropped under load, never commands or ACKs.

### 2.7 Align peer and route lifetimes

With the defaults, maintenance runs every 20 seconds. Because deletion uses `age > threshold`, peers can remain for about 80 seconds and routes for about 140 seconds. A route can therefore point to a deleted ESP-NOW peer for roughly one minute.

Expire dependent routes when a peer is removed. Tune timeouts only after measuring mobility and packet rates. Merely shortening both timers can increase route-discovery floods and make latency worse.

## Step 3: Repair end-to-end mesh reliability

This step changes internal mesh packet semantics and should be deployed as a coordinated, versioned protocol update. Home Assistant-visible behavior can remain unchanged.

### 3.1 Replace the service-wide ACK semaphore with per-message identity

Current design:

- one binary semaphore per service
- no message ID in `forward_msg_header_t`
- any ACK on that service releases the current waiter
- only one pending ACK can be represented
- no destination validation

Failure examples:

- Two tasks send QoS messages on service 1. ACK for node A releases the send waiting for node B.
- A late ACK from an earlier retry releases a later, unrelated send.
- Multiple ACKs collapse into one binary semaphore state.

Add a source-scoped sequence/message ID to DATA_QOS and DATA_ACK. Track pending sends by `(destination, service, message_id)` and match ACKs exactly. Serialize or bound the number of outstanding messages per destination.

### 3.2 Suppress duplicate application delivery

The receiver calls the service callback before sending the ACK. If the ACK is lost, every retransmission invokes the callback again. This can repeat commands and publish duplicate state/config/log messages.

Maintain a small per-source cache of recently completed message IDs. For a duplicate QoS frame, resend the ACK but do not invoke the application callback again. Size and expire this cache based on maximum retry duration and traffic rate.

### 3.3 Discover a route before consuming retry attempts

`forward_message()` drops a packet when no route exists. For QoS traffic, route discovery is queued only after the second timeout. Queue ordering means additional data attempts can be processed before the route request. Non-QoS traffic never requests a route.

Use an explicit per-destination state:

- route ready: transmit
- route unknown/discovering: retain a small bounded pending set and send one RREQ
- discovery succeeded: release pending messages
- discovery timed out: report failure

Coalesce simultaneous route requests for the same destination. Do not flood one RREQ per waiting message.

### 3.4 Make retransmission adaptive and non-blocking

Normal nodes use 10 attempts with exponentially increasing waits capped at 1 second, totaling roughly 7 seconds in the worst case. Gateway firmware uses 5 attempts, roughly 2 seconds. `aodv_send()` blocks the calling task for this entire period.

Move retries into the AODV task or a timer-driven pending-send manager. Learn smoothed RTT per destination/hop count and set timeout from observed RTT plus variance. Keep jitter. Return completion asynchronously so one poor route does not block unrelated NowQTT processing.

### 3.5 Add hop limit and duplicate control to forwarded data

Forwarded data has no hop limit. A transient routing loop can circulate until routes age out, consuming airtime and queue capacity.

Add:

- hop limit/TTL
- source and message ID
- duplicate cache at forwarders
- drop counters for TTL and duplicate events

### 3.6 Improve route discovery identity and storm control

RREQ duplicate detection uses only a random 32-bit broadcast ID and remembers ten IDs globally. The immediate collision probability is low, but identity is incomplete and a busy network can evict an ID quickly, allowing a delayed duplicate to flood again.

Identify RREQs by `(originator MAC, broadcast ID)`, retain them for a measured time window, add an RREQ hop limit, rate-limit per originator/destination, and jitter forwarding. Coalesce route discovery as described above.

### 3.7 Select routes using link quality, not only sequence and hop count

RSSI is available on receive but peering uses it only as a one-time threshold. Routes then prefer freshness and hop count, even if a slightly longer path is much more reliable.

Track per-peer:

- EWMA RSSI
- next-hop send success ratio
- ACK RTT and timeout ratio
- consecutive failures

Use a stable cost with hysteresis to prevent route flapping. Do not route directly from instantaneous RSSI.

### 3.8 Revisit peer topology limits

Encrypted ESP-NOW peer capacity is finite. `process_PREP()` stops accepting responses at half of `ESP_NOW_MAX_ENCRYPT_PEER_NUM`, while incoming PREQ processing can fill the full table. This asymmetric policy makes topology dependent on discovery direction and timing.

Define a deliberate maximum neighbor count and replacement policy based on quality and route use. Pin active next hops, evict stale/poor unused peers, and ensure route entries are invalidated on eviction.

## Step 4: Make OTA safe and isolate it from normal traffic

OTA is bulk traffic and currently competes with control/state traffic without end-to-end flow control.

### 4.1 Fix deterministic packet-count and final-packet errors

Confirmed issues:

- Python sends `floor(size / 232) + 1` packets. If size is exactly divisible by 232, it sends one extra empty packet.
- Embedded code computes `ceil(size / 232)` and aborts when that extra packet number equals `packet_count`.
- Embedded code always writes 232 payload bytes, even for the final short packet.
- `esp_ota_write_with_offset()` and `esp_ota_set_boot_partition()` return values are ignored.

Use exactly `ceil(size / payload_size)` packets and derive the expected final payload length from total size and packet number. Validate received frame length before writing and check every OTA API result.

### 4.2 Apply OTA backpressure

Python transmits every 50 ms regardless of mesh depth, retry rate, UART occupancy, or the device's flash-write speed. The device has an approximately eight-packet OTA message buffer and silently drops when full.

Introduce a bounded sliding window:

- sender transmits up to N packets
- receiver acknowledges ranges or a bitmap
- sender advances only as capacity is confirmed
- missing packets are selectively retransmitted

Until a protocol update is available, lower the sending rate based on measured worst-case multi-hop throughput and stop/pause when overflow counters increase.

### 4.3 Add chunk and image integrity checks

ESP-NOW link checks do not replace end-to-end validation across UART parsing, memory, routing, and retransmission.

Add CRC32 per OTA chunk and verify a whole-image SHA-256 before selecting the boot partition. Keep ESP-IDF image validation and rollback enabled. Reject wrong-size, duplicate-conflicting, and out-of-range chunks without aborting a valid session unnecessarily.

### 4.4 Fix OTA concurrency and lifecycle

`global_vars.ota_queue` and each manager's retransmit list are accessed by multiple threads without synchronization. Retransmit listeners are repeatedly created as daemon threads. Packet-number parsing reads only three of four encoded bytes.

Use one OTA session object per destination with a lock/event, one lifecycle thread or task, a bounded retransmit set, and explicit cancel/failure/complete states. Prevent concurrent OTA sessions from saturating the shared UART and mesh unless bandwidth allocation is implemented.

## Step 5: Larger architectural improvements

These provide the greatest long-term gains while preserving MQTT topics and Home Assistant behavior.

### 5.1 Use a staged gateway pipeline with explicit ownership

Recommended internal pipeline:

`serial reader -> validated inbound queue -> dispatcher -> device/MQTT worker`

`MQTT callbacks / OTA / diagnostics -> prioritized outbound queue -> serial writer`

`trace/device events -> database queue -> database owner`

Each resource has one owner:

- one serial reader
- one serial writer
- one MQTT client/network loop
- one database writer

Queues provide bounded buffering, metrics, and clear overload policy. This removes most shared-state locks and prevents a slow broker or database from blocking UART intake.

### 5.2 Add a versioned UART envelope

The current envelope is only prefix, service, one-byte length, destination/source, and payload. It cannot detect loss, duplication, corruption, or incompatible versions.

A versioned envelope should include:

- sync marker with robust framing (COBS or SLIP are suitable)
- protocol version
- message type/service
- payload length
- monotonically increasing sequence number
- CRC32
- optional ACK/NACK for commands and control traffic

COBS plus delimiter gives deterministic resynchronization after corruption. During migration, the Python gateway can recognize both old and new prefixes, and firmware can negotiate or be configured for the old format.

### 5.3 Separate reliability classes

Not all traffic needs identical behavior:

- commands, reset, OTA control: acknowledged, ordered, deduplicated
- config/discovery: acknowledged and deduplicated, can be retried slowly
- state: latest-value delivery, may be coalesced under load
- heartbeat: replaceable by a newer heartbeat
- trace/log: best effort and lowest priority
- OTA data: bulk sliding-window transfer

The current boolean QoS flag cannot express these needs. Internal traffic classes improve both latency and resilience without changing payload meaning.

### 5.4 Add store-and-forward only where freshness permits

For temporary broker or serial outages, a small persistent queue can retain commands/config and selected state. Define TTL and maximum storage by message class so stale sensor values or commands are not replayed unexpectedly.

Do not persist every trace, heartbeat, or intermediate state. That would increase recovery latency and flash wear.

### 5.5 Introduce protocol compatibility tests

Maintain golden byte vectors for:

- C-to-Python UART frames
- Python-to-C UART frames
- every AODV message type
- minimum/maximum payloads
- exact-multiple and short-final OTA images
- malformed lengths, unknown services, duplicate IDs, and CRC failures

Run host-side parser tests on every change and embedded unit tests under ESP-IDF where possible. Add fuzz tests for both UART parsers and radio message dispatch because both currently cast untrusted lengths directly into structs.

## Boundary gaps that can lead to failure

### Node application to NowQTT utility

- Queue rejection is invisible to the application.
- All sends share one queue; a long synchronous QoS send blocks receive processing and later sends in `nowqtt_task`.
- Heartbeat timer enqueue failure is ignored.
- Configuration bursts at startup have no completion feedback.

### NowQTT utility to AODV

- `aodv_send()` has no result.
- QoS blocks the caller and ACK identity is only the service.
- No-route handling drops the current packet.
- Retry delivery is not idempotent.

### AODV routing to ESP-NOW

- Immediate API success is treated as delivery; asynchronous send status is unused.
- Route entries outlive removed peers.
- No data TTL or duplicate ID exists.
- Peer capacity and admission policy are asymmetric.
- Malformed frame lengths are insufficiently validated.

### Mesh to gateway firmware

- Gateway UART drops are not reported back to the mesh sender. The mesh ACK can already have been sent before UART acceptance, so end-to-end success is false.
- One-byte UART length and no CRC make corruption indistinguishable from valid data.
- Gateway firmware offers no host-side flow-control signal.

### Gateway firmware to Python

- Default baud rates disagree.
- Neither side confirms complete frame acceptance.
- Python has concurrent writers and weak resynchronization.
- Partial reads and invalid lengths are not handled safely.
- There is no boot/session identifier, so sequence continuity after either side restarts cannot be inferred.

### Python dispatcher to MQTT/Home Assistant

- Serial consumption can block on MQTT connection establishment.
- One client/thread per entity amplifies broker outages.
- State/config publishes use QoS 0 and publish results are ignored.
- Availability uses QoS 1, but gateway-to-node command delivery has no matching end-to-end confirmation.
- A Home Assistant command can be accepted by MQTT while being lost in UART, routing, or at the node with no failure surfaced.

### Python dispatcher to SQLite/web

- One SQLite connection is shared across threads without serialization.
- Some writes are not explicitly committed.
- Trace inserts perform many small transactions in the serial reader.
- Dynamic SQL can fail on ordinary quoted values and permits injection from web/device-controlled fields.

## Prioritized implementation sequence

1. Add counters, timing, queue high-water marks, and a repeatable load test.
2. Verify and unify UART baud/configuration.
3. Add one Python serial writer and robust `read_exact`/frame bounds handling.
4. Validate all embedded message lengths and service indexes.
5. Register ESP-NOW send callbacks and expose all current silent failures.
6. Move Python serial parsing off database/MQTT connection work.
7. Give SQLite one owner or per-thread connections with WAL and proper transactions.
8. Batch/rate-limit trace work and keep diagnostics lowest priority.
9. Replace per-entity MQTT clients with one gateway client.
10. Align route cleanup with peer deletion and use confirmed link failures.
11. Introduce versioned per-message IDs, exact ACK matching, and duplicate suppression.
12. Make route discovery a stateful prerequisite instead of consuming retries on missing routes.
13. Move QoS retries to an asynchronous pending-send manager with adaptive RTT.
14. Fix OTA packet boundaries immediately, then add flow control and integrity verification.
15. Migrate UART to a versioned, checksummed, sequence-aware envelope.

## Changes to avoid

- Do not enable QoS for every message with the current implementation. It increases blocking and duplicate delivery and still cannot correlate ACKs.
- Do not only enlarge queues. This can hide overload while increasing stale-message latency.
- Do not only shorten route/peer timeouts. This can create RREQ storms and route flapping.
- Do not add verbose per-packet INFO logging in production.
- Do not add more Python locks around long operations. Prefer single-owner workers and short queue operations.
- Do not increase OTA send rate until receiver backpressure exists.

## Expected outcome by stage

After Steps 0-1, failures become measurable, malformed traffic is contained, UART writes stop racing, and configuration errors no longer masquerade as RF loss.

After Step 2, serial intake remains responsive during broker/database delays, routine command latency becomes predictable, and entity count no longer multiplies MQTT connections and threads.

After Step 3, QoS represents the correct message and destination, retries no longer repeat application actions, stale routes recover promptly, and one bad destination no longer stalls unrelated traffic.

After Step 4, OTA no longer aborts on exact packet boundaries, corrupt/short chunks are rejected, and bulk transfer cannot silently overrun the receiver.

After Step 5, every transport boundary has framing, ownership, backpressure, and observable delivery semantics while existing MQTT topics and Home Assistant functionality remain intact.