# THIS FILE IS CURRENTLY NOT IN USE ####################################################  # noqa: D100


class VehicleStateMachine:
    def __init__(self, vehicle_type):
        self.vehicle_type = vehicle_type
        self.states = ["DISARMED", "ARMED", "RUNNING"]
        self.modes = ["STABILIZE", "LOITER", "AUTO", "GUIDED"]

        # Define valid state transitions
        self.valid_state_transitions = {
            "DISARMED": ["ARMED"],
            "ARMED": ["DISARMED", "RUNNING"],
            "RUNNING": ["ARMED"],
        }

        # Define valid mode transitions
        self.valid_mode_transitions = {
            "STABILIZE": ["LOITER"],
            "LOITER": ["STABILIZE", "AUTO", "GUIDED"],
            "AUTO": ["LOITER"],
            "GUIDED": ["AUTO", "LOITER"],
        }

        self.current_state = "DISARMED"
        self.current_mode = "STABILIZE"

    def transition(self, state):
        if (
            state in self.states
            and state in self.valid_state_transitions[self.current_state]
        ):
            print(
                f"Transitioning from {self.current_state} to {state} state for {self.vehicle_type}"
            )
            self.current_state = state
        else:
            print(
                f"Invalid state transition from {self.current_state} to {state} for {self.vehicle_type}"
            )

    def set_mode(self, mode):
        if (
            mode in self.modes
            and mode in self.valid_mode_transitions[self.current_mode]
        ):
            print(
                f"Switching from {self.current_mode} to {mode} mode for {self.vehicle_type}"
            )
            self.current_mode = mode
        else:
            print(
                f"Invalid mode transition from {self.current_mode} to {mode} for {self.vehicle_type}"
            )

    def execute(self):
        print(
            f"Current state: {self.current_state}, Current mode: {self.current_mode} for {self.vehicle_type}"
        )


# Example usage for different vehicle types
quadcopter = VehicleStateMachine("Quadcopter")
quadcopter.execute()

quadcopter.transition("ARMED")
quadcopter.set_mode("LOITER")
quadcopter.execute()

quadcopter.transition("RUNNING")
quadcopter.set_mode("AUTO")
quadcopter.execute()

quadcopter.transition("ARMED")
quadcopter.set_mode("GUIDED")
quadcopter.execute()

quadcopter.transition("DISARMED")
quadcopter.set_mode("LOITER")
quadcopter.execute()
