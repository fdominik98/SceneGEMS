import signal
import sys
import time

from agent import Agent
from connections import MAVLinkConnection
from mavlink_handler import Mavlink
from mqtt_handler import Mqtt


def main() -> None:
    # CONNECTIONS
    mavlink_connection = MAVLinkConnection()
    mav: Mavlink = Mavlink(mavlink_connection)

    # MQTT SETUP
    mqtt: Mqtt = Mqtt()

    agent = Agent(mqtt, mav)

    def signal_handler(*args) -> None:
        print("Shutting down...")
        agent.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Frequencies in Hz (TODO: insert by environment variables)
    pos_rate: float = 2  # Hz
    decl_rate: float = 0.5  # Hz
    misc_rate: float = 1  # Hz

    # Calculate intervals in seconds
    pos_interval: float = 1 / pos_rate
    decl_interval: float = 1 / decl_rate
    misc_interval: float = 1 / misc_rate

    # Initialize timers
    last_pos_time = time.time()
    last_decl_time = time.time()
    last_misc_time = time.time()

    # Clean up
    mqtt.send_waypoints()
    
    # while not mav.prepare_vehicle_global(0):
    #     time.sleep(0.1)

    while True:
        curr_time = time.time()

        # Declarations. Low rate of information sending.
        if curr_time - last_decl_time >= decl_interval:
            mqtt.send_heartbeat(decl_rate)
            mqtt.send_sensor_info(decl_rate)
            mqtt.send_direct_execution_info(decl_rate)
            mqtt.send_videoserver_url()
            mqtt.send_speed_preset(mav.get_speed_preset())

            # Below will be triggered and sent by the mavlink system
            #     but will be periodically sent aswell
            mqtt.send_mode(mav.get_mode_name())
            mqtt.send_state(mav.get_state_name())
            mqtt.send_control_system_version(f"{mav.vehicle.version}")
            mqtt.send_armable(mav.is_armable())
            mqtt.send_ipaddress(agent.get_local_ip())

            last_decl_time = time.time()

        # Position related. High rate of information sending.
        if curr_time - last_pos_time >= pos_interval:
            # agent.send_position()
            # agent.send_speed()
            # agent.send_course()
            # agent.send_heading()
            # agent.send_waypoints()

            # print(
            #     f"{agent.mav.me_inside_geofence()=} {agent.mav.me_inside_geofence_soon(3)=} {agent.mav.me_inside_no_go_zone()=} {agent.mav.me_inside_no_go_zone_soon(3)=}"
            # )
            # print(f"{agent.mav.position_is_allowed()=}")

            if not agent.mav.position_is_allowed():
                agent.mav.set_speed(0.2)
            pass

            last_pos_time = time.time()

        # Others. medium rate of information sending.
        if curr_time - last_misc_time >= misc_interval:
            mqtt.send_cargo(agent.cargo_collection)

            last_misc_time = time.time()

        # mav.print_agent_state()

        time.sleep(0.2)  # Sleep for a short time to avoid busy-waiting


if __name__ == "__main__":
    main()
