import math

from concrete_level.models.concrete_actors import ConcreteVessel


def calculate_hydrodynamics(vessel: ConcreteVessel, hull_izz: float) -> dict:
    """
    Calculates empirical hydrodynamic coefficients for a surface vessel
    using standard heuristics for Added Mass, Linear Damping, and Quadratic Damping.
    All returned values are negative to represent forces opposing motion.
    """

    # --- Physical Constants & Dimensions ---
    rho = 1025.0  # Density of seawater (kg/m^3)
    m = vessel.mass
    L = vessel.length
    B = vessel.breadth
    T = vessel.draft

    # ==========================================
    # 1. ADDED MASS (Inertia of dragged water)
    # ==========================================
    # Surge (x): Streamlined, minimal water dragged (~5% of mass)
    xDotU = -0.05 * m

    # Sway (y): Pushing a wall of water. Modeled as a half-cylinder.
    yDotV = -0.5 * rho * math.pi * (T**2) * L

    # Heave (z): High resistance to pushing down into the water.
    # Note: If your vessel is strictly planar, this just adds stability.
    zDotW = -0.5 * m

    # Yaw (n): Rotational added inertia.
    nDotR = -0.5 * hull_izz

    # ==========================================
    # 2. QUADRATIC DAMPING (High-speed drag)
    # Formula: -0.5 * rho * Cd * Area
    # ==========================================
    # Surge drag: Cd for a streamlined bow is roughly 0.3
    frontal_area = B * T
    xUU = -0.5 * rho * 0.3 * frontal_area

    # Sway drag: Cd for a flat broadside is roughly 1.0
    # This acts like a massive invisible keel preventing the stern from sliding out.
    side_area = L * T
    yVV = -0.5 * rho * 3.0 * side_area

    # Heave drag: Cd for flat bottom pushing down is high.
    bottom_area = L * B
    zWW = -0.5 * rho * 1.2 * bottom_area

    # Yaw drag: Integrates the broadside drag along the length of the hull.
    # Yaw drag: Increase the multiplier from 1.0 to 5.0 or higher.
    # This forces the water to aggressively brake any unwanted spinning.
    nRR = -0.5 * rho * 5.0 * ((L**3 * T) / 12.0)

    # ==========================================
    # 3. LINEAR DAMPING (Low-speed friction)
    # Crucial for simulator stability to prevent infinite drifting
    # ==========================================
    xU = -0.01 * m
    yV = -0.20 * m
    zW = -0.10 * m
    nR = -0.50 * hull_izz

    return {"xDotU": xDotU, "yDotV": yDotV, "zDotW": zDotW, "nDotR": nDotR, "xU": xU, "yV": yV, "zW": zW, "nR": nR, "xUU": xUU, "yVV": yVV, "zWW": zWW, "nRR": nRR}
