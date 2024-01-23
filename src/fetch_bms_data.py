import sys
import os
import logging
import configparser
import time
import json
import serial
from serial.serialutil import SerialException
import paho.mqtt.client as mqtt
from paho.mqtt import MQTTException
from typing import List

try:
    # cast config vars to requested type
    def cast_value(value, return_type) -> int | float | bool | str | None:
        try:
            if return_type == int:
                return int(value)
            elif return_type == float:
                return float(value)
            elif return_type == bool:
                return value.lower() in ['true', '1', 'yes', 'on']
            else:
                return str(value)
        except ValueError:
            return None

    # get config vars either from env-var (1st) or config.ini (2nd)
    def get_config_value(var_name, return_type=str) -> int | float | bool | str | None:
        # first, try to get the value from environment variables
        value = os.environ.get(var_name)
        if value is not None:
            return cast_value(value, return_type)

        # if the variable is not in the environment, try the config file
        config = configparser.ConfigParser()
        config.read("config.ini")

        for section in config.sections():
            if var_name in config[section]:
                return cast_value(config[section][var_name], return_type)

        # return None if the variable is not found
        return None

    # BMS config
    
    # when ONLY_MASTER is True, data will only be fetched for one pack (0) 
    ONLY_MASTER = get_config_value("ONLY_MASTER", return_type=bool)
    # when ONLY_MASTER is False, data will be fetched for NUMBER_OF_PACKS (1-n)
    NUMBER_OF_PACKS = get_config_value("NUMBER_OF_PACKS", return_type=int)
    # set min and max cell-voltage as this cannot be read from the BMS
    MIN_CELL_VOLTAGE = get_config_value("MIN_CELL_VOLTAGE", return_type=float)
    MAX_CELL_VOLTAGE = get_config_value("MAX_CELL_VOLTAGE", return_type=float)

    # Logging setup and config 
    
    logging.basicConfig()
    logger = logging.getLogger("SeplosBMS")
    
    if get_config_value("LOGGING_LEVEL").upper() == "ERROR":
        logger.setLevel(logging.ERROR)
    elif get_config_value("LOGGING_LEVEL").upper() == "WARNING":
        logger.setLevel(logging.WARNING)
    elif get_config_value("LOGGING_LEVEL").upper() == "DEBUG":
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    # MQTT config and setuo

    MQTT_HOST = get_config_value("MQTT_HOST")
    MQTT_PORT = get_config_value("MQTT_PORT", return_type=int)
    MQTT_USERNAME = get_config_value("MQTT_USERNAME")
    MQTT_PASSWORD = get_config_value("MQTT_PASSWORD")
    MQTT_TOPIC = get_config_value("MQTT_TOPIC")
    MQTT_UPDATE_INTERVAL = get_config_value("MQTT_UPDATE_INTERVAL", return_type=int)

    mqtt_client = mqtt.Client()
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    mqtt_client.on_connect = logger.info("mqtt connected ({}:{}, user: {})".format(MQTT_HOST, MQTT_PORT, MQTT_USERNAME))

    # Serial Interface config and setup (set to 9600 for Master and 19200 for Slaves)

    SERIAL_INTERFACE = get_config_value("SERIAL_INTERFACE")
    SERIAL_BAUD_RATE = get_config_value("SERIAL_BAUD_RATE", return_type=int)

    serial_instance = None

    # Debug output of env-var settings
    
    logger.debug(f"SERIAL_INTERFACE: {SERIAL_INTERFACE}")
    logger.debug(f"SERIAL_BAUD_RATE: {SERIAL_BAUD_RATE}")

    logger.debug(f"MQTT_HOST: {MQTT_HOST}")
    logger.debug(f"MQTT_PORT: {MQTT_PORT}")
    logger.debug(f"MQTT_USERNAME: {MQTT_USERNAME}")
    logger.debug(f"MQTT_PASSWORD: {MQTT_PASSWORD}")
    logger.debug(f"MQTT_TOPIC: {MQTT_TOPIC}")
    logger.debug(f"MQTT_UPDATE_INTERVAL: {MQTT_UPDATE_INTERVAL}")

    logger.debug(f"ONLY_MASTER: {ONLY_MASTER}")
    logger.debug(f"NUMBER_OF_PACKS: {NUMBER_OF_PACKS}")

    logger.debug(f"MIN_CELL_VOLTAGE: {MIN_CELL_VOLTAGE}")
    logger.debug(f"MAX_CELL_VOLTAGE: {MAX_CELL_VOLTAGE}")

    # Telesignalization Class
    class Telesignalization(object):
        """
        This class holds Warning and alarm states for different types of Checks
        They are of type integer, 2 represents a Telesignalization event, 1 a Warning event, 0 if everything is fine
        """

        def __init__(self):

            # equalization status

            self.cell_voltage_warning = [None] * 16
            self.cell_temperature_warning = [None] * 4
            self.ambient_temperature_warning: str = None
            self.component_temperature_warning: str = None
            self.dis_charging_current_warning: str = None
            self.pack_voltage_warning: str = None
            
            # warning 1

            self.voltage_sensing_failure: str = None
            self.temp_sensing_failure: str = None
            self.current_sensing_failure: str = None
            self.power_switch_failure: str = None
            self.cell_voltage_difference_sensing_failure: str = None
            self.charging_switch_failure: str = None
            self.discharging_switch_failure: str = None
            self.current_limit_switch_failure: str = None

            # warning 2

            self.cell_overvoltage: str = None
            self.cell_voltage_low: str = None
            self.pack_overvoltage: str = None
            self.pack_voltage_low: str = None

            # warning 3

            self.charging_temp_high: str = None
            self.charging_temp_low: str = None
            self.discharging_temp_high: str = None
            self.discharging_temp_low: str = None
            
            # warning 4

            self.ambient_temp_high: str = None
            self.ambient_temp_low: str = None
            self.component_temp_high: str = None

            # warning 5

            self.charging_overcurrent: str = None
            self.discharging_overcurrent: str = None
            self.transient_overcurrent: str = None
            self.output_short_circuit: str = None
            self.transient_overcurrent_lock: str = None
            self.output_short_circuit_lock: str = None

            # warning 6

            self.charging_high_voltage: str = None
            self.intermittent_power_supplement: str = None
            self.soc_low: str = None
            self.cell_low_voltage_forbidden_charging: str = None
            self.output_reverse_protection: str = None
            self.output_connection_failure: str = None
            
            # power status
            
            self.discharge_switch: str = None
            self.charge_switch: str = None
            self.current_limit_switch: str = None
            self.heating_limit_switch: str = None

            # equalization status
            
            self.cell_equalization = [None] * 16

            # system status
            
            self.discharge: str = None
            self.charge: str = None
            self.floating_charge: str = None
            self.standby: str = None
            self.power_off: str = None

            # disconnection status

            self.cell_disconnection = [None] * 16

            # warning 7
            
            self.auto_charging_wait: str = None
            self.manual_charging_wait: str = None

            # warning 8
            
            self.eep_storage_failure: str = None
            self.rtc_clock_failure: str = None
            self.no_calibration_of_voltage: str = None
            self.no_calibration_of_current: str = None
            self.no_calibration_of_null_point: str = None

    # Telemetry Class
    class Telemetry(object):
        """
        This class holds Warning, Protection, Normal, On and Off states for different types of Checks
        """

        def __init__(self):

            # from pack

            self.cell_voltage = [None] * 16
            self.cell_temperature: float = [None] * 4
            self.ambient_temperature: float = None
            self.components_temperature: float = None
            self.dis_charge_current: float = None
            self.total_pack_voltage: float = None
            self.residual_capacity: float = None
            self.battery_capacity: float = None
            self.soc: float = None
            self.rated_capacity: float = None
            self.cycles: int = None
            self.soh: float = None
            self.port_voltage: float = None

            # calculated

            self.average_cell_voltage: float = None
            self.delta_cell_voltage: float = None
            self.lowest_cell: int = None
            self.lowest_cell_voltage: float = None
            self.highest_cell: int = None
            self.highest_cell_voltage: float = None
            self.min_pack_voltage: float = None
            self.max_pack_voltage: float = None
            self.dis_charge_power: float = None

    # Battery-Pack Class
    class SeplosBatteryPack():
        def __init__(self, pack_address):

            # pack address (0 for Master, 1-n for Slaves)
            self.pack_address = pack_address
            
            # last status (update mqtt only on changed data)
            self.last_status = None
            
            # Telemetry and Telesignalization store
            self.telemetry = Telemetry()           
            self.telesignalization = Telesignalization()

        # calculate given frame checksum
        @staticmethod
        def calculate_frame_checksum(frame: bytes) -> int:
            checksum = 0
            for b in frame:
                checksum += b
            checksum %= 0xFFFF
            checksum ^= 0xFFFF
            checksum += 1
            return checksum

        # check if ascii data is hex only
        @staticmethod
        def is_valid_hex_string(data) -> bool:
            try:
                bytes.fromhex(data.decode("ascii"))
                logger.debug("frame has hex only: ok")
                return True
            except ValueError:
                logger.debug("frame includes non-hexadecimal characters, got: {}".format(data))
                return False

        # check data has requested length (alarm: 98, stats: 168)
        @staticmethod
        def is_valid_length(data, expected_length: int) -> bool:
            datalength = len(data)
            if datalength < expected_length:
                logger.debug("frame length too short, expected {}, got: {}".format(expected_length, datalength))
                return False
            logger.debug("frame length (expected: {}): ok".format(expected_length))
            return True
        
        # return integer from given 1 byte ascii hex data
        @staticmethod
        def int_from_1byte_hex_ascii(data: bytes, offset: int, signed=False) -> int:
            return int.from_bytes(
                bytes.fromhex(data[offset : offset + 2].decode("ascii")),
                byteorder="big",
                signed=signed,
            )

        # return integer from given 2 byte ascii hex data
        @staticmethod
        def int_from_2byte_hex_ascii(data: bytes, offset: int, signed=False) -> int:
            return int.from_bytes(
                bytes.fromhex(data[offset : offset + 4].decode("ascii")),
                byteorder="big",
                signed=signed,
            )
        
        # return normal/trigger_low/trigger_high/trigger_other status
        @staticmethod
        def status_from_24_byte_alarm(data: bytes, offset: int) -> str:
            alarm_type = bytes.fromhex(data.decode("ascii"))[offset]
            if alarm_type == 0:
                return "normal"
            elif alarm_type == 1:
                return "trigger_low"
            elif alarm_type == 2:
                return "trigger_high"
            else:
                return "trigger_other"
        
        # return either on/off or normal/warning/protection status
        @staticmethod
        def status_from_20_bit_alarm(data: bytes, offset: int, on_off_bit: int=None, warn_bit: int=None, protection_bit: int=None) -> str:
            data_byte = bytes.fromhex(data.decode("ascii"))[offset]
            if on_off_bit is not None:
                return "on" if data_byte & (1 << on_off_bit) != 0 else "off"
            elif warn_bit is not None:
                if data_byte & (1 << warn_bit) != 0:
                    return "warning"
                if protection_bit is not None and data_byte & (1 << protection_bit) != 0:
                    return "protection"
                return "normal"

        # decode battery pack telesignalization feedback frame
        def decode_telesignalization_feedback_frame(self, data: bytes) -> dict:
            telesignalization_feedback = {}
            
            # number of cells
            
            number_of_cells = bytes.fromhex(data.decode("ascii"))[2]

            # info 24 byte alarm offsets
            
            cell_warning_byte_offset = 3
            cell_temperature_warning_byte_offset = 20
            ambient_temperature_warning_byte_offset = 24
            component_temperature_warning_byte_offset = 25
            dis_charging_current_warning_byte_offset = 26
            pack_voltage_warning_byte_offset = 27

            # info 20 bit alarm offsets
            
            warning_1_alarm_byte_offset = 29
            warning_2_alarm_byte_offset = 30
            warning_3_alarm_byte_offset = 31
            warning_4_alarm_byte_offset = 32
            warning_5_alarm_byte_offset = 33
            warning_6_alarm_byte_offset = 34
            power_status_byte_offset = 35
            equalization_status1_byte_offset = 36
            equalization_status2_byte_offset = 37
            system_status_byte_offset = 38
            disconnection_status1_byte_offset = 39
            disconnection_status2_byte_offset = 40
            warning_7_alarm_byte_offset = 41
            warning_8_alarm_byte_offset = 42

            # info data
            
            for i in range(number_of_cells):  # 0 to 15, for 16 cells
                self.telesignalization.cell_voltage_warning[i] = self.status_from_24_byte_alarm(data=data, offset=cell_warning_byte_offset + i)
                telesignalization_feedback[f"voltage_warning_cell_{i + 1}"] = self.telesignalization.cell_voltage_warning[i]

            for i in range(4):  # 0 to 3, for 4 temperature sensors
                self.telesignalization.cell_temperature_warning[i] = self.status_from_24_byte_alarm(data=data, offset=cell_temperature_warning_byte_offset + i)
                telesignalization_feedback[f"cell_temperature_warning_{i + 1}"] = self.telesignalization.cell_temperature_warning[i]

            self.telesignalization.ambient_temperature_warning = self.status_from_24_byte_alarm(data=data, offset=ambient_temperature_warning_byte_offset)
            telesignalization_feedback[f"ambient_temperature_warning"] = self.telesignalization.ambient_temperature_warning

            self.telesignalization.component_temperature_warning = self.status_from_24_byte_alarm(data=data, offset=component_temperature_warning_byte_offset)
            telesignalization_feedback[f"component_temperature_warning"] = self.telesignalization.component_temperature_warning

            self.telesignalization.dis_charging_current_warning = self.status_from_24_byte_alarm(data=data, offset=dis_charging_current_warning_byte_offset)
            telesignalization_feedback[f"dis_charging_current_warning"] = self.telesignalization.dis_charging_current_warning

            self.telesignalization.pack_voltage_warning = self.status_from_24_byte_alarm(data=data, offset=pack_voltage_warning_byte_offset)
            telesignalization_feedback[f"pack_voltage_warning"] = self.telesignalization.pack_voltage_warning

            # warning 1

            self.telesignalization.voltage_sensing_failure = self.status_from_20_bit_alarm(
                data=data, offset=warning_1_alarm_byte_offset, warn_bit=0
            )
            telesignalization_feedback["voltage_sensing_failure"] = self.telesignalization.voltage_sensing_failure

            self.telesignalization.temp_sensing_failure = self.status_from_20_bit_alarm(
                data=data, offset=warning_1_alarm_byte_offset, warn_bit=1
            )
            telesignalization_feedback["temp_sensing_failure"] = self.telesignalization.temp_sensing_failure

            self.telesignalization.current_sensing_failure = self.status_from_20_bit_alarm(
                data=data, offset=warning_1_alarm_byte_offset, warn_bit=2
            )
            telesignalization_feedback["current_sensing_failure"] = self.telesignalization.current_sensing_failure

            self.telesignalization.power_switch_failure = self.status_from_20_bit_alarm(
                data=data, offset=warning_1_alarm_byte_offset, warn_bit=3
            )
            telesignalization_feedback["power_switch_failure"] = self.telesignalization.power_switch_failure

            self.telesignalization.cell_voltage_difference_sensing_failure = self.status_from_20_bit_alarm(
                data=data, offset=warning_1_alarm_byte_offset, warn_bit=4
            )
            telesignalization_feedback["cell_voltage_difference_sensing_failure"] = self.telesignalization.cell_voltage_difference_sensing_failure

            self.telesignalization.charging_switch_failure = self.status_from_20_bit_alarm(
                data=data, offset=warning_1_alarm_byte_offset, warn_bit=5
            )
            telesignalization_feedback["charging_switch_failure"] = self.telesignalization.charging_switch_failure

            self.telesignalization.discharging_switch_failure = self.status_from_20_bit_alarm(
                data=data, offset=warning_1_alarm_byte_offset, warn_bit=6
            )
            telesignalization_feedback["discharging_switch_failure"] = self.telesignalization.discharging_switch_failure

            self.telesignalization.current_limit_switch_failure = self.status_from_20_bit_alarm(
                data=data, offset=warning_1_alarm_byte_offset, warn_bit=7
            )
            telesignalization_feedback["current_limit_switch_failure"] = self.telesignalization.current_limit_switch_failure

            # warning 2

            self.telesignalization.cell_overvoltage = self.status_from_20_bit_alarm(
                data=data, offset=warning_2_alarm_byte_offset, warn_bit=0, protection_bit=1
            )
            telesignalization_feedback["cell_overvoltage"] = self.telesignalization.cell_overvoltage

            self.telesignalization.cell_voltage_low = self.status_from_20_bit_alarm(
                data=data, offset=warning_2_alarm_byte_offset, warn_bit=2, protection_bit=3
            )
            telesignalization_feedback["cell_voltage_low"] = self.telesignalization.cell_voltage_low

            self.telesignalization.pack_overvoltage = self.status_from_20_bit_alarm(
                data=data, offset=warning_2_alarm_byte_offset, warn_bit=4, protection_bit=5
            )
            telesignalization_feedback["pack_overvoltage"] = self.telesignalization.pack_overvoltage

            self.telesignalization.pack_voltage_low = self.status_from_20_bit_alarm(
                data=data, offset=warning_2_alarm_byte_offset, warn_bit=6, protection_bit=7
            )
            telesignalization_feedback["pack_voltage_low"] = self.telesignalization.pack_voltage_low

            # warning 3

            self.telesignalization.charging_temp_high = self.status_from_20_bit_alarm(
                data=data, offset=warning_3_alarm_byte_offset, warn_bit=0, protection_bit=1
            )
            telesignalization_feedback["charging_temp_high"] = self.telesignalization.charging_temp_high

            self.telesignalization.charging_temp_low = self.status_from_20_bit_alarm(
                data=data, offset=warning_3_alarm_byte_offset, warn_bit=2, protection_bit=3
            )
            telesignalization_feedback["charging_temp_low"] = self.telesignalization.charging_temp_low

            self.telesignalization.discharging_temp_high = self.status_from_20_bit_alarm(
                data=data, offset=warning_3_alarm_byte_offset, warn_bit=4, protection_bit=5
            )
            telesignalization_feedback["discharging_temp_high"] = self.telesignalization.discharging_temp_high

            self.telesignalization.discharging_temp_low = self.status_from_20_bit_alarm(
                data=data, offset=warning_3_alarm_byte_offset, warn_bit=6, protection_bit=7
            )
            telesignalization_feedback["discharging_temp_low"] = self.telesignalization.discharging_temp_low

            # warning 4

            self.telesignalization.ambient_temp_high = self.status_from_20_bit_alarm(
                data=data, offset=warning_4_alarm_byte_offset, warn_bit=0, protection_bit=1
            )
            telesignalization_feedback["ambient_temp_high"] = self.telesignalization.ambient_temp_high

            self.telesignalization.ambient_temp_low = self.status_from_20_bit_alarm(
                data=data, offset=warning_4_alarm_byte_offset, warn_bit=2, protection_bit=3
            )
            telesignalization_feedback["ambient_temp_high"] = self.telesignalization.ambient_temp_high

            self.telesignalization.component_temp_high = self.status_from_20_bit_alarm(
                data=data, offset=warning_4_alarm_byte_offset, warn_bit=4, protection_bit=5
            )
            telesignalization_feedback["component_temp_high"] = self.telesignalization.component_temp_high

            # warning 5

            self.telesignalization.charging_overcurrent = self.status_from_20_bit_alarm(
                data=data, offset=warning_5_alarm_byte_offset, warn_bit=0, protection_bit=1
            )
            telesignalization_feedback["charging_overcurrent"] = self.telesignalization.charging_overcurrent

            self.telesignalization.discharging_overcurrent = self.status_from_20_bit_alarm(
                data=data, offset=warning_5_alarm_byte_offset, warn_bit=2, protection_bit=3
            )
            telesignalization_feedback["discharging_overcurrent"] = self.telesignalization.discharging_overcurrent

            self.telesignalization.transient_overcurrent = self.status_from_20_bit_alarm(
                data=data, offset=warning_5_alarm_byte_offset, warn_bit=4
            )
            telesignalization_feedback["transient_overcurrent"] = self.telesignalization.transient_overcurrent

            self.telesignalization.output_short_circuit = self.status_from_20_bit_alarm(
                data=data, offset=warning_5_alarm_byte_offset, warn_bit=5
            )
            telesignalization_feedback["output_short_circuit"] = self.telesignalization.output_short_circuit

            self.telesignalization.transient_overcurrent_lock = self.status_from_20_bit_alarm(
                data=data, offset=warning_5_alarm_byte_offset, warn_bit=6
            )
            telesignalization_feedback["transient_overcurrent_lock"] = self.telesignalization.transient_overcurrent_lock

            self.telesignalization.output_short_circuit_lock = self.status_from_20_bit_alarm(
                data=data, offset=warning_5_alarm_byte_offset, warn_bit=7
            )
            telesignalization_feedback["transient_overcurrent_lock"] = self.telesignalization.output_short_circuit_lock

            # warning 6

            self.telesignalization.charging_high_voltage = self.status_from_20_bit_alarm(
                data=data, offset=warning_6_alarm_byte_offset, warn_bit=0
            )
            telesignalization_feedback["charging_high_voltage"] = self.telesignalization.charging_high_voltage

            self.telesignalization.intermittent_power_supplement = self.status_from_20_bit_alarm(
                data=data, offset=warning_6_alarm_byte_offset, warn_bit=1
            )
            telesignalization_feedback["intermittent_power_supplement"] = self.telesignalization.intermittent_power_supplement

            self.telesignalization.soc_low = self.status_from_20_bit_alarm(
                data=data, offset=warning_6_alarm_byte_offset, warn_bit=2, protection_bit=3
            )
            telesignalization_feedback["soc_low"] = self.telesignalization.soc_low

            self.telesignalization.cell_low_voltage_forbidden_charging = self.status_from_20_bit_alarm(
                data=data, offset=warning_6_alarm_byte_offset, warn_bit=4
            )
            telesignalization_feedback["cell_low_voltage_forbidden_charging"] = self.telesignalization.cell_low_voltage_forbidden_charging

            self.telesignalization.output_reverse_protection = self.status_from_20_bit_alarm(
                data=data, offset=warning_6_alarm_byte_offset, warn_bit=5
            )
            telesignalization_feedback["output_reverse_protection"] = self.telesignalization.output_reverse_protection

            self.telesignalization.output_connection_failure = self.status_from_20_bit_alarm(
                data=data, offset=warning_6_alarm_byte_offset, warn_bit=6
            )
            telesignalization_feedback["output_connection_failure"] = self.telesignalization.output_connection_failure

            # power status

            self.telesignalization.discharge_switch = self.status_from_20_bit_alarm(
                data=data, offset=power_status_byte_offset, on_off_bit=0
            )
            telesignalization_feedback["discharge_switch"] = self.telesignalization.discharge_switch

            self.telesignalization.charge_switch = self.status_from_20_bit_alarm(
                data=data, offset=power_status_byte_offset, on_off_bit=1
            )
            telesignalization_feedback["charge_switch"] = self.telesignalization.charge_switch

            self.telesignalization.current_limit_switch = self.status_from_20_bit_alarm(
                data=data, offset=power_status_byte_offset, on_off_bit=2
            )
            telesignalization_feedback["current_limit_switch"] = self.telesignalization.current_limit_switch

            self.telesignalization.heating_limit_switch = self.status_from_20_bit_alarm(
                data=data, offset=power_status_byte_offset, on_off_bit=3
            )
            telesignalization_feedback["heating_limit_switch"] = self.telesignalization.heating_limit_switch

            # equalization status 1 + 2

            for i in range(number_of_cells):
                on_off_bit = i % 8
                offset = equalization_status1_byte_offset if i < 8 else equalization_status2_byte_offset

                self.telesignalization.cell_equalization[i] = self.status_from_20_bit_alarm(data=data, offset=offset, on_off_bit=on_off_bit)
                # shift cell-index on return List by 1
                telesignalization_feedback[f"equalization_cell_{i + 1}"] = self.telesignalization.cell_equalization[i]

            # system status

            self.telesignalization.discharge = self.status_from_20_bit_alarm(
                data=data, offset=system_status_byte_offset, on_off_bit=0
            )
            telesignalization_feedback["discharge"] = self.telesignalization.discharge

            self.telesignalization.charge = self.status_from_20_bit_alarm(
                data=data, offset=system_status_byte_offset, on_off_bit=1
            )
            telesignalization_feedback["charge"] = self.telesignalization.charge

            self.telesignalization.floating_charge = self.status_from_20_bit_alarm(
                data=data, offset=system_status_byte_offset, on_off_bit=2
            )
            telesignalization_feedback["floating_charge"] = self.telesignalization.floating_charge

            self.telesignalization.standby = self.status_from_20_bit_alarm(
                data=data, offset=system_status_byte_offset, on_off_bit=4
            )
            telesignalization_feedback["standby"] = self.telesignalization.standby

            self.telesignalization.power_off = self.status_from_20_bit_alarm(
                data=data, offset=system_status_byte_offset, on_off_bit=5
            )
            telesignalization_feedback["power_off"] = self.telesignalization.power_off

            # disconnection status 1 + 2

            for i in range(number_of_cells):
                warn_bit = i % 8
                offset = disconnection_status1_byte_offset if i < 8 else disconnection_status2_byte_offset

                self.telesignalization.cell_disconnection[i] = self.status_from_20_bit_alarm(data=data, offset=offset, warn_bit=warn_bit)
                # shift cell-index on return List by 1
                telesignalization_feedback[f"disconnection_cell_{i + 1}"] = self.telesignalization.cell_disconnection[i]

            # warning 7

            self.telesignalization.auto_charging_wait = self.status_from_20_bit_alarm(
                data=data, offset=warning_7_alarm_byte_offset, warn_bit=4
            )
            telesignalization_feedback["auto_charging_wait"] = self.telesignalization.auto_charging_wait

            self.telesignalization.manual_charging_wait = self.status_from_20_bit_alarm(
                data=data, offset=warning_7_alarm_byte_offset, warn_bit=5
            )
            telesignalization_feedback["manual_charging_wait"] = self.telesignalization.manual_charging_wait

            # warning 8

            self.telesignalization.eep_storage_failure = self.status_from_20_bit_alarm(
                data=data, offset=warning_8_alarm_byte_offset, warn_bit=0
            )
            telesignalization_feedback["eep_storage_failure"] = self.telesignalization.eep_storage_failure

            self.telesignalization.rtc_clock_failure = self.status_from_20_bit_alarm(
                data=data, offset=warning_8_alarm_byte_offset, warn_bit=1
            )
            telesignalization_feedback["rtc_clock_failure"] = self.telesignalization.rtc_clock_failure

            self.telesignalization.no_calibration_of_voltage = self.status_from_20_bit_alarm(
                data=data, offset=warning_8_alarm_byte_offset, warn_bit=2
            )
            telesignalization_feedback["no_calibration_of_voltage"] = self.telesignalization.no_calibration_of_voltage

            self.telesignalization.no_calibration_of_current = self.status_from_20_bit_alarm(
                data=data, offset=warning_8_alarm_byte_offset, warn_bit=3
            )
            telesignalization_feedback["no_calibration_of_current"] = self.telesignalization.no_calibration_of_current

            self.telesignalization.no_calibration_of_null_point = self.status_from_20_bit_alarm(
                data=data, offset=warning_8_alarm_byte_offset, warn_bit=4
            )
            telesignalization_feedback["no_calibration_of_null_point"] = self.telesignalization.no_calibration_of_null_point

            return telesignalization_feedback

        # check validity of given frame, i.e. lenght, checksum and error flag
        def is_valid_frame(self, data: bytes) -> bool:
            """checks if data contains a valid frame
            * minimum length is 18 Byte
            * checksum needs to be valid
            * also checks for error code as return code in cid2
            * not checked: lchksum
            """
            try:
                # check frame checksum
                chksum = self.calculate_frame_checksum(data[1:-5])
                compare = self.int_from_2byte_hex_ascii(data, -5)
                if chksum != compare:
                    logger.debug("frame has wrong checksum, got {}, expected {}".format(chksum, compare))
                    return False
                logger.debug("frame checksum ok, got {}, expected {}".format(chksum, compare))

                # check frame cid2 flag
                cid2 = data[7:9]
                if cid2 != b"00":
                    logger.debug("frame error flag (cid2) set, expected expected b'00', got: {}, ".format(cid2))
                    return False
                logger.debug("frame error flag (cid2) ok, got: {}".format(cid2))

                return True

            # catch corrupted frames
            except UnicodeError:
                logger.debug("frame corrupted, got: {}".format(data))
                return False
            # catch non-hexadecimal numbers
            except ValueError:
                logger.debug("frame has non-hexadecimal number, got: {}".format(data))
                return False

        # calculate info length checksum
        @staticmethod
        def get_info_length(info: bytes) -> int:
            lenid = len(info)
            if lenid == 0:
                return 0

            lchksum = (lenid & 0xF) + ((lenid >> 4) & 0xF) + ((lenid >> 8) & 0xF)
            lchksum %= 16
            lchksum ^= 0xF
            lchksum += 1

            return (lchksum << 12) + lenid

        # calculate command to send for each battery_pack using its address
        def encode_cmd(self, address: int, cid2: int = None, info: bytes = b"01") -> bytes:
            """encodes a command sent to a battery (cid1=0x46)"""
            cid1 = 0x46

            info_length = self.get_info_length(info)

            frame = "{:02X}{:02X}{:02X}{:02X}{:04X}".format(
                0x20, address, cid1, cid2, info_length
            ).encode()
            frame += info

            checksum = self.calculate_frame_checksum(frame)
            encoded = b"~" + frame + "{:04X}".format(checksum).encode() + b"\r"
            return encoded

        # get cell with the lowest voltage
        def get_min_cell(self) -> dict:
            min_cell = self.telemetry.cell_voltage.index(min(self.telemetry.cell_voltage))
            min_cell_voltage = self.telemetry.cell_voltage[min_cell]
            return { "min_cell": min_cell, "min_cell_voltage": min_cell_voltage }

        # get cell with the highest voltage
        def get_max_cell(self) -> dict:
            max_cell = self.telemetry.cell_voltage.index(max(self.telemetry.cell_voltage))
            max_cell_voltage = self.telemetry.cell_voltage[max_cell]
            return { "max_cell": max_cell, "max_cell_voltage": max_cell_voltage }

        # decode battery pack telemetry feedback frame
        def decode_telemetry_feedback_frame(self, data) -> dict:
                telemetry_feedback = {}

                # number of cells
                number_of_cells = self.int_from_1byte_hex_ascii(data=data, offset=4)

                # data offsets
                cell_voltage_offset = 6
                temps_offset = 72
                dis_charge_current_offset = 96
                total_pack_voltage_offset = 100
                residual_capacity_offset = 104
                battery_capacity_offset = 110
                soc_offset = 114
                rated_capacity_offset = 118
                cycles_offset = 122
                soh_offset = 126
                port_voltage_offset = 130

                self.telemetry.min_pack_voltage = MIN_CELL_VOLTAGE * number_of_cells
                self.telemetry.max_pack_voltage = MAX_CELL_VOLTAGE * number_of_cells

                # set min and max pack voltage
                telemetry_feedback["min_pack_voltage"] = self.telemetry.min_pack_voltage
                telemetry_feedback["max_pack_voltage"] = self.telemetry.max_pack_voltage


                # get voltages for each cell
                for i in range(number_of_cells):
                    voltage = (
                        self.int_from_2byte_hex_ascii(data, cell_voltage_offset + i * 4) / 1000
                    )
                    self.telemetry.cell_voltage[i] = voltage
                    # shift cell-index on return List by 1
                    tmp_key = f"voltage_cell_{i + 1}"
                    telemetry_feedback[tmp_key] = voltage

                # calculate average cell voltage
                self.telemetry.average_cell_voltage = round((sum(self.telemetry.cell_voltage) / len(self.telemetry.cell_voltage)), 3)
                telemetry_feedback["average_cell_voltage"] = self.telemetry.average_cell_voltage

                # get lowest cell and its voltage
                lowest_cell_data = self.get_min_cell()
                self.telemetry.lowest_cell = lowest_cell_data['min_cell']
                # shift cell-index on return List by 1
                telemetry_feedback["lowest_cell"] = self.telemetry.lowest_cell + 1
                self.telemetry.lowest_cell_voltage = lowest_cell_data['min_cell_voltage']
                telemetry_feedback["lowest_cell_voltage"] = self.telemetry.lowest_cell_voltage

                # get lowest cell and its voltage
                highest_cell_data = self.get_max_cell()
                self.telemetry.highest_cell = highest_cell_data["max_cell"]
                # shift cell-index on return List by 1
                telemetry_feedback["highest_cell"] = self.telemetry.highest_cell + 1
                self.telemetry.highest_cell_voltage = highest_cell_data["max_cell_voltage"]
                telemetry_feedback["highest_cell_voltage"] = self.telemetry.highest_cell_voltage

                # calculate delta cell voltage
                self.telemetry.delta_cell_voltage = round((self.telemetry.highest_cell_voltage - self.telemetry.lowest_cell_voltage), 3)
                telemetry_feedback["delta_cell_voltage"] = self.telemetry.delta_cell_voltage

                # get values for the 4 existing cell-temperature sensors
                for i in range(0, 4):
                    temp = (self.int_from_2byte_hex_ascii(data, temps_offset + i * 4) - 2731) / 10
                    self.telemetry.cell_temperature[i] = temp
                    # shift cell-index on return List by 1
                    tmp_key = f"cell_temperature_{i + 1}"
                    telemetry_feedback[tmp_key] = temp

                # get ambient temperature
                self.telemetry.ambient_temperature = (self.int_from_2byte_hex_ascii(data, temps_offset + 4 * 4) - 2731) / 10
                telemetry_feedback["ambient_temperature"] = self.telemetry.ambient_temperature

                # get components temperature
                self.telemetry.components_temperature = (self.int_from_2byte_hex_ascii(data, temps_offset + 5 * 4) - 2731) / 10
                telemetry_feedback["components_temperature"] = self.telemetry.components_temperature

                # get dis-/charge current
                self.telemetry.dis_charge_current = self.int_from_2byte_hex_ascii(data, dis_charge_current_offset, signed=True) / 100
                telemetry_feedback["dis_charge_current"] = self.telemetry.dis_charge_current

                # get total pack-voltage
                self.telemetry.total_pack_voltage = self.int_from_2byte_hex_ascii(data, total_pack_voltage_offset) / 100
                telemetry_feedback["total_pack_voltage"] = self.telemetry.total_pack_voltage

                # calculate dis-/charge_power
                self.telemetry.dis_charge_power = round((self.telemetry.dis_charge_current * self.telemetry.total_pack_voltage), 3)
                telemetry_feedback["dis_charge_power"] = self.telemetry.dis_charge_power

                # get rated capacity
                self.telemetry.rated_capacity = self.int_from_2byte_hex_ascii(data, rated_capacity_offset) / 100
                telemetry_feedback["rated_capacity"] = self.telemetry.rated_capacity

                # get battery capacity
                self.telemetry.battery_capacity = self.int_from_2byte_hex_ascii(data, battery_capacity_offset) / 100
                telemetry_feedback["battery_capacity"] = self.telemetry.battery_capacity

                # get remaining capacity
                self.telemetry.residual_capacity = self.int_from_2byte_hex_ascii(data, residual_capacity_offset) / 100
                telemetry_feedback["residual_capacity"] = self.telemetry.residual_capacity

                # get soc
                self.telemetry.soc = self.int_from_2byte_hex_ascii(data, soc_offset) / 10
                telemetry_feedback["soc"] = self.telemetry.soc

                # get cycles
                self.telemetry.cycles = self.int_from_2byte_hex_ascii(data, cycles_offset)
                telemetry_feedback["cycles"] = self.telemetry.cycles

                # get soh
                self.telemetry.soh = self.int_from_2byte_hex_ascii(data, soh_offset) / 10
                telemetry_feedback["soh"] = self.telemetry.soh

                # get port voltage
                self.telemetry.port_voltage = self.int_from_2byte_hex_ascii(data, port_voltage_offset) / 100
                telemetry_feedback["port_voltage"] = self.telemetry.port_voltage

                return telemetry_feedback

        # read data for given battery_pack address from serial interface
        def read_serial_data(self, serial_instance):
            logger.info("Fetch data for Battery Pack {}".format(self.pack_address))

            # json object to store status and alarm response values
            battery_pack_data = {
                "telemetry": {},
                "telesignalization": {}
            }

            # flush interface in- and output
            serial_instance.flushOutput()
            serial_instance.flushInput()

            # calculate request telemetry command (0x42) for the current pack_address
            telemetry_command = self.encode_cmd(address=self.pack_address, cid2=0x42)
            logger.debug("telemetry_command: {}".format(telemetry_command))

            # loop over responses until a valid frame is received, then decode and return it as json
            telemetry_command_iteration = 1
            while True:
                # (re-)send telemetry_command to the serial port until a response is received
                if telemetry_command_iteration == 1 or telemetry_command_iteration % 5 == 0:
                    serial_instance.write(telemetry_command)

                # set EOL to \r
                raw_data = serial_instance.read_until(b'\r')
                data = raw_data[13 : -5]

                # check if data is valid frame
                if self.is_valid_length(data, expected_length=150) and self.is_valid_hex_string and self.is_valid_frame(raw_data):
                    telemetry_feedback = self.decode_telemetry_feedback_frame(data)
                    battery_pack_data["telemetry"] = telemetry_feedback
                    logger.info("Battery-Pack {} Telemetry Feedback: {}".format(self.pack_address, json.dumps(telemetry_feedback, indent=4)))
                    break

            # calculate request telesignalization command (0x44) for the current pack_address
            telesignalization_command = self.encode_cmd(address=self.pack_address, cid2=0x44)
            logger.debug("telesignalization_command: {}".format(telesignalization_command))

            # loop over responses until a valid frame is received, then decode and return it as json
            telesignalization_command_iteration = 1
            while True:
                # (re-)send telesignalization_command to the serial port until a response is received
                if telesignalization_command_iteration == 1 or telesignalization_command_iteration % 5 == 0:
                    serial_instance.write(telesignalization_command)

                # set EOL to \r
                raw_data = serial_instance.read_until(b'\r')
                data = raw_data[13 : -5]

                # check if data is valid frame
                if self.is_valid_length(data, expected_length=98) and self.is_valid_hex_string and self.is_valid_frame(raw_data):
                    telesignalization_feedback = self.decode_telesignalization_feedback_frame(data)
                    battery_pack_data["telesignalization"] = telesignalization_feedback
                    logger.info("Battery-Pack {} Telesignalization feedback: {}".format(self.pack_address, json.dumps(telesignalization_feedback, indent=4)))
                    break

            # keep current stats to check if they changed before returning
            if not self.last_status:
                self.last_status = battery_pack_data
            elif self.last_status == battery_pack_data:
                return False
            else:
                self.last_status = battery_pack_data
            return battery_pack_data

    # connect mqtt client and start the loop
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
    except MQTTException as e:
        logger.error(f"MQTTException occurred: {e}")
        sys.exit(1)

    # connect serial interface
    try:
        serial_instance = serial.Serial(SERIAL_INTERFACE, SERIAL_BAUD_RATE)
    except SerialException as e:
        logger.error(f"SerialException occurred: {e}")
        sys.exit(1)

    # array of battery-pack objects
    battery_packs = []

    # fill battery_packs array with one (ONLY_MASTER = true) or multiple pack(s)
    if ONLY_MASTER:
        battery_packs.append({"address": 0, "instance": SeplosBatteryPack(0)})
    else:
        for i in range(1, NUMBER_OF_PACKS + 1):
            address = int(f'0x{i:02x}', 16)
            instance = SeplosBatteryPack(address)
            battery_packs.append({"address": address, "instance": instance})

    # fetch battery-pack Telemetry and Telesignalization data
    i = 0
    while True:
        current_battery_pack = battery_packs[i]["instance"]
        stats = current_battery_pack.read_serial_data(serial_instance)

        if stats:
            logger.info("Sending stats to MQTT")
            topic = f"{MQTT_TOPIC}/pack-{i + 1 if not ONLY_MASTER else 0}/sensors"
            mqtt_client.publish(topic, json.dumps(stats, indent=4))
        else:
            logger.info("Stats have not changed. No update required.")

        # query all packs again after defined time
        i += 1
        if i >= len(battery_packs):
            time.sleep(MQTT_UPDATE_INTERVAL)
            i = 0

# handle keyboard-interruption
except KeyboardInterrupt:
    logger.info("Interrupt received! Cleaning up...")

finally:
    # close mqtt client if connected
    if mqtt_client.is_connected:
        logger.info("disconnecting mqtt client")
        mqtt_client.disconnect()
        mqtt_client.loop_stop()

    # close serial connection if open
    if serial_instance:
        logger.info("Closing serial connection")
        serial_instance.close()
    logger.info("Exiting the program.")
    sys.exit(0)
