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

- 3 bytes of fives to mark the beginning of a new message
- 9 bytes header:
  - 6 bytes MAC address of the esp
  - 1 byte to identify the sensor
  - 1 byte command type
  - 1 byte message id
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

Messages look as follows. The 3 fives and 8 header bytes are not displayed

```json
h/<platform>/<node_id>/<object_id>/c|
{
    "n":"<Name>",
    "um":"<unit of measurement>", # optional
    "dc":"<device_class>", # optional
    "mx":"<Number max value>", # optional
    "mn":"<Number min value>", # optional
    "st":"<Number step", # optional
    "md":"<Number mode", # optional
    "o":"<Sensor options>", # optional
    "sc":"<State Class>", # optional
    "d":{
        "i":"<identifiers>",
        "s":"<suggested_area>",
        "n":"<Device Name>",
        "t":"<Timeout in Seconds>"
    }
}
```
Expands to:

```json
homeassistant/<platform>/<node_id>/<unique_id>/config|
{
    "name":"<name>",
    "unique_id":"<unique_id>",
    "state_topic":"homeassistant/<platform>/<node_id>/<unique_id>/state",
    "command_topic":"homeassistant/<platform>/<node_id>/<unique_id>/com",
    "unit_of_measurement":"<unit of measurement>", # optional
    "device_class":"<device_class>", # optional
    "max":"<Number max value>", # optional
    "min":"<Number min value>", # optional
    "step":"<Number step", # optional
    "mode":"<Number mode", # optional
    "options":"<Sensor options>", # optional
    "state_class":"<State Class>", # optional
    "device":{
        "identifiers":"ESP32 <identifiers>",
        "suggested_area":"<suggested_area>",
        "manufacturer":"Ich",
        "model":"ESP32",
        "name":"<device name>",
        "timeout_in_seconds": "<Timeout in Seconds>"
    }
}
```
[platforms](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery) 

Example input:

```json
h/switch/on_off/irRemote_myRoom_soundSystem/c|
{
   "n":"ESP SoundSystem MyRoom",
   "d":{
      "i":"SoundSystem MyRoom",
      "s":"Mein Zimmer",
      "n":"ESP SoundSystem MyRoom"
   }
}
```

Example output:
```json
/switch/on_off/irRemote_myRoom_soundSystem/config|
{
   "name":"ESP SoundSystem MyRoom",
   "unique_id":"irRemote_myRoom_soundSystem",
   "state_topic":"homeassistant/switch/on_off/irRemote_myRoom_soundSystem/state",
   "command_topic":"homeassistant/switch/on_off/irRemote_myRoom_soundSystem/com",
   "device":{
      "identifiers":"ESP8266 SoundSystem MyRoom",
      "suggested_area":"Mein Zimmer",
      "manufacturer":"Ich",
      "model":"ESP8266",
      "name":"ESP SoundSystem MyRoom"
   }
}
```

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