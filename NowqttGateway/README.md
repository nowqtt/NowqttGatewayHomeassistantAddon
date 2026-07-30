# Serial to MQTT Bridge

## Setup

1. Add this repository to the Home Assistant Add-on Store.
2. Install the **Nowqtt Mash Gateway** add-on.
3. Configure the serial device, MQTT broker address/port, credentials, and timeout options on the add-on Configuration tab.
4. Start the add-on and open `http://<home-assistant-host>:54321/v1/health` to verify MQTT, serial, and worker health.

Home Assistant writes the selected options to `/data/options.json`; the add-on validates them before opening the broker, database, or serial port. For local container development, mount a compatible options file at that path and pass the configured serial device into the container.

## Reliability and health

The gateway uses one bounded serial writer and one shared MQTT connection. Control and command traffic has reserved queue capacity; OTA traffic is prioritized ahead of route tracing. Serial reads and writes have finite deadlines, and the persistent receive buffer can resynchronize on the next valid prefix after a malformed or incomplete frame.

`SIGTERM` and `SIGINT` trigger an ordered shutdown: the gateway stops accepting input, cancels and joins OTA, finishes queued dispatch work, publishes devices offline, stops MQTT, drains serial output, and closes the serial device. Required worker failures make the process unhealthy and stop it so Home Assistant can restart the add-on.

Operational state is available from:

- `GET /v1/health` for MQTT state, worker liveness, serial queue, error, drop, and frame counters
- `GET /v1/ota/status` for the active OTA transfer

Trace polling pauses during OTA and resumes as soon as the transfer ends. `trace_interval_seconds`, `trace_retention_days`, `serial_output_queue_size`, serial timeout values, OTA size, and OTA deadline are configurable in the add-on options. The OTA deadline must cover the configured maximum firmware size at the protocol's packet pacing; the default 4 MiB limit therefore uses a 1,200-second deadline. The SQLite database is stored persistently at `/data/sql_lite_database.db`; an existing legacy database is copied there on first start.

### Additional setups when using Proxmox

#### Pass the serial device to a container

- Figure out which serial device the bridge ESP is with this command: `ls /dev/serial/by-id/`
- Find the major and minor number of this device
  - `ls -l /dev/serial/by-id/<device_id>`
  - Output example: `lrwxrwxrwx 1 root root 13 Mar  3 14:39 /dev/serial/by-id/usb-FTDI_USB-Serial_Converter_FT2GO19S-if00-port0 -> ../../ttyUSB0`
  - Like in this example, the major number is mostly 188 (which corresponds to the ttyUSB driver), and the minor number is 0
  - Figure out if ttyUSB is 188: `grep ttyUSB /proc/devices`. Output: `188 ttyUSB`
- Edit the LXC container configuration file by running the following command: `nano /etc/pve/lxc/<container_id>.conf`
- Add the following lines to the configuration file:
  ```shell
    lxc.mount.entry: /dev/ttyUSB0 dev/ttyUSB0 none bind,optional,create=file
    lxc.cgroup.devices.allow: c <major_number>:<minor_number> rwm
  ```
- Restart the container: `pct restart <container_id>`
- Run `ls /dev/serial/by-id/` in the container to see if the serial device is passed through

#### Set the permissions of the serial device

- Set the permissions non persistent:
  - `chmod 666 /dev/ttyUSB0`
- Set the permissions persistent
  - Find the vendor and product ID of your USB device by running the command: `lsusb`
  - This will list all the USB devices connected to your system. Look for the line that corresponds to your ttyUSB0 device, and note down the vendor and product ID in the format `vendorID:productID`
  - Create a new udev rule file in the `/etc/udev/rules.d/` directory. You can name the file anything you like, but it must end with `.rules`. For example, you can create a file called `99-usb-permissions.rules` by running the command:
  - `nano /etc/udev/rules.d/99-usb-permissions.rules`
  - Add the following line to the file, replacing vendorID and productID: `SUBSYSTEM=="tty", ATTRS{idVendor}=="vendorID", ATTRS{idProduct}=="productID", MODE="0666"`
  - Reload the udev rules by running the command: `sudo udevadm control --reload-rules`

### Notes

- Docker command to get log of headless container: `docker logs -f <container ID>`

## Structure of a message

The serial bridge protocol is binary and length-framed. It does not use newline delimiters.

| Offset | Size | Description |
| --- | --- | --- |
| 0 | 3 bytes | Frame prefix: `FF 13 AB` |
| 3 | 1 byte | Service (`FF` trace, `00` OTA, other values Nowqtt) |
| 4 | 1 byte | Body length from 1 to 255 bytes |
| 5 | body length | Service-specific body |

A regular Nowqtt body starts with an eight-byte header:

| Offset in body | Size | Description |
| --- | --- | --- |
| 0 | 6 bytes | Source ESP MAC address |
| 6 | 1 byte | Command type |
| 7 | 1 byte | Entity ID |
| 8 | remaining bytes | UTF-8 payload |

Trace bodies contain a six-byte destination followed by zero or more 13-byte hops. OTA bodies contain a six-byte source MAC followed by the OTA command payload. Host-to-bridge OTA data uses the `FF 13 AC` prefix variant.

The current bridge protocol does not carry a checksum or sequence number. The host can recover framing after damaged data, but end-to-end corruption detection requires a compatible bridge firmware protocol change.

Commands:
```python
class SerialCommands(Enum):
    RESET = 0
    HEARTBEAT = 1
    CONFIG = 2
    STATE = 3
    COMMAND = 4
    LOG = 6
    ACK = 7
```

## Advertising message

It is recommended to use the [official abbreviations](https://www.home-assistant.io/integrations/mqtt/) for the advertising message

Example client code in C:
```C
const char* mqtt_device_config = ",\"dev\":{\"ids\":\"ESP Test Plug\",\"sa\":\"Mein Zimmer\",\"name\":\"ESP Test Plug Abbreviations\",\"mf\":\"Ich\",\"mdl\":\"ESP32\"}}";
nowqtt_entity_t nowqtt_smart_plug = {"h/switch/nowqtt/test_plug_abbr/c|{\"name\":\"Test Plug Abbreviations\"", true, "OFF", smart_plug_switchHandler};
```

The discovery topic before the `|` separator must match `h/<platform>/<namespace>/<object>/c`. Wildcards, control characters, extra segments, and unsafe namespace/object identifiers are rejected. `unique_id`, `state_topic`, `command_topic`, and gateway/device availability are set by this program.

Different [platforms](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery) (not all are supported yet)

## State and command message

State messages use the binary frame and eight-byte Nowqtt body header described above. MQTT commands are serialized through the same bounded writer and include a terminating zero byte expected by the device-side command parser.
