"""Inicialización y conexiones SQLite del servidor."""

import sqlite3

from . import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'device',
    lfdi TEXT NOT NULL UNIQUE,
    sfdi INTEGER NOT NULL,
    fingerprint_sha256 TEXT NOT NULL UNIQUE,
    authorization_status TEXT NOT NULL DEFAULT 'active',
    enabled INTEGER NOT NULL DEFAULT 1,
    registered_at INTEGER NOT NULL,
    last_seen INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    CHECK (authorization_status IN ('pending', 'active', 'blocked', 'retired')),
    CHECK (enabled IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_devices_sfdi ON devices(sfdi);
CREATE INDEX IF NOT EXISTS idx_devices_authorization ON devices(authorization_status, enabled);

CREATE TABLE IF NOT EXISTS device_certificates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    fingerprint_sha256 TEXT NOT NULL UNIQUE,
    certificate_der BLOB NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    replaced_at INTEGER,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    CHECK (active IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_device_certificates_device_id ON device_certificates(device_id);

CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL UNIQUE,
    pin INTEGER NOT NULL,
    registered_at INTEGER NOT NULL,
    poll_rate INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS der_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    resource_type TEXT NOT NULL,
    xml_body BLOB NOT NULL,
    source_timestamp INTEGER,
    received_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE (device_id, resource_type),
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    CHECK (
        resource_type IN (
            'DERCapability',
            'DERSettings',
            'DERStatus',
            'DERAvailability'
        )
    )
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER,
    event_category TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    http_method TEXT,
    route TEXT,
    http_status INTEGER,
    resource_type TEXT,
    subject TEXT,
    source_ip TEXT,
    details TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE SET NULL,
    CHECK (severity IN ('info', 'warning', 'error', 'critical')),
    CHECK (http_status IS NULL OR (http_status >= 100 AND http_status <= 599))
);

CREATE INDEX IF NOT EXISTS idx_audit_events_created_at
ON audit_events(created_at);

CREATE INDEX IF NOT EXISTS idx_audit_events_device
ON audit_events(device_id);

CREATE INDEX IF NOT EXISTS idx_audit_events_type
ON audit_events(event_type);

CREATE INDEX IF NOT EXISTS idx_audit_events_status
ON audit_events(http_status);

CREATE INDEX IF NOT EXISTS idx_der_resources_device
ON der_resources(device_id);

CREATE TABLE IF NOT EXISTS control_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    response_type TEXT NOT NULL,
    subject TEXT,
    response_status INTEGER,
    created_datetime INTEGER,
    xml_body BLOB NOT NULL,
    received_at INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    CHECK (
        response_type IN (
            'Response',
            'DERControlResponse',
            'DefaultDERControlResponse'
        )
    ),
    CHECK (
        response_status IS NULL
        OR response_status BETWEEN 0 AND 255
    )
);

CREATE INDEX IF NOT EXISTS idx_control_responses_device
ON control_responses(device_id);

CREATE INDEX IF NOT EXISTS idx_control_responses_subject
ON control_responses(subject);

CREATE INDEX IF NOT EXISTS idx_control_responses_received
ON control_responses(received_at);

CREATE TABLE IF NOT EXISTS der_programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    mrid TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    primacy INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    CHECK (version >= 0),
    CHECK (primacy BETWEEN 0 AND 255),
    CHECK (active IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_der_programs_device
ON der_programs(device_id);

CREATE INDEX IF NOT EXISTS idx_der_programs_active
ON der_programs(device_id, active);

CREATE TABLE IF NOT EXISTS default_der_controls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL UNIQUE,
    mrid TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    control_xml BLOB NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (program_id) REFERENCES der_programs(id) ON DELETE CASCADE,
    CHECK (version >= 0)
);

CREATE INDEX IF NOT EXISTS idx_default_der_controls_program
ON default_der_controls(program_id);

CREATE TABLE IF NOT EXISTS der_controls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    device_id INTEGER NOT NULL,
    mrid TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    creation_time INTEGER NOT NULL,
    start_time INTEGER NOT NULL,
    duration INTEGER NOT NULL,
    control_status TEXT NOT NULL DEFAULT 'scheduled',
    control_xml BLOB NOT NULL,
    cancelled_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (program_id) REFERENCES der_programs(id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    CHECK (version >= 0),
    CHECK (duration > 0),
    CHECK (
        control_status IN (
            'scheduled',
            'active',
            'received',
            'started',
            'completed',
            'rejected',
            'cancelled',
            'expired',
            'superseded'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_der_controls_program
ON der_controls(program_id);

CREATE INDEX IF NOT EXISTS idx_der_controls_device
ON der_controls(device_id);

CREATE INDEX IF NOT EXISTS idx_der_controls_schedule
ON der_controls(device_id, start_time);

CREATE INDEX IF NOT EXISTS idx_der_controls_status
ON der_controls(control_status);

CREATE TABLE IF NOT EXISTS mirror_usage_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    mrid TEXT NOT NULL,
    description TEXT,
    role_flags INTEGER NOT NULL DEFAULT 0,
    service_category INTEGER NOT NULL DEFAULT 0,
    post_rate INTEGER NOT NULL DEFAULT 300,
    device_lfdi TEXT,
    status INTEGER,
    xml_body BLOB NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    UNIQUE (device_id, mrid),
    CHECK (role_flags >= 0),
    CHECK (service_category BETWEEN 0 AND 255),
    CHECK (post_rate > 0),
    CHECK (status IS NULL OR status BETWEEN 0 AND 255)
);

CREATE INDEX IF NOT EXISTS idx_mirror_usage_points_device
ON mirror_usage_points(device_id);

CREATE INDEX IF NOT EXISTS idx_mirror_usage_points_mrid
ON mirror_usage_points(mrid);

CREATE TABLE IF NOT EXISTS mirror_meter_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usage_point_id INTEGER NOT NULL,
    mrid TEXT NOT NULL,
    description TEXT,
    reading_type TEXT NOT NULL,
    phase TEXT,
    uom INTEGER,
    power_of_ten_multiplier INTEGER NOT NULL DEFAULT 0,
    flow_direction INTEGER,
    accumulation_behaviour INTEGER,
    commodity INTEGER,
    data_qualifier INTEGER,
    kind INTEGER,
    reading_type_xml BLOB,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (usage_point_id) REFERENCES mirror_usage_points(id) ON DELETE CASCADE,
    UNIQUE (usage_point_id, mrid),
    CHECK (
    reading_type IN (
        'current_rms_A',
        'voltage_rms_A',
        'voltage_current_phase_angle_A',
        'frequency',
        'active_power',
        'apparent_power',
        'reactive_power',
        'power_factor'
    )
),

    CHECK (power_of_ten_multiplier BETWEEN -128 AND 127)
);

CREATE INDEX IF NOT EXISTS idx_mirror_meter_readings_usage_point
ON mirror_meter_readings(usage_point_id);

CREATE INDEX IF NOT EXISTS idx_mirror_meter_readings_type
ON mirror_meter_readings(reading_type);

CREATE TABLE IF NOT EXISTS meter_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_reading_id INTEGER NOT NULL,
    value INTEGER NOT NULL,
    reading_time INTEGER NOT NULL,
    quality_flags INTEGER,
    xml_body BLOB NOT NULL,
    received_at INTEGER NOT NULL,
    FOREIGN KEY (meter_reading_id) REFERENCES mirror_meter_readings(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_meter_readings_meter
ON meter_readings(meter_reading_id);

CREATE INDEX IF NOT EXISTS idx_meter_readings_time
ON meter_readings(reading_time);

CREATE INDEX IF NOT EXISTS idx_meter_readings_received
ON meter_readings(received_at);


"""


def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize_database():
    with connect() as connection:
        connection.executescript(SCHEMA)
