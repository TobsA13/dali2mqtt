
# dali2mqtt
DALI <-> MQTT bridge
# <ins>This is a fork of [dali2mqtt](https://github.com/dgomes/dali2mqtt) from [dgomes.](https://github.com/dgomes) </ins>



## About

This daemon is inspired in [zigbee2mqtt](https://github.com/Koenkk/zigbee2mqtt) and provides the means to integrate a DALI light controller into your Home Assistant setup.

## Supported Devices

This daemon relies in [python-dali](https://github.com/sde1000/python-dali) so all devices supported by this library should also be supported by dali2mqtt.

## How to use

### Create a Virtual Environment (recommended) and install the requirements
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Create a configuration file
You can create a configuration file when you call the daemon the first time

```bash
venv/bin/python3 ./main.py
```

Then just edit the file accordingly. You can also create the file with the right values, by using the arguments of dali_mqtt_daemon.py:

```
  --config CONFIG       configuration file
  --devices-names DEVICES_NAMES
                        devices names file
  --mqtt-server MQTT_SERVER
                        MQTT server
  --mqtt-port MQTT_PORT
                        MQTT port
  --mqtt-username MQTT_USERNAME
                        MQTT username
  --mqtt-password MQTT_PASSWORD
                        MQTT password
  --mqtt-base-topic MQTT_BASE_TOPIC
                        MQTT base topic
  --dali-driver {hasseb,tridonic,dali_server}
                        DALI device driver
  --dali-lamps DALI_LAMPS
                        Number of lamps to scan                        
  --ha-discovery-prefix HA_DISCOVERY_PREFIX
                        HA discovery mqtt prefix
  --log-level {critical,error,warning,info,debug}
                        Log level
  --log-color           Coloring output
  
  --group-mode {mean,max,min,off}
                        How the light level of a group is set when the level some lamps of the is changed   

```

### Devices friendly names
Default all lamps will be displayed in Home Assistant by short address, numbers from 0 to 63
You can give lamps special names to help you identify lamps by name. On the first execution, `devices.yaml` file will be create with all lamps available.
Example `devices.yaml`:
```yaml
0: 
  "friendly_name": "Lamp in kitchen"
8:
  "friendly_name": "Lamp in bathroom"
```
Please note that MQTT topics support a minimum set of characters, therefore friendly names are converted to slug strings, so a lamp with address 0 (as an example) in MQTT will be named "lamp-in-kitchen"

### Setup systemd
edit dali2mqtt.service and change the path of python3 to the path of your venv, after:

```bash
sudo cp dali2mqtt.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dali2mqtt.service 
```

### Give your user permissions to access the USB device
```bash
sudo adduser homeassistant plugdev 
cp 50-hasseb.rules /etc/udev/rules.d/
```
You might need to reboot your device after the last change.

In this example the user is **homeassistant**

### Check everything is OK
```bash
sudo systemctl start dali2mqtt.service 
sudo systemctl status dali2mqtt.service 
```

### Command line arguments and configuration file

When the daemon first runs, it creates a default `config.yaml` file.
You can edit the file to customize your setup.
