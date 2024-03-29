#!/usr/bin/env python3
"""Bridge between a DALI controller and an MQTT bus."""
import json
import traceback

import paho.mqtt.client as mqtt
import dali.address as address
import dali.gear.general as gear
from dali.command import YesNoResponse
from dali.exceptions import DALIError
from slugify import slugify

from .config import Config
from .group import Group
from .lamp import Lamp
from .devicesnamesconfig import DevicesNamesConfig

from .consts import *

logging.basicConfig(format=LOG_FORMAT)
logger = logging.getLogger(__name__)


def scan_lamps(driver):
    """Scan a maximum number of dali devices."""
    lamps = []
    config = Config()
    for lamp in range(0, 64):
        try:
            logger.debug("Search for Lamp %s", lamp)
            present = driver.send(gear.QueryControlGearPresent(address.Short(lamp)))
            if isinstance(present, YesNoResponse) and present.value:
                lamps.append(lamp)
                logger.debug("Found lamp at address %d", lamp)
                if len(lamps) >= config[CONF_DALI_LAMPS]:
                    logger.warning("All %s configured lamps have been found, Stopping scan", config[CONF_DALI_LAMPS])
                    logger.info("Found %d lamps", len(lamps))
                    return lamps
        except DALIError as err:
            logger.warning("%s not present: %s", lamp, err)

    logger.info("Found %d lamps", len(lamps))
    return lamps


def scan_groups(dali_driver, lamps):
    logger.info("Scanning for groups:")
    groups = {}
    for lamp in lamps:
        try:
            logger.debug("Search for groups for Lamp {}".format(lamp))
            group1 = dali_driver.send(gear.QueryGroupsZeroToSeven(address.Short(lamp))).value.as_integer
            group2 = dali_driver.send(gear.QueryGroupsEightToFifteen(address.Short(lamp))).value.as_integer

            lamp_groups = []

            for i in range(8):
                checkgroup = 1 << i
                logger.debug("Check pattern: %d", checkgroup)
                if (group1 & checkgroup) == checkgroup:
                    if not i in groups:
                        groups[i] = []
                    groups[i].append(lamp)
                    lamp_groups.append(i)
                if (group2 & checkgroup) != 0:
                    if not i + 8 in groups:
                        groups[i + 8] = []
                    groups[i + 8].append(lamp)
                    lamp_groups.append(i + 8)

            logger.debug("Lamp %d is in groups %s", lamp, lamp_groups)

        except Exception as e:
            logger.warning("Can't get groups for lamp %s: %s", lamp, e)
    logger.info("Finished scanning for groups")
    return groups


def initialize_lamps(data_object, client):
    logger.info("initializing lamps...")
    driver_object = data_object["driver"]
    lamps = scan_lamps(driver_object)
    logger.info("Getting lamp parameters:")
    for lamp in lamps:
        try:
            _address = address.Short(lamp)
            lamp = Lamp(driver_object, client, _address)
            data_object["all_lamps"][lamp.address] = lamp

        except Exception as err:
            logger.error("While initializing lamp<%s>: %s", lamp, err)
            print(traceback.format_exc())
            raise err

    groups = scan_groups(driver_object, lamps)
    for group, group_lamps in groups.items():
        try:
            _address = address.Group(group)
            _lamps = []
            for _x in group_lamps:
                _lamps.append(data_object["all_lamps"][_x])
            group = Group(driver_object, client, _address, _lamps)
            for _x in group_lamps:
                data_object["all_lamps"][_x].addGroup(group)
            data_object["all_groups"][group.address] = group

        except Exception as err:
            logger.error("While initializing group<%s>: %s", group, err)
            print(traceback.format_exc())
            raise err

    devices_names_config = DevicesNamesConfig()
    if devices_names_config.is_devices_file_empty():
        devices_names_config.save_devices_names_file(
            list(data_object["all_lamps"].values()) + list(data_object["all_groups"].values()))

    config = Config()
    client.publish(
        MQTT_DALI2MQTT_STATUS.format(config[CONF_MQTT_BASE_TOPIC]), MQTT_AVAILABLE, retain=True
    )
    logger.info("initializing lamps finished")



def get_light_object(data_object, light):
    try:
        _x = light.split("_")
        type = _x[0]
        light = int(_x[1])
    except (KeyError, ValueError):
        logger.error(f"Invalid topic {light}")
        return

    try:
        if type == "lamp":
            return data_object["all_lamps"][light]
        elif type == "group":
            return data_object["all_groups"][light]
        else:
            logger.error(f"{type} {light} invalid type")
    except KeyError:
        logger.error(f"Light {type} {light} doesn't exists")
    return None


def on_message_cmd(mqtt_client, data_object, msg):
    """Callback on MQTT command message."""
    logger.debug("Command on %s: %s", msg.topic, msg.payload)
    light = msg.topic.split("/")[1]
    light = get_light_object(data_object, light)
    if light is None:
        return
    if msg.payload == MQTT_PAYLOAD_OFF:
        try:
            light.setLevel(0)
            logger.debug(f"Set {light.device_name} to OFF")
        except DALIError as err:
            logger.error(f"Failed to set {light.device_name} to OFF: {err}")


def on_message_flash(mqtt_client, data_object, msg):
    """Callback on MQTT flash message."""
    logger.debug("Flash on %s: %s", msg.topic, msg.payload)
    light = msg.topic.split("/")[1]
    light = get_light_object(data_object, light)
    if light is None:
        return
    try:
        data = json.loads(msg.payload)
    except ValueError:
        logger.warning(f"Failed to parse payload for flash on light: {light.device_name}")
        return

    try:
        light.flash(data["count"], data["speed"])
    except KeyError:
        logger.warning(f"Failed to get need parameters from payload {data} for flash on light: {light.device_name}")
        return


def on_message_brightness_cmd(mqtt_client, data_object, msg):
    """Callback on MQTT brightness command message."""
    logger.debug("Brightness Command on %s: %s", msg.topic, msg.payload)
    light = msg.topic.split("/")[1]
    light = get_light_object(data_object, light)
    if light is None:
        return
    level = msg.payload.decode("utf-8")

    if level.isdigit() and 0 <= int(level) < 256:
        level = int(level)
        try:
            light.setLevel(level)
            logger.debug(f"Set {light.device_name} to {level}")
        except DALIError as err:
            logger.error(f"Failed to set {light.device_name} to OFF: {err}")
    else:
        logger.error(f"Invalid payload for {light}: {level}")


def on_message_scene_cmd(mqtt_client, data_object, msg):
    """Callback on MQTT scene command message."""
    logger.debug("Scene Command on %s: %s", msg.topic, msg.payload)
    light = msg.topic.split("/")[1]
    light = get_light_object(data_object, light)
    if light is None:
        return
    scene = msg.payload.decode("utf-8")
    if scene == "-":
        light.setSceneToNoneMQTT()
        return
    if scene.startswith("Scene ") and len(scene.split(" ")) == 2:
        scene = scene.split(" ")
        if len(scene) == 2 and scene[1].isdigit() and 0 <= int(scene[1]) <= 15:
            scene = int(scene[1])
            try:
                light.setScene(scene)
                logger.debug(f"Set {light.device_name} to Scene {scene}")
            except DALIError as err:
                logger.error(f"Failed to set {light.device_name} to Scene {scene}: {err}")
        else:
            logger.error(f"Invalid payload for {light}: {scene}")
    else:
        logger.error(f"Invalid payload for {light}: {scene}")


def on_message_reinitialize_lamps_cmd(mqtt_client, data_object, msg):
    """Callback on MQTT scan lamps command message"""
    logger.debug("Reinitialize Command on %s", msg.topic)
    logger.info("Reinitializing lamps")
    config = Config()
    mqtt_client.publish(
        MQTT_DALI2MQTT_STATUS.format(config[CONF_MQTT_BASE_TOPIC]), MQTT_NOT_AVAILABLE, retain=True
    )
    initialize_lamps(data_object, mqtt_client)


def on_message_poll_lamps_cmd(mqtt_client, data_object, msg):
    """Callback on MQTT poll lamps command message"""
    logger.debug("Poll lamps command on %s", msg.topic)
    logger.info("Polling lamps")
    for _x in data_object["all_lamps"].values():
        _x.pollLevel()
    for _x in data_object["all_groups"].values():
        _x.recalc_level()
    logger.info("Polling lamps finished")


def on_message(mqtt_client, data_object, msg):  # pylint: disable=W0613
    """Default callback on MQTT message."""
    logger.error("Don't publish to %s", msg.topic)


def on_connect(client, data_object, flags, result):  # pylint: disable=W0613,R0913
    """Callback on connection to MQTT server."""
    config = Config()
    client.subscribe(
        [
            (MQTT_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"), 0),
            (MQTT_FLASH_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"), 0),
            (MQTT_BRIGHTNESS_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"), 0),
            (MQTT_SCENE_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"), 0),
            (MQTT_SCAN_LAMPS_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC]), 0),
            (MQTT_POLL_LAMPS_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC]), 0),
        ]
    )
    client.publish(
        MQTT_DALI2MQTT_STATUS.format(config[CONF_MQTT_BASE_TOPIC]), MQTT_NOT_AVAILABLE, retain=True
    )
    initialize_lamps(data_object, client)
    register_bridge(client)


def register_bridge(client):
    logger.info("registering buttons")
    config = Config()
    for button in BUTTONS:
        json_config = {
            "name": button['name'],
            "unique_id": "{}_BUTTON_{}".format(config[CONF_MQTT_BASE_TOPIC], slugify(button['name'])),
            "command_topic": button['command_topic'].format(
                config[CONF_MQTT_BASE_TOPIC]
            ),
            "entity_category": button['entity_category'],
            "availability_topic": MQTT_DALI2MQTT_STATUS.format(config[CONF_MQTT_BASE_TOPIC]),
            "payload_available": MQTT_AVAILABLE,
            "payload_not_available": MQTT_NOT_AVAILABLE,
            "device": {
                "identifiers": config[CONF_MQTT_BASE_TOPIC],
                "name": f"DALI2MQTT Bridge",
                "sw_version": VERSION,
                "manufacturer": AUTHOR
            },
        }

        if 'device_class' in button and button['device_class'] is not None:
            json_config["device_class"] = button['device_class']

        logger.debug(f"Register button {button['name']}")
        client.publish(
            HA_DISCOVERY_PREFIX_BUTTON.format(config[CONF_HA_DISCOVERY_PREFIX], config[CONF_MQTT_BASE_TOPIC],
                                              slugify(button['name'])),
            json.dumps(json_config),
            retain=True,
        )


def create_mqtt_client(driver_object):
    """Create MQTT client object, setup callbacks and connection to server."""

    config = Config()
    logger.debug("Connecting to %s:%s", config[CONF_MQTT_SERVER], config[CONF_MQTT_PORT])
    mqttc = mqtt.Client(
        client_id="dali2mqttx",
        userdata={
            "driver": driver_object,
            "all_lamps": {},
            "all_groups": {}
        },
    )
    mqttc.will_set(
        MQTT_DALI2MQTT_STATUS.format(config[CONF_MQTT_BASE_TOPIC]), MQTT_NOT_AVAILABLE, retain=True
    )
    mqttc.on_connect = on_connect

    # Add message callbacks that will only trigger on a specific subscription match.
    mqttc.message_callback_add(
        MQTT_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"), on_message_cmd
    )
    mqttc.message_callback_add(
        MQTT_FLASH_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"), on_message_flash
    )
    mqttc.message_callback_add(
        MQTT_BRIGHTNESS_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"),
        on_message_brightness_cmd,
    )
    mqttc.message_callback_add(
        MQTT_SCENE_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"),
        on_message_scene_cmd,
    )
    mqttc.message_callback_add(
        MQTT_SCAN_LAMPS_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC]),
        on_message_reinitialize_lamps_cmd,
    )
    mqttc.message_callback_add(
        MQTT_POLL_LAMPS_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC]),
        on_message_poll_lamps_cmd,
    )

    mqttc.on_message = on_message

    if config[CONF_MQTT_USERNAME] != '':
        mqttc.username_pw_set(config[CONF_MQTT_USERNAME], config[CONF_MQTT_PASSWORD])

    mqttc.connect(config[CONF_MQTT_SERVER], config[CONF_MQTT_PORT], 180)
    return mqttc


def main(args):
    config = Config()
    config.setup(args)

    if config[CONF_LOG_COLOR]:
        logging.addLevelName(
            logging.WARNING,
            "{}{}".format(YELLOW_COLOR, logging.getLevelName(logging.WARNING)),
        )
        logging.addLevelName(
            logging.ERROR, "{}{}".format(RED_COLOR, logging.getLevelName(logging.ERROR))
        )

    logger.setLevel(ALL_SUPPORTED_LOG_LEVELS[config[CONF_LOG_LEVEL]])
    devices_names_config = DevicesNamesConfig()
    devices_names_config.setup()

    dali_driver = None
    logger.debug("Using <%s> driver", config[CONF_DALI_DRIVER])

    if config[CONF_DALI_DRIVER] == HASSEB:
        from dali.driver.hasseb import SyncHassebDALIUSBDriver

        dali_driver = SyncHassebDALIUSBDriver()

        try:
            firmware_version = float(dali_driver.readFirmwareVersion())
        except AttributeError:
            logger.error("Could not open device. Is the hasseb adapter connected and has the right permissions?")
            quit(1)
            return
        if firmware_version < MIN_HASSEB_FIRMWARE_VERSION:
            logger.error("Using dali2mqtt requires newest hasseb firmware")
            logger.error(
                "Please, look at https://github.com/hasseb/python-dali/tree/master/dali/driver/hasseb_firmware"
            )
            quit(1)
        # Force disable sniffing, as we get strange return values when sniffing is enabled
        dali_driver.disableSniffing()
    elif config[CONF_DALI_DRIVER] == TRIDONIC:
        from dali.driver.tridonic import SyncTridonicDALIUSBDriver

        dali_driver = SyncTridonicDALIUSBDriver()
    elif config[CONF_DALI_DRIVER] == DALI_SERVER:
        from dali.driver.daliserver import DaliServer

        dali_driver = DaliServer("localhost", 55825)

    mqttc = create_mqtt_client(dali_driver)
    try:
        mqttc.loop_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
