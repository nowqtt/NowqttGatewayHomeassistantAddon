# Serial to MQTT Bridge

## Setup
- Edit the `config.default.yaml` file
- Remove ".default" from the file name
- In the root folder run:
  - `docker-compose build`
  - `docker-compose up`

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

Messages contain the following components in this order 

- 3 Bytes of fives to mark the beginning of a new message
- 1 Byte message length
- 8 Bytes header:
  - 6 Bytes MAC address of the esp
  - 1 Byte command type
  - 1 Byte to identify the sensor
- The rest up to a new line is the message

Commands:
```python
class SerialCommands(Enum):
    RESET = 0
    HEARTBEAT = 1
    CONFIG = 2
    STATE = 3
    COMMAND = 4
    INFLUX = 5
    LOG = 6
    ACK = 7
```

Example (without spaces):

```text
0x05 0x05 0x05 0x1e 0x1e 0x1e 0x1e 0x1e 0x1e 0x01 0x03 0x15 h/switch/on_off/testdevice1/c|{\"n\": \"testdevice1\", \"d\": {\"i\": \"testdevice1\", \"s\": \"Mein Zimmer\" ,\"n\": \"testdevice1\"}}
```

## Advertising message

It is recommended to use the [official abbreviations](https://www.home-assistant.io/integrations/mqtt/) for the advertising message 

Example client code in C:
```C
const char* mqtt_device_config = ",\"dev\":{\"ids\":\"ESP Test Plug\",\"sa\":\"Mein Zimmer\",\"name\":\"ESP Test Plug Abbreviations\",\"mf\":\"Ich\",\"mdl\":\"ESP32\"}}";
nowqtt_entity_t nowqtt_smart_plug = {"h/switch/nowqtt/test_plug_abbr/c|{\"name\":\"Test Plug Abbreviations\"", true, "OFF", smart_plug_switchHandler};
```

`unique_id`, `state_topic`, `command_topic` and `availability_topic` will be set by this program.

Different [platforms](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery) (not all are supported yet)

## State and command message

Both messages start with 3 fives and 8 header bytes. The message follows immediately after these bytes.

## Influx

The message starts with 3 fives and 8 header bytes. The command type has to be set to INFLUX.

```json
{
  "o": "<Name of Organisation",
  "b": "<Name of Bucket",
  "mn": "<Name of Message (Name of the datapoint)>",
  "items": {
    "key1": "<val1>",
    "key2": "<val2>",
    ...
  }
}
```