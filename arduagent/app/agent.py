import json  # noqa: D100
import math
import time
import traceback
from typing import Any

import netifaces
import searchers
from config import AgentConfig
from dronekit import Vehicle
from mavlink_handler import Mavlink
from mqtt_handler import Mqtt, TaskStatus
from paho.mqtt.client import MQTTMessage


class Agent:
    def __init__(self, mqtt_ref: Mqtt, mav_ref: Mavlink) -> None:
        """Initialize an Agent instance."""
        self.boot_time = time.time()

        self.mqtt = mqtt_ref
        self.mav = mav_ref

        self.use_collision_avoidance = True

        self.cargo_collection: list = []

        self.callbacks_mavlink()
        self.callbacks_mqtt()
        self.callbacks_mqtt_positions()
        self.callbacks_obstacle_distances()
        self.callbacks_rc_override()

        self.tuuid = "UNKNOWN"
        self.cuuid = "UNKNOWN"

        self.mav.set_auto_arm(AgentConfig.REAL_SIM == "simulation")

        self.pos_front_topic: str = "waraps/unit/"
        self.pos_end_topic: str = "/sensor/position"

        self.follow_lead_name: str = None

        self.ca_front_topic: str = f"{self.pos_front_topic}{AgentConfig.DOMAIN}/{AgentConfig.REAL_SIM}/"
        self.ca_end_topic: str = self.pos_end_topic

        self.fl_front_topic: str = self.pos_front_topic
        self.fl_end_topic: str = self.pos_end_topic

        self.did_ca_manouver_before = False

        self.horizontal_offset_meters = 10.0
        self.vertical_offset_meters = self.horizontal_offset_meters
        self.horizontal_offset_degrees = 180.0

        self.obstacles: list = []

        self.concurrent_commands: list = [
            "set-speed",
            "reset-speed",
            "set-heading-thrust",
            "release",
        ]

    # MAVLINK (VEHICLE) CALLBACKS ======================================================

    def callbacks_mavlink(self) -> None:
        self.mav.vehicle.add_message_listener(
            "HEARTBEAT", self.heartbeat_callback
        )
        self.mav.vehicle.add_message_listener(
            "COMMAND_ACK", self.command_ack_callback
        )
        self.mav.vehicle.add_message_listener(
            "MISSION_ITEM_REACHED", self.mission_item_reached_callback
        )
        
        self.mav.vehicle.add_message_listener(
            "SYSTEM_TIME", self.system_time_callback
        )

        self.mav.vehicle.add_attribute_listener(
            "EXTENDED_SYS_STATE", self.sys_state_callback
        )
        self.mav.vehicle.add_attribute_listener(
            "location.global_frame", self.global_frame_callback
        )
        self.mav.vehicle.add_attribute_listener(
            "location.global_relative_frame",
            self.global_relative_frame_callback,
        )
        self.mav.vehicle.add_attribute_listener(
            "groundspeed", self.groundspeed_callback
        )
        self.mav.vehicle.add_attribute_listener(
            "heading", self.heading_callback
        )
        self.mav.vehicle.add_attribute_listener(
            "velocity", self.velocity_callback
        )
        self.mav.vehicle.add_attribute_listener(
            "armable", self.armable_callback
        )
        self.mav.vehicle.add_attribute_listener("armed", self.arm_callback)
        self.mav.vehicle.add_attribute_listener("mode", self.mode_callback)
        self.mav.vehicle.add_attribute_listener(
            "battery", self.battery_callback
        )

    def heartbeat_callback(self, vehicle: Vehicle, name, value) -> None:
        if self.mav.is_valid_vehicle_type(value.type):
            if self.mav.vehicle_type != value.type:
                self.mav.vehicle_type = value.type
                
    def system_time_callback(self, vehicle: Vehicle, name, value) -> None:
        self.mav.clock = float(value.time_unix_usec / 1e6)
        self.mqtt.send_clock(self.mav.clock)

    def command_ack_callback(self, vehicle: Vehicle, name, value) -> None:
        hrm: dict = self.mav.decode_command_ack(value)

        cmd: str = str(hrm["command"].replace("MAV_CMD_", ""))
        res: str = str(hrm["result"].replace("MAV_RESULT_", ""))
        info: str = f"{cmd}:{res}"

    def mission_item_reached_callback(
        self, vehicle: Vehicle, name, value
    ) -> None:
        last_item_index: int = self.mav.vehicle.commands.count
        last_item_reached: int = int(value.seq)

        has_mission: bool = last_item_index > 0

        self.mav.mission_done = (
            has_mission and last_item_reached >= last_item_index
        )
        self.mav.on_mission = has_mission and not self.mav.mission_done

        if self.mav.is_mission_done() and not self.mav.is_on_mission():  # noqa: SIM102
            # this is done only to be able to set the mission to "stopped" mode.
            if self.mav.paus_mission():
                # if self.mav.stop_mission():
                self.mqtt.send_response(
                    TaskStatus.FINISHED, self.tuuid, self.cuuid
                )
                self.mqtt.send_feedback(TaskStatus.FINISHED, self.tuuid)

    def sys_state_callback(self, vehicle: Vehicle, name, value) -> None:
        self.mav.landed_state = value.landed_state

    def global_frame_callback(self, vehicle: Vehicle, name, value) -> None:
        """Callback for position."""
        if value:
            pos_arr: list = [value.lat, value.lon, value.alt]
            # self.mav.current_altitude_global = value.alt
            self.mqtt.send_position(pos_arr)

            if self.mav.is_on_mission() and not self.is_following_lead():
                intension: list = self.mav.get_waypoints_global()

                if len(intension) == 0 and self.mav.is_heading_thrust():
                    intension.append(pos_arr)
                    intension.append(self.mav.get_heading_thrust_waypoint())
                else:
                    intension.insert(0, pos_arr)

                self.mqtt.send_waypoints(intension)

    def global_relative_frame_callback(
        self, vehicle: Vehicle, name, value
    ) -> None:
        """Callback for position."""
        if value:
            self.mav.current_altitude_relative = value.alt

    def groundspeed_callback(self, vehicle, name, value) -> None:
        """Groundspeed callback."""
        self.mav.sog_mps = round(value, 2)
        self.mqtt.send_speed(self.mav.sog_mps)

    def heading_callback(self, vehicle, name, value) -> None:
        """Heading callback."""
        self.mqtt.send_heading(value)

    def velocity_callback(self, vehicle, name, value) -> None:
        """Course callback."""
        vx, vy, _ = value
        cog_deg = math.degrees(math.atan2(vy, vx))

        if cog_deg < 0:
            cog_deg += 360.0

        self.mav.cog_deg = round(cog_deg, 1)
        self.mqtt.send_course(self.mav.cog_deg)

    def battery_callback(self, vehicle, name, value) -> None:
        """Battery/Energy left callback."""
        self.mqtt.send_energy_level(value.level)
        self.mqtt.send_battery_status(
            {
                "voltage": value.voltage,
                "current": value.current,
                "level": value.level,
            }
        )

    # This callback does not work and I do not know why.
    def arm_callback(self, vehicle, name, value) -> None:
        """Arm callback."""
        self.mqtt.send_state(value)
        self.mqtt.send_info(value)

    def armable_callback(self, vehicle, name, value) -> None:
        """Armable callback."""
        if value:
            self.mqtt.send_info("Vehicle is armable")
        else:
            self.mqtt.send_info("Vehicle is not armable")

    def mode_callback(self, vehicle, name, mode) -> None:
        """Change mode callback."""
        try:
            if mode.name == "LOIT_UNLIM":
                print(
                    "MY LOITER NOW ==============================================="
                )

            if self.mav.is_manual():
                self.mqtt.send_feedback(TaskStatus.PILOT_TAKEOVER, self.tuuid)

            elif self.mav.is_auto() or self.mav.is_guided():
                self.mav.apply_task_speed()
                self.mqtt.send_feedback(TaskStatus.RUNNING, self.tuuid)

            elif self.mav.is_paused():
                self.mqtt.send_feedback(TaskStatus.PAUSED, self.tuuid)

            elif self.mav.is_stopped():
                self.mqtt.send_feedback(TaskStatus.FINISHED, self.tuuid)
                self.mqtt.send_waypoints(None)

            else:
                self.mqtt.send_info(mode.name)

            state = self.mav.get_state_name()
            info: str = f"{state}:{mode.name}"

            self.mqtt.send_info(info)

        except Exception:
            print(traceback.format_exc())

    # MQTT (C2) CALLBACKS ==============================================================

    def callbacks_mqtt(self) -> None:
        """Callbacks for commands from, e.g. C2, on MQTT Broker."""
        topic = f"{AgentConfig.COMMAND_TOPIC}"
        print(f"Registering command mqtt callback on {topic} ...")
        self.mqtt.mqtt_connection.client.on_message = self.receive_command
        self.mqtt.mqtt_connection.client.subscribe(topic, qos=1)

    def callbacks_mqtt_positions(self) -> None:
        """Callbacks for other agent positions."""
        topic = f"{AgentConfig.OTHER_POSITIONS_TOPIC}"

        print(
            f"Registering other agents positions mqtt callback on {topic} ..."
        )
        self.mqtt.mqtt_connection.client.subscribe(topic, qos=0)

    def callbacks_obstacle_distances(self) -> None:
        """Callbacks for obstacle distances."""
        topic = f"{AgentConfig.OBSTACLE_DISTANCES_TOPIC}"

        print(
            f"Registering to obstacle distances mqtt callback on {topic} ..."
        )
        self.mqtt.mqtt_connection.client.subscribe(topic, qos=0)
        
    def callbacks_rc_override(self) -> None:
        """Callbacks for RC overrides."""
        topic = f"{AgentConfig.RC_OVERRIDE_TOPIC}"
        print(f"Registering rc override mqtt callback on {topic} ...")
        self.mqtt.mqtt_connection.client.subscribe(topic, qos=0)

    def set_follow_lead(self, name):
        self.follow_lead_name = name
        if self.mav.is_ground() or self.mav.is_surface():
            self.horizontal_offset_meters = 2.0
            self.vertical_offset_meters = 0.0
            self.horizontal_offset_degrees = 180.0
        elif self.mav.is_rotary():
            self.horizontal_offset_meters = 5.0
            self.vertical_offset_meters = 10.0
            self.horizontal_offset_degrees = 180.0
        elif self.mav.is_fixed_wing():
            self.horizontal_offset_meters = 20.0
            self.vertical_offset_meters = 40.0
            self.horizontal_offset_degrees = 180.0
        elif self.mav.is_subsurface():
            self.horizontal_offset_meters = 0.0
            self.vertical_offset_meters = -2.0
            self.horizontal_offset_degrees = 180.0

    def reset_follow_lead(self):
        self.initial_pos_follow_me_sent = False
        self.set_follow_lead(None)

    def is_following_lead(self):
        return self.follow_lead_name != None

    def clear_mission(self):
        self.reset_follow_lead()
        return self.mav.clear_mission()

    def stop_mission(self):
        self.reset_follow_lead()
        self.mav.reset_heading_thrust()
        return self.mav.stop_mission()

    def receive_command(self, client : Any, userdata : Any, msg : MQTTMessage) -> None:
        """Broker subscribe callback.

        Args:
        ----
            client: The client instance.
            userdata: The private user data as set in Client() or userdata_set().
            msg: An instance of MQTTMessage. This is a class with members topic, payload, qos, retain.
        """
        msg_topic_str = str(msg.topic)

        if msg.topic == AgentConfig.COMMAND_TOPIC:
            try:
                # If someone sends a "null" command or removes a command on broker
                if not msg.payload:
                    err_msg: str = "No command/signal received"
                    self.mqtt.send_response(
                        TaskStatus.FAILED, None, None, err_msg
                    )
                    print(f"{err_msg}")
                    return

                msg_json = json.loads(msg.payload.decode("utf-8"))

                if msg_json["command"] == "start-task":
                    task_name = msg_json["task"]["name"]
                    self.tuuid = msg_json["task-uuid"]
                    self.cuuid = msg_json["com-uuid"]

                    self.mqtt.send_response(
                        TaskStatus.RUNNING, self.tuuid, self.cuuid
                    )

                    if not self.mav.is_armable():
                        err_msg: str = "Not ready - Pre tests"
                        self.mqtt.send_response(
                            TaskStatus.FAILED,
                            self.tuuid,
                            self.cuuid,
                            err_msg,
                        )
                        print(f"{err_msg}")
                        return

                    if not self.mav.is_armed() and not self.mav.is_auto_armed():
                        err_msg: str = "Not armed - Manual"
                        self.mqtt.send_response(
                            TaskStatus.FAILED,
                            self.tuuid,
                            self.cuuid,
                            err_msg,
                        )
                        print(f"{err_msg}")
                        return

                    if (
                        self.mav.is_armed()
                        and task_name not in self.concurrent_commands
                    ):
                        if self.mav.is_on_mission():
                            # if self.mav.is_armed() and self.mav.is_busy():
                            err_msg: str = "Occupied"
                            self.mqtt.send_response(
                                TaskStatus.FAILED,
                                self.cuuid,
                                self.tuuid,
                                err_msg,
                            )
                            print(f"{err_msg}")
                            return

                        if self.is_following_lead():
                            err_msg: str = "Occupied - Following lead"
                            self.mqtt.send_response(
                                TaskStatus.FAILED,
                                self.cuuid,
                                self.tuuid,
                                err_msg,
                            )
                            print(f"{err_msg}")
                            return

                    # print(f"CMD ¤¤¤¤ msg: {task_name}")
                    if task_name == "move-to":
                        self.mqtt.send_feedback(TaskStatus.STARTING, self.tuuid)

                        lat = msg_json["task"]["params"]["waypoint"]["latitude"]
                        lon = msg_json["task"]["params"]["waypoint"][
                            "longitude"
                        ]
                        alt = msg_json["task"]["params"]["waypoint"]["altitude"]

                        wps: list = [[lat, lon, alt]]

                        spd = msg_json["task"]["params"]["speed"]

                        if not spd:
                            spd = "standard"

                        self.clear_mission()

                        self.mqtt.send_feedback(TaskStatus.PLANNING, self.tuuid)

                        # DO PLANNING HERE

                        self.mav.add_waypoints_to_mission_global(wps, spd)

                        self.mqtt.send_feedback(TaskStatus.RUNNING, self.tuuid)

                        # Guard access to waypoint altitude. If missing, fall back
                        # to a safe default: home altitude + minimum mission altitude
                        # (or the minimum mission altitude if home is unknown).
                        takeoff_altitude_global = None
                        try:
                            if (
                                wps
                                and isinstance(wps[0], (list, tuple))
                                and len(wps[0]) >= 3
                                and wps[0][2] is not None
                            ):
                                takeoff_altitude_global = float(wps[0][2])
                        except Exception:
                            takeoff_altitude_global = None

                        if takeoff_altitude_global is None:
                            home_alt = None
                            try:
                                home_alt = self.mav.vehicle.home_location.alt
                            except Exception:
                                home_alt = None

                            if home_alt is not None:
                                takeoff_altitude_global = (
                                    home_alt
                                    + self.mav.minimum_takeoff_altitude_relative
                                )
                            else:
                                takeoff_altitude_global = (
                                    self.mav.minimum_takeoff_altitude_relative
                                )

                        if self.mav.prepare_vehicle_global(
                            takeoff_altitude_global
                        ):
                            self.mav.on_mission = self.mav.start_mission("AUTO")
                        else:
                            self.mqtt.send_response(
                                TaskStatus.FAILED,
                                self.tuuid,
                                self.cuuid,
                                "Not prepared",
                            )
                            self.mqtt.send_feedback(
                                TaskStatus.FAILED, self.tuuid
                            )

                    elif task_name == "go-home":
                        self.mqtt.send_feedback(TaskStatus.STARTING, self.tuuid)

                        self.clear_mission()

                        self.mqtt.send_feedback(TaskStatus.PLANNING, self.tuuid)

                        # DO PLANNING HERE

                        self.mqtt.send_feedback(TaskStatus.RUNNING, self.tuuid)
                        if not self.mav.return_to_launch():
                            self.mqtt.send_response(
                                TaskStatus.FAILED,
                                self.tuuid,
                                self.cuuid,
                                "Not prepared",
                            )
                            self.mqtt.send_feedback(
                                TaskStatus.FAILED, self.tuuid
                            )

                    elif task_name == "move-path":
                        self.mqtt.send_feedback(TaskStatus.STARTING, self.tuuid)

                        spd = msg_json["task"]["params"]["speed"]

                        if not spd:
                            spd = "standard"
                        print("Mqtt speed: " + str(spd) + "m/s")
                        loop = msg_json["task"]["params"].get("loop", None)

                        if loop is None:
                            loop = 0
                        elif loop < 0:
                            loop = -1

                        self.clear_mission()

                        self.mqtt.send_feedback(TaskStatus.PLANNING, self.tuuid)

                        # DO PLANNING HERE

                        wps: list = []
                        for point in msg_json["task"]["params"]["waypoints"]:
                            lat = point["latitude"]
                            lon = point["longitude"]
                            alt = point["altitude"]

                            alt = max(
                                alt, self.mav.minimum_mission_altitude_relative
                            )

                            wps.append([lat, lon, alt])

                        # Add a DO_JUMP command to loop back to the first waypoint
                        if len(wps) > 0 and loop != 0:
                            jump_count = (
                                loop if loop > 0 else -1
                            )  # Number of times to repeat the loop, -1 => indefinite

                            print(f"Number of loops: {loop} => {jump_count}")

                        self.mav.add_waypoints_to_mission_global(wps, spd, loop)

                        self.mqtt.send_feedback(TaskStatus.RUNNING, self.tuuid)

                        # Guard access to waypoint altitude. If missing, fall back
                        # to a safe default: home altitude + minimum mission altitude
                        # (or the minimum mission altitude if home is unknown).
                        takeoff_altitude_global = None
                        try:
                            if (
                                wps
                                and isinstance(wps[0], (list, tuple))
                                and len(wps[0]) >= 3
                                and wps[0][2] is not None
                            ):
                                takeoff_altitude_global = float(wps[0][2])
                        except Exception:
                            takeoff_altitude_global = None

                        if takeoff_altitude_global is None:
                            home_alt = None
                            try:
                                home_alt = self.mav.vehicle.home_location.alt
                            except Exception:
                                home_alt = None

                            if home_alt is not None:
                                takeoff_altitude_global = (
                                    home_alt
                                    + self.mav.minimum_mission_altitude_relative
                                )
                            else:
                                takeoff_altitude_global = (
                                    self.mav.minimum_mission_altitude_relative
                                )

                        if self.mav.prepare_vehicle_global(
                            takeoff_altitude_global
                        ):
                            self.mav.on_mission = self.mav.start_mission("AUTO")
                        else:
                            self.mqtt.send_response(
                                TaskStatus.FAILED,
                                self.tuuid,
                                self.cuuid,
                                "Not prepared",
                            )
                            self.mqtt.send_feedback(
                                TaskStatus.FAILED, self.tuuid
                            )

                    elif task_name == "search-area":
                        self.mqtt.send_feedback(TaskStatus.STARTING, self.tuuid)

                        spd = msg_json["task"]["params"]["speed"]
                        tse = msg_json["task"]["params"]["target-size"]
                        tty = msg_json["task"]["params"]["target-type"]

                        if not spd:
                            spd = "standard"

                        if not tse:
                            tse = 1.7

                        if not tty:
                            tty = "person"

                        self.mav.configure_task_speed(spd)

                        home_alt: float = self.mav.vehicle.home_location.alt
                        search_alt_rel: float = 2.0
                        search_alt_abs: float = search_alt_rel + home_alt
                        spacing_meters: float = 5.0

                        if self.mav.is_air():
                            # The below calculations of search altitude SHOULD be dependent on
                            # Ground Zero altitude and not the home altitude in the future
                            search_alt_rel = tse * 10.0
                            spacing_meters: float = (
                                self.mav.get_spacing_for_coverage(
                                    100, search_alt_rel
                                )
                            )

                            search_alt_rel = max(
                                search_alt_rel,
                                self.mav.minimum_mission_altitude_relative,
                            )

                            search_alt_abs = search_alt_rel + home_alt

                        print(
                            f"Search altitude rel/abs: {search_alt_rel=} {search_alt_abs=} Home alt:{home_alt}"
                        )

                        self.clear_mission()

                        self.mqtt.send_feedback(TaskStatus.PLANNING, self.tuuid)

                        # DO PLANNING HERE

                        wps_area: list = []
                        for point in msg_json["task"]["params"]["area"]:
                            lat = round(float(point["latitude"]), 7)
                            lon = round(float(point["longitude"]), 7)
                            # alt = point["altitude"]

                            wps_area.append(
                                [lat, lon, round(float(search_alt_abs), 7)]
                            )

                        search: None
                        search_type: str = None

                        if tty == "person":
                            search_type = "SPIRAL"
                        elif tty == "car":
                            search_type = "HULL"
                        else:
                            search_type = "GRID"

                        if search_type == "SPIRAL":
                            search: searchers.SpiralSearch = (
                                searchers.SpiralSearch()
                            )
                        elif search_type == "HULL":
                            search: searchers.HullSearch = (
                                searchers.HullSearch()
                            )
                        else:
                            search: searchers.GridSearch = (
                                searchers.GridSearch()
                            )

                        wps: list = search.calculate_search_pattern(
                            wps_area, spacing_meters, search_alt_rel
                        )

                        print(f"Search pattern has {len(wps)} waypoints")

                        if len(wps) == 0:
                            self.mqtt.send_info("Search pattern has no WPs")
                            return

                        if len(wps) > 600:
                            self.mqtt.send_info(
                                f"Search pattern to large {len(wps)}"
                            )
                            return

                        # Pre show search path
                        self.mqtt.send_waypoints(wps)
                        time.sleep(3)

                        # self.mav.add_waypoints_to_mission_global(wps, spd)
                        self.mav.add_waypoints_to_mission_relative(wps, spd)
                        self.mqtt.send_feedback(TaskStatus.RUNNING, self.tuuid)

                        if self.mav.prepare_vehicle_relative(search_alt_rel):
                            self.mav.on_mission = self.mav.start_mission("AUTO")
                        else:
                            self.mqtt.send_response(
                                TaskStatus.FAILED,
                                self.tuuid,
                                self.cuuid,
                                "Not prepared",
                            )
                            self.mqtt.send_feedback(
                                TaskStatus.FAILED, self.tuuid
                            )

                    elif task_name == "collect":
                        cargo = msg_json["task"]["params"]["cargo"]
                        self.mav.collect_cargo()

                        if cargo not in self.cargo_collection:
                            self.cargo_collection.append(cargo)

                        print(
                            f"Cargo {cargo} has been collected into the cargo_collection {self.cargo_collection}"
                        )

                        self.mqtt.send_cargo(self.cargo_collection)
                        self.mqtt.send_response(
                            TaskStatus.FINISHED, self.tuuid, self.cuuid
                        )
                        self.mqtt.send_feedback(TaskStatus.FINISHED, self.tuuid)

                    elif task_name == "release":
                        cargo = msg_json["task"]["params"]["cargo"]
                        self.mav.release_cargo()

                        if (
                            self.cargo_collection
                            and len(self.cargo_collection) > 0
                        ):
                            print("Releasing cargo:")
                            for item in self.cargo_collection:
                                print(f"    {item}")
                        else:
                            print("No cargo to release")

                        # release => remove all collected items
                        self.cargo_collection.clear()
                        self.mqtt.send_cargo(self.cargo_collection)
                        self.mqtt.send_response(
                            TaskStatus.FINISHED, self.tuuid, self.cuuid
                        )
                        self.mqtt.send_feedback(TaskStatus.FINISHED, self.tuuid)

                    elif task_name == "set-speed":
                        self.mqtt.send_feedback(TaskStatus.STARTING, self.tuuid)

                        spd = msg_json["task"]["params"]["speed"]

                        if not spd:
                            spd = "standard"

                        self.mav.configure_task_speed(spd)
                        self.mav.apply_task_speed()

                        self.mqtt.send_response(
                            TaskStatus.FINISHED, self.tuuid, self.cuuid
                        )
                        self.mqtt.send_feedback(TaskStatus.FINISHED, self.tuuid)

                    elif task_name == "reset-speed":
                        self.mqtt.send_feedback(TaskStatus.STARTING, self.tuuid)

                        self.mav.clear_speed_override()
                        self.mav.reset_speed()

                        self.mqtt.send_response(
                            TaskStatus.FINISHED, self.tuuid, self.cuuid
                        )
                        self.mqtt.send_feedback(TaskStatus.FINISHED, self.tuuid)

                    elif task_name == "follow-lead":
                        self.mqtt.send_feedback(TaskStatus.PLANNING, self.tuuid)

                        # UGLY for now, i.e. use the name of a point to infer a agent in the same domain
                        ref_point: str = msg_json["task"]["meta"]["reference"]
                        ref_leader: str = ref_point.removesuffix("-P")

                        spd = msg_json["task"]["params"]["speed"]

                        if not spd:
                            spd = "standard"

                        self.mav.configure_task_speed(spd)

                        # DO PLANNING HERE

                        if self.mav.prepare_vehicle_relative():
                            print(f"LEADER: {ref_leader}")
                            self.set_follow_lead(ref_leader)
                            self.mav.set_mode("GUIDED")
                            self.mav.apply_task_speed()
                            self.mqtt.send_feedback(
                                TaskStatus.RUNNING, self.tuuid
                            )
                        else:
                            self.mqtt.send_response(
                                TaskStatus.FAILED,
                                self.tuuid,
                                self.cuuid,
                                "Not prepared",
                            )
                            self.mqtt.send_feedback(
                                TaskStatus.FAILED, self.tuuid
                            )

                    elif task_name == "set-geofence":
                        self.mqtt.send_feedback(TaskStatus.PLANNING, self.tuuid)

                        spd = msg_json["task"]["params"]["speed"]

                        if not spd:
                            spd = "standard"

                        self.mav.configure_task_speed(spd)

                        self.mqtt.send_feedback(TaskStatus.PLANNING, self.tuuid)

                        # DO PLANNING HERE

                        wps: list = []
                        for point in msg_json["task"]["params"]["area"]:
                            lat = point["latitude"]
                            lon = point["longitude"]
                            # alt = point["altitude"]
                            wps.append([lat, lon])

                        # Insert the first point as the last to "close" the area
                        wps.append(wps[0])

                        if self.mav.set_geofence(wps):
                            # print(f"{self.mav.geofence=}")
                            self.mqtt.send_feedback(
                                TaskStatus.FINISHED, self.tuuid
                            )
                        else:
                            self.mqtt.send_response(
                                TaskStatus.FAILED,
                                self.tuuid,
                                self.cuuid,
                                "Could not set geofence",
                            )
                            self.mqtt.send_feedback(
                                TaskStatus.FAILED, self.tuuid
                            )

                    elif task_name == "add-no-go-zone":
                        self.mqtt.send_feedback(TaskStatus.PLANNING, self.tuuid)

                        wps: list = []
                        for point in msg_json["task"]["params"]["area"]:
                            lat = point["latitude"]
                            lon = point["longitude"]
                            # alt = point["altitude"]
                            wps.append([lat, lon])

                        # Insert the first point as the last to "close" the area
                        wps.append(wps[0])

                        if self.mav.add_to_no_go_zones(wps):
                            # print(f"{self.mav.no_go_zones=}")
                            self.mqtt.send_feedback(
                                TaskStatus.FINISHED, self.tuuid
                            )
                        else:
                            self.mqtt.send_response(
                                TaskStatus.FAILED,
                                self.tuuid,
                                self.cuuid,
                                "Could not add no-go-zone",
                            )
                            self.mqtt.send_feedback(
                                TaskStatus.FAILED, self.tuuid
                            )

                    elif task_name == "set-heading-thrust":
                        hdg: float = 0.0
                        thr: float = 0.0
                        ptc: float = 0.0

                        try:
                            hdg: float = msg_json["task"]["params"].get(
                                "heading", 0.0
                            )
                            thr: float = msg_json["task"]["params"].get(
                                "thrust", 0.0
                            )
                            # ptc: float = msg_json["task"]["params"].get("pitch", 0.0)

                        except Exception:
                            print(traceback.format_exc())

                        self.mqtt.send_feedback(TaskStatus.RUNNING, self.tuuid)

                        if not self.mav.is_guided():
                            if self.mav.prepare_vehicle_relative(
                                takeoff_altitude_relative
                            ) and self.mav.set_mode("GUIDED"):
                                self.mav.on_mission = self.mav.start_mission(
                                    "GUIDED"
                                )

                            else:
                                self.mqtt.send_response(
                                    TaskStatus.FAILED,
                                    self.tuuid,
                                    self.cuuid,
                                    "Not prepared",
                                )
                                self.mqtt.send_feedback(
                                    TaskStatus.FAILED, self.tuuid
                                )

                            return

                        self.mav.set_heading_thrust(hdg, thr)

                    else:
                        self.mqtt.send_response(
                            TaskStatus.FAILED,
                            self.tuuid,
                            self.cuuid,
                            "Task not supported",
                        )
                        self.mqtt.send_feedback(TaskStatus.FAILED, self.tuuid)

                elif msg_json["command"] == "signal-task":
                    if (
                        self.is_following_lead()
                        or self.mav.is_on_mission()
                        or self.mav.is_paused()
                    ):
                        # if self.current_task.task_uuid == task_uuid:
                        signal = msg_json["signal"]

                        if signal == "$abort":
                            if self.stop_mission():
                                self.mqtt.send_response(
                                    TaskStatus.ABORTED, self.tuuid, self.cuuid
                                )
                                self.mqtt.send_feedback(
                                    TaskStatus.FINISHED, self.tuuid
                                )
                            else:
                                self.mqtt.send_response(
                                    TaskStatus.FAILED,
                                    self.tuuid,
                                    self.cuuid,
                                    "Signal did not work",
                                )
                                self.mqtt.send_feedback(
                                    TaskStatus.FAILED, self.tuuid
                                )

                        elif signal == "$enough":
                            if self.stop_mission():
                                self.mqtt.send_response(
                                    TaskStatus.ENOUGH, self.tuuid, self.cuuid
                                )
                                self.mqtt.send_feedback(
                                    TaskStatus.FINISHED, self.tuuid
                                )
                            else:
                                self.mqtt.send_response(
                                    TaskStatus.FAILED,
                                    self.tuuid,
                                    self.cuuid,
                                    "Signal did not work",
                                )
                                self.mqtt.send_feedback(
                                    TaskStatus.FAILED, self.tuuid
                                )

                        elif signal == "$pause":
                            if self.mav.paus_mission():
                                self.mqtt.send_response(
                                    TaskStatus.RUNNING, self.tuuid, self.cuuid
                                )
                                self.mqtt.send_feedback(
                                    TaskStatus.PAUSED, self.tuuid
                                )
                            else:
                                self.mqtt.send_response(
                                    TaskStatus.FAILED,
                                    self.tuuid,
                                    self.cuuid,
                                    "Signal did not work",
                                )
                                self.mqtt.send_feedback(
                                    TaskStatus.FAILED, self.tuuid
                                )

                        elif signal == "$continue":
                            if self.mav.continue_mission():
                                self.mqtt.send_response(
                                    TaskStatus.RUNNING, self.tuuid, self.cuuid
                                )
                                self.mqtt.send_feedback(
                                    TaskStatus.RUNNING, self.tuuid
                                )
                            else:
                                self.mqtt.send_response(
                                    TaskStatus.FAILED,
                                    self.tuuid,
                                    self.cuuid,
                                    "Signal did not work",
                                )
                                self.mqtt.send_feedback(
                                    TaskStatus.FAILED, self.tuuid
                                )

                        else:
                            self.mqtt.send_response(
                                TaskStatus.FAILED,
                                self.tuuid,
                                self.cuuid,
                                f"{signal} is not supported",
                            )
                            self.mqtt.send_feedback(
                                TaskStatus.FAILED, self.tuuid
                            )

                    else:
                        self.mqtt.send_response(
                            TaskStatus.FAILED,
                            self.tuuid,
                            self.cuuid,
                            "No active command",
                        )
                        self.mqtt.send_feedback(TaskStatus.FAILED, self.tuuid)

                elif msg_json["command"] == "ping":
                    self.mqtt.send_response(
                        TaskStatus.PONG, self.tuuid, self.cuuid, TaskStatus.PING
                    )
                    self.mqtt.send_feedback(TaskStatus.PONG, self.tuuid)

                else:
                    self.mqtt.send_response(
                        TaskStatus.FAILED,
                        self.tuuid,
                        self.cuuid,
                        "Command not supported",
                    )
                    self.mqtt.send_feedback(TaskStatus.FAILED, self.tuuid)

            except json.decoder.JSONDecodeError:
                self.mqtt.send_response(
                    TaskStatus.FAILED,
                    self.tuuid,
                    self.cuuid,
                    "Malformed json command",
                )
                self.mqtt.send_feedback(TaskStatus.FAILED, self.tuuid)
                print(traceback.format_exc())

            except KeyError:
                self.mqtt.send_response(
                    TaskStatus.FAILED,
                    self.tuuid,
                    self.cuuid,
                    f"Key in json not found: {traceback.format_exc()}",
                )
                self.mqtt.send_feedback(TaskStatus.FAILED, self.tuuid)
                print(traceback.format_exc())

            except TimeoutError:
                self.mqtt.send_response(
                    TaskStatus.FAILED,
                    self.tuuid,
                    self.cuuid,
                    "Command time out",
                )
                self.mqtt.send_feedback(TaskStatus.FAILED, self.tuuid)
                print(traceback.format_exc())

            except Exception:
                self.mqtt.send_response(
                    TaskStatus.FAILED,
                    self.tuuid,
                    self.cuuid,
                    f"{traceback.format_exc()}",
                )
                self.mqtt.send_feedback(TaskStatus.FAILED, self.tuuid)
                print(traceback.format_exc())

        # Check if there is positions from other agents
        # Can be obstacle, own position or leader
        elif msg_topic_str.startswith(
            self.pos_front_topic
        ) and msg_topic_str.endswith(self.pos_end_topic):
            # Test payload for position object
            if not msg.payload:
                print(
                    f"Misformatted agent position of other agent: {msg.topic}"
                )

                return

            is_own: bool = self.is_own_topic(msg_topic_str)
            is_lead: bool = self.is_following_lead() and self.is_lead_topic(
                msg_topic_str
            )

            lat_other: float = None
            lon_other: float = None
            alt_other: float = None

            try:
                msg_json = json.loads(msg.payload.decode("utf-8"))
                lat_other = msg_json["latitude"]
                lon_other = msg_json["longitude"]
                alt_other = msg_json["altitude"]

            except Exception:
                print(f"{traceback.format_exc()}")

            # Test for a sound formatted postion object
            # Every other agent can be an obstacle, thresholded by 100 meters
            if lat_other and lon_other and alt_other:
                if not self.mav.is_ready_for_guidance():
                    return

                if is_own:
                    return

                if is_lead:
                    pos_lead: list = [lat_other, lon_other, alt_other]
                    lat_lead, lon_lead, alt_lead = (
                        self.mav.get_destination_position(
                            pos_lead,
                            self.horizontal_offset_meters,
                            self.horizontal_offset_degrees,
                            self.vertical_offset_meters,
                        )
                    )
                    if self.mav.validate_lat_lon_alt(
                        lat_lead, lon_lead, alt_lead
                    ):
                        self.mav.follow_lead_global(
                            lat_lead, lon_lead, alt_lead
                        )
                    #     print(
                    #         f"FINE: Could calculate lead point {lat_lead=} {lon_lead=} {alt_lead=}"
                    #     )
                    # else:
                    #     print(
                    #         f"ERROR: {lat_lead=} {lon_lead=} {alt_lead=} {pos_lead=} {self.horizontal_offset_meters} {self.horizontal_offset_degrees} {self.vertical_offset_meters}"
                    #     )
                    #     print(
                    #         f"ERROR: Could not calculate lead point {lat_lead=} {lon_lead=} {alt_lead=}"
                    #     )

                # Test for collision avoidance
                if (
                    self.use_collision_avoidance
                    and msg_topic_str.startswith(self.ca_front_topic)
                    and msg_topic_str.endswith(self.ca_end_topic)
                ):
                    executing_ca_manouver = False
                    data = self.obstacle_in_front(
                        lat_other, lon_other, alt_other, msg_topic_str
                    )
                    if data and len(data) >= 3:
                        executing_ca_manouver = (
                            self.do_collision_avoidance_manouver(data)
                        )

                    if (
                        not executing_ca_manouver
                        and self.did_ca_manouver_before
                    ):
                        self.mav.reset_speed()

                    self.did_ca_manouver_before = executing_ca_manouver
        elif msg_topic_str == AgentConfig.OBSTACLE_DISTANCES_TOPIC:
            try:
                msg_json = json.loads(msg.payload.decode("utf-8"))
                distances = list(msg_json["distances"])
                increment = int(msg_json["increment"])
                min_distance = float(msg_json["min_distance"])
                max_distance = float(msg_json["max_distance"])
                self.mav.send_obstacle_distances(distances, increment, min_distance, max_distance)
            except Exception:
                print(f"{traceback.format_exc()}")
        elif msg_topic_str == AgentConfig.RC_OVERRIDE_TOPIC:
            try:
                msg_json = json.loads(msg.payload.decode("utf-8"))
                left_pwm = msg_json["left_pwm"]
                right_pwm = msg_json["right_pwm"]
                self.mav.send_rc_override(left_pwm, right_pwm)
            except Exception:
                print(f"{traceback.format_exc()}")

    # HELPERS ==========================================================================

    def is_own_topic(self, topic_str: str = None) -> bool:
        return topic_str and topic_str.startswith(AgentConfig.BASE_TOPIC)

    def is_lead_topic(self, topic_str: str = None) -> bool:
        if topic_str and self.follow_lead_name:
            search_str: str = "/" + self.follow_lead_name + "/"

            return search_str in str(topic_str)
        return False

    def terminate(self) -> None:
        """Terminate the agent by disconnecting from the Pixhawk and MQTT."""
        self.mqtt.terminate()
        self.mav.terminate()

    def get_local_ip(self) -> str:
        interface_priority = {
            "vpn": [],
            "ethernet": [],
            "wifi": [],
            "mobile": [],
        }

        # Classify interfaces by type
        for interface in netifaces.interfaces():
            try:
                # Get the addresses associated with the interface
                addresses = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addresses:
                    # Check interface type based on name patterns
                    if interface.startswith("tun"):
                        interface_priority["vpn"].append(interface)
                    elif interface.startswith(("en", "eth")):
                        interface_priority["ethernet"].append(interface)
                    elif interface.startswith("wl"):
                        interface_priority["wifi"].append(interface)
                    elif interface.startswith("ppp"):
                        interface_priority["mobile"].append(interface)
            except ValueError:
                continue

        # Check interfaces based on priority
        for category in ["vpn", "ethernet", "wifi", "mobile"]:
            for interface in interface_priority[category]:
                try:
                    addresses = netifaces.ifaddresses(interface)
                    if netifaces.AF_INET in addresses:
                        ip_info = addresses[netifaces.AF_INET][0]
                        ip_addr = ip_info["addr"]
                        # print(f"Found local IP {interface} => {ip_addr}")
                        return ip_addr
                except KeyError:
                    continue

        return None

    def obstacle_in_front(
        self,
        lat_other: float,
        lon_other: float,
        alt_other: float,
        top_other: str,
    ) -> float:
        distance_to_other: float = self.mav.get_horizontal_distance_to_own(
            lat_other, lon_other
        )

        bearing_to_other: float = self.mav.get_bearing_to_other(
            lat_other, lon_other
        )

        ca_warning: bool = False
        tolerance_deg: float = 10.0

        if self.mav.cog_deg and distance_to_other and bearing_to_other:
            left_bound = (self.mav.cog_deg - tolerance_deg + 360) % 360
            right_bound = (self.mav.cog_deg + tolerance_deg + 360) % 360

            if left_bound <= right_bound:
                ca_warning = left_bound <= bearing_to_other <= right_bound
            else:
                ca_warning = (
                    bearing_to_other >= left_bound
                    or bearing_to_other <= right_bound
                )

            if ca_warning:
                if self.mav.sog_mps != 0:
                    seconds_to_other = distance_to_other / self.mav.sog_mps
                else:
                    seconds_to_other = 999

                return [
                    round(distance_to_other, 2),
                    round(bearing_to_other, 2),
                    round(seconds_to_other, 1),
                    top_other,
                ]

        return []

    def do_collision_avoidance_manouver(self, data: list) -> int:
        distance_to_other, bearing_to_other, seconds_to_other, top_other = data

        warning_seconds: float = 10.0
        stop_seconds: float = 3.0
        stop_meters_min: float = 2.0

        if distance_to_other < stop_meters_min or (
            seconds_to_other
            and seconds_to_other >= 0
            and seconds_to_other < stop_seconds
        ):
            self.mav.set_speed(0)
            self.mqtt.send_info(f"CA STOP: {distance_to_other}m")

        elif seconds_to_other >= 0 and seconds_to_other < warning_seconds:
            max_speed: float = self.mav.get_max_speed()

            ca_speed = (
                (seconds_to_other - stop_seconds) / warning_seconds * max_speed
            )

            # See to that the ca_speed is lower than any other wanted speed
            ca_speed = round(
                min(ca_speed, self.mav.wanted_speed_mps, max_speed), 2
            )

            self.mav.set_speed(ca_speed)
            self.mqtt.send_info(f"CA WARN: {distance_to_other}m")

            # Collision Avoidance is active
            return True

        return False
