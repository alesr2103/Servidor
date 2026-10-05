"""Mapeo de ReadingType IEEE 2030.5 para telemetria DER."""

READING_TYPE_BY_UOM = {
    5: "current_rms_A",
    29: "voltage_rms_A",
    33: "frequency",
    38: "active_power",
    61: "apparent_power",
    63: "reactive_power",
    65: "power_factor",
}

DEFAULT_PHASE_BY_TYPE = {
    "current_rms_A": 128,
    "voltage_rms_A": 129,
    "voltage_current_phase_angle_A": 128,
    "frequency": 0,
    "active_power": 0,
    "apparent_power": 0,
    "reactive_power": 0,
    "power_factor": 0,
}

READING_UNITS = {
    0: "N/A",
    5: "A",
    29: "V",
    33: "Hz",
    38: "W",
    61: "VA",
    63: "var",
    65: "CosTheta",
}


def reading_type_for_uom(uom, description=None):
    uom = int(uom)

    if uom in READING_TYPE_BY_UOM:
        return READING_TYPE_BY_UOM[uom]

    text = (description or "").strip().lower()

    if uom == 0 and "angle" in text:
        return "voltage_current_phase_angle_A"

    raise ValueError(f"UomType no soportado: {uom}")


def default_phase_for_type(reading_type):
    return DEFAULT_PHASE_BY_TYPE.get(reading_type, 0)


def unit_name(uom):
    return READING_UNITS.get(int(uom), f"uom-{uom}")
