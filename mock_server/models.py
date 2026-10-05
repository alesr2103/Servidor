"""Modelos internos persistentes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceRecord:
    id: int
    name: str
    description: str
    role: str
    lfdi: str
    sfdi: int
    fingerprint_sha256: str
    authorization_status: str
    enabled: bool
    registered_at: int
    last_seen: int | None
    created_at: int
    updated_at: int

    @property
    def is_authorized(self):
        return self.enabled and self.authorization_status == "active"

    @property
    def end_device_href(self):
        return f"/edev/{self.id}"

    @property
    def registration_href(self):
        return f"/edev/{self.id}/rg"

    @property
    def der_list_href(self):
        return f"/edev/{self.id}/der"

@dataclass(frozen=True)
class DERResourceRecord:
    id: int
    device_id: int
    resource_type: str
    xml_body: bytes
    source_timestamp: int | None
    received_at: int
    updated_at: int

@dataclass(frozen=True)
class AuditEventRecord:
    id: int
    device_id: int | None
    event_category: str
    event_type: str
    severity: str
    http_method: str | None
    route: str | None
    http_status: int | None
    resource_type: str | None
    subject: str | None
    source_ip: str | None
    details: str | None
    created_at: int


@dataclass(frozen=True)
class ControlResponseRecord:
    id: int
    device_id: int
    response_type: str
    subject: str | None
    response_status: int | None
    created_datetime: int | None
    xml_body: bytes
    received_at: int


@dataclass(frozen=True)
class DERProgramRecord:
    id: int
    device_id: int
    mrid: str
    description: str
    version: int
    primacy: int
    active: bool
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class DefaultDERControlRecord:
    id: int
    program_id: int
    mrid: str
    description: str
    version: int
    control_xml: bytes
    created_at: int
    updated_at: int

@dataclass(frozen=True)
class MirrorUsagePointRecord:
    id: int
    device_id: int
    mrid: str
    description: str | None
    role_flags: int
    service_category: int
    post_rate: int
    device_lfdi: str | None
    status: int | None
    xml_body: bytes
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class MirrorMeterReadingRecord:
    id: int
    usage_point_id: int
    mrid: str
    description: str | None
    reading_type: str
    phase: str | None
    uom: int | None
    power_of_ten_multiplier: int
    flow_direction: int | None
    accumulation_behaviour: int | None
    commodity: int | None
    data_qualifier: int | None
    kind: int | None
    reading_type_xml: bytes | None
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class MeterReadingRecord:
    id: int
    meter_reading_id: int
    value: int
    reading_time: int
    quality_flags: int | None
    xml_body: bytes
    received_at: int

    @property
    def scaled_value(self):
        return self.value

@dataclass(frozen=True)
class DERControlRecord:
    id: int
    program_id: int
    device_id: int
    mrid: str
    description: str
    version: int
    creation_time: int
    start_time: int
    duration: int
    control_status: str
    control_xml: bytes
    cancelled_at: int | None
    created_at: int
    updated_at: int

    @property
    def end_time(self):
        return self.start_time + self.duration

    @property
    def is_cancelled(self):
        return self.control_status == "cancelled"

    @property
    def is_terminal(self):
        return self.control_status in {
            "completed",
            "rejected",
            "cancelled",
            "expired",
            "superseded",
        }

