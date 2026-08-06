import math
from typing import Union
import pyproj

import numpy as np
from haversine import Unit, haversine

from concrete_level.models.actor_state import ActorState
from utils.math_utils import calculate_heading

class Geofence:
    """Circular geofence: center point (WGS84) and radius in meters."""

    def __init__(self, latitude: float, longitude: float, radius_meters: float): # lat, long in degrees
        self.latitude = latitude
        self.longitude = longitude
        self.radius_meters = radius_meters
        self.utm_epsg = self.get_utm_epsg(self.latitude, self.longitude)
        self.to_xy = pyproj.Transformer.from_crs("EPSG:4326", self.utm_epsg, always_xy=True)
        self.to_ll = pyproj.Transformer.from_crs(self.utm_epsg, "EPSG:4326", always_xy=True)
        self.x0, self.y0 = self.to_xy.transform(self.longitude, self.latitude)
        
    def get_utm_epsg(self, lat: float, lon: float) -> str:
        zone = int((lon + 180) / 6) + 1

        if lat >= 0:
            return f"EPSG:326{zone:02d}"
        else:
            return f"EPSG:327{zone:02d}"

    
    def to_lat_long(self, p: np.ndarray) -> np.ndarray:
        x, y = p[0] + self.x0, p[1] + self.y0
        long, lat = self.to_ll.transform(x, y)
        return np.array([lat, long])
    
    def to_coord(self, lat: float, lon: float) -> np.ndarray:
        x, y = self.to_xy.transform(lon, lat)
        return np.array([x - self.x0, y - self.y0])
    
    @property
    def center(self) -> np.ndarray:
        return np.array([self.latitude, self.longitude])
    
def to_true_north(heading: float, unit=Unit.RADIANS) -> float:
    if unit == Unit.RADIANS:
        heading = math.degrees(heading)
        result = 90 - heading
        result = result % 360
        if result == 0:
            result = 360
        return math.radians(result)
    elif unit == Unit.DEGREES:
        result = (90 - heading) % 360
        return 360 if result == 0 else result
    else:
        raise ValueError("Invalid unit. Use Unit.DEGREES or Unit.RADIANS.")


def from_true_north(true_north: float, unit=Unit.RADIANS) -> float:
    angle = math.degrees(true_north) if unit == Unit.RADIANS else true_north

    # Normalize 360 -> 0 BEFORE conversion
    if angle == 360:
        angle = 0

    heading = 90 - angle

    # Normalize to [-180, 180)
    heading = (heading + 180) % 360 - 180

    return math.radians(heading) if unit == Unit.RADIANS else heading


def true_north_heading(
    p1: np.ndarray,
    p2: np.ndarray,
    unit: Union[Unit.DEGREES, Unit.RADIANS] = Unit.RADIANS,
) -> float:
    p12 = p2 - p1
    heading = to_true_north(calculate_heading(p12))
    if unit == Unit.RADIANS:
        return heading
    elif unit == Unit.DEGREES:
        return math.degrees(heading)
    else:
        raise ValueError("Invalid unit. Use Unit.DEGREES or Unit.RADIANS.")


def waypoint_from_state(state: ActorState, reference_geofence: Geofence) -> dict:
    lat_long = reference_geofence.to_lat_long(state.p)
    return {
        "altitude": 0,
        "latitude": lat_long[0],
        "longitude": lat_long[1],
        "rostype": "GeoPoint",
    }
    
    
def normalized_to_pwm(norm_value):
    """
    Converts a float between -1.0 and 1.0 to a standard PWM integer.
    E.g., -0.5 becomes 1250.
    """
    # 1. Clamp the value to ensure it never exceeds the -1.0 to 1.0 range
    clamped_value = max(-1.0, min(1.0, norm_value))
    
    # 2. Calculate the PWM
    pwm = 1500 + (clamped_value * 500)
    
    # 3. Return as an integer (MAVLink requires ints for RC overrides)
    return int(pwm)
    
