"""Generación de recursos XML IEEE 2030.5."""

import time
import xml.etree.ElementTree as ET
from . import config
from .store import STORE
from .repositories import CONTROL_RESPONSE_REPOSITORY, DEFAULT_DER_CONTROL_REPOSITORY, DER_CONTROL_REPOSITORY, DER_PROGRAM_REPOSITORY, DER_RESOURCE_REPOSITORY, METER_READING_REPOSITORY, MIRROR_METER_READING_REPOSITORY, MIRROR_USAGE_POINT_REPOSITORY

ET.register_namespace("", config.NAMESPACE)

def qn(tag): return f"{{{config.NAMESPACE}}}{tag}"

def element(tag, text=None, attributes=None):
    node = ET.Element(qn(tag))
    for name, value in (attributes or {}).items(): node.set(name, str(value))
    if text is not None: node.text = str(text)
    return node

def child(parent, tag, text=None, attributes=None):
    node = element(tag, text, attributes); parent.append(node); return node

def serialize(root):
    try: ET.indent(root, space="  ")
    except AttributeError: pass
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True, short_empty_elements=True)
    ET.fromstring(data)
    return data

def device_capability():
    root = element("DeviceCapability", attributes={"href": "/dcap", "pollRate": config.POLL_RATE})
    child(root, "TimeLink", attributes={"href": "/tm"})
    child(root, "EndDeviceListLink", attributes={"all": 1, "href": "/edev"})
    child(root, "MirrorUsagePointListLink", attributes={"all": len(MIRROR_USAGE_POINT_REPOSITORY.list_for_device(1)), "href": "/mup"})
    return serialize(root)

def time_resource():
    now = int(time.time()); root = element("Time", attributes={"href": "/tm"})
    values = (("currentTime", now), ("dstEndTime", 0), ("dstOffset", 0), ("dstStartTime", 0),
              ("localTime", (now + config.TZ_OFFSET) % 86400), ("quality", config.TIME_QUALITY),
              ("tzOffset", config.TZ_OFFSET))
    for tag, value in values: child(root, tag, value)
    return serialize(root)


def add_end_device(parent):
    dev = child(parent, "EndDevice", attributes={"href": "/edev/1"})
    child(dev, "DERListLink", attributes={"all": 1, "href": "/edev/1/der"})
    child(dev, "lFDI", STORE.lfdi_hex)
    child(dev, "sFDI", STORE.sfdi)
    child(dev, "changedTime", 0)
    child(dev, "FunctionSetAssignmentsListLink", attributes={"all": len(programs_for_device()), "href": "/edev/1/fsa"})
    child(dev, "RegistrationLink", attributes={"href": "/edev/1/rg"})
    return dev

def end_device_list():
    root = element("EndDeviceList", attributes={"href": "/edev", "all": 1, "results": 1})
    add_end_device(root); return serialize(root)

def end_device():
    holder = element("Holder"); return serialize(add_end_device(holder))

def registration():
    root = element("Registration",attributes={"href": "/edev/1/rg","pollRate": config.REGISTRATION_POLL_RATE,},)

    child(root,"dateTimeRegistered",STORE.registration_time,)

    child(root,"pIN",config.REGISTRATION_PIN,)

    return serialize(root)

def add_der(parent):
    resource = child(parent, "DER", attributes={"href": "/edev/1/der/1"})
    child(resource, "DERAvailabilityLink", attributes={"href": "/edev/1/der/1/dera"})
    child(resource, "DERCapabilityLink", attributes={"href": "/edev/1/der/1/dercap"})
    child(resource, "DERSettingsLink", attributes={"href": "/edev/1/der/1/derg"})
    child(resource, "DERStatusLink", attributes={"href": "/edev/1/der/1/ders"})
    return resource

def der_list():
    root = element("DERList", attributes={"href": "/edev/1/der", "all": 1, "results": 1})
    add_der(root)
    return serialize(root)

def der():
    holder = element("Holder")
    return serialize(add_der(holder))

def power(parent, tag, value, multiplier=0):
    resource = child(parent, tag)
    child(resource, "multiplier", multiplier)
    child(resource, "value", value)
    return resource

def persisted_der_resource(resource_type, default_generator):
    record = DER_RESOURCE_REPOSITORY.get(1, resource_type)
    return record.xml_body if record is not None else default_generator()

def default_der_capability():
    root = element("DERCapability", attributes={"href": "/edev/1/der/1/dercap"})
    child(root, "modesSupported", "01fffd")
    power(root, "rtgA", 10)
    power(root, "rtgW", 2000)
    child(root, "type", 4)
    return serialize(root)

def der_capability():
    return persisted_der_resource("DERCapability", default_der_capability)

def default_der_settings():
    root = element("DERSettings", attributes={"href": "/edev/1/der/1/derg"})
    child(root, "setGradW", 0)
    power(root, "setMaxW", 1800)
    child(root, "updatedTime", int(time.time()))
    return serialize(root)

def der_settings():
    return persisted_der_resource("DERSettings", default_der_settings)

def default_der_status():
    root = element(
        "DERStatus",
        attributes={"href": "/edev/1/der/1/ders"},
    )
    now = int(time.time())

    inverter = child(root, "inverterStatus")
    child(inverter, "dateTime", now)
    child(inverter, "value", 4)

    child(root, "readingTime", now)
    return serialize(root)


def der_status():
    return persisted_der_resource("DERStatus", default_der_status)


def default_der_availability():
    root = element("DERAvailability", attributes={"href": "/edev/1/der/1/dera"})
    child(root, "availabilityDuration", 600)
    child(root, "readingTime", int(time.time()))
    child(root, "reservePercent", 40)
    power(root, "statWAvail", 200)
    return serialize(root)

def der_availability():
    return persisted_der_resource("DERAvailability", default_der_availability)


def programs_for_device():
    records = DER_PROGRAM_REPOSITORY.list_for_device(1, active_only=True)
    return sorted(records, key=lambda record: record.id)


def program_for_route(fsa_id, program_id=None):
    record = DER_PROGRAM_REPOSITORY.get_by_id(fsa_id)

    if record is None:
        return None

    if record.device_id != 1 or not record.active:
        return None

    if program_id is not None and record.id != program_id:
        return None

    return record


def fsa_mrid(fsa_id):
    base = int("F5000000000000000000000000000000", 16)
    return f"{base + int(fsa_id):032X}"


def add_fsa(parent, fsa_id=1, record=None):
    record = record or program_for_route(fsa_id)

    if record is None:
        return None

    href = f"/edev/1/fsa/{fsa_id}"
    fsa = child(
        parent,
        "FunctionSetAssignments",
        attributes={"href": href},
    )
    child(
        fsa,
        "DERProgramListLink",
        attributes={"all": 1, "href": f"{href}/derp"},
    )
    child(fsa, "mRID", fsa_mrid(fsa_id))
    child(fsa, "description", f"Asignacion DER {fsa_id}")
    child(fsa, "version", 1)
    return fsa


def fsa_list():
    records = programs_for_device()
    root = element(
        "FunctionSetAssignmentsList",
        attributes={
            "href": "/edev/1/fsa",
            "all": len(records),
            "results": len(records),
        },
    )

    for record in records:
        add_fsa(root, record.id, record)

    return serialize(root)


def fsa_by_id(fsa_id):
    record = program_for_route(fsa_id)

    if record is None:
        return None

    holder = element("Holder")
    return serialize(add_fsa(holder, fsa_id, record))


def fsa():
    return fsa_by_id(1)


def active_program():
    return DER_PROGRAM_REPOSITORY.get_active_for_device(1)


def add_program(parent, record=None, fsa_id=None):
    record = record or active_program()

    if record is None:
        return None

    fsa_id = record.id if fsa_id is None else int(fsa_id)
    href = f"/edev/1/fsa/{fsa_id}/derp/{record.id}"
    controls = DER_CONTROL_REPOSITORY.list_for_program(
        record.id,
        include_terminal=False,
    )
    controls = [
        control
        for control in controls
        if persisted_control_status(control) is not None
    ]

    program = child(
        parent,
        "DERProgram",
        attributes={"href": href},
    )
    child(program, "mRID", record.mrid)
    child(program, "description", record.description)
    child(program, "version", record.version)
    child(
        program,
        "DefaultDERControlLink",
        attributes={"href": f"{href}/dderc"},
    )
    child(
        program,
        "DERControlListLink",
        attributes={
            "all": len(controls),
            "href": f"{href}/derc",
        },
    )
    child(program, "primacy", record.primacy)
    return program


def program_list_for_fsa(fsa_id):
    record = program_for_route(fsa_id)

    if record is None:
        return None

    href = f"/edev/1/fsa/{fsa_id}/derp"
    root = element(
        "DERProgramList",
        attributes={
            "href": href,
            "all": 1,
            "results": 1,
        },
    )
    add_program(root, record, fsa_id)
    return serialize(root)


def program_list():
    return program_list_for_fsa(1)


def program_by_route(fsa_id, program_id):
    record = program_for_route(fsa_id, program_id)

    if record is None:
        return None

    holder = element("Holder")
    return serialize(add_program(holder, record, fsa_id))


def program():
    return program_by_route(1, 1)


def default_control_for_program(fsa_id, program_id):
    program_record = program_for_route(fsa_id, program_id)

    if program_record is None:
        return None

    record = DEFAULT_DER_CONTROL_REPOSITORY.get_for_program(
        program_record.id
    )

    if record is None:
        return None

    root = ET.fromstring(record.control_xml)
    root.set(
        "href",
        f"/edev/1/fsa/{fsa_id}/derp/{program_id}/dderc",
    )
    return serialize(root)


def default_control():
    return default_control_for_program(1, 1)


def persisted_control_status(record, now=None):
    current_time = int(time.time()) if now is None else int(now)

    if record.is_terminal:
        return None

    if current_time < record.start_time:
        return 0

    if current_time < record.end_time:
        return 1

    return None


def copy_control_base(parent, control_xml):
    base = child(parent, "DERControlBase")

    try:
        stored = ET.fromstring(control_xml)
    except ET.ParseError:
        return base

    stored_base = stored.find(
        f"{{{config.NAMESPACE}}}DERControlBase"
    )

    if stored_base is None:
        return base

    for stored_child in list(stored_base):
        copied = ET.fromstring(
            ET.tostring(stored_child, encoding="utf-8")
        )
        base.append(copied)

    return base


def add_persisted_control(parent, record, href=None):
    status = persisted_control_status(record)

    if status is None:
        raise ValueError("DERControl expirado")

    if href is None:
        href = (
            f"/edev/1/fsa/{record.program_id}"
            f"/derp/{record.program_id}"
            f"/derc/{record.id}"
        )

    control = child(
        parent,
        "DERControl",
        attributes={
            "href": href,
            "replyTo": "/rsps/1/rsp",
            "responseRequired": "03",
        },
    )
    child(control, "mRID", record.mrid)
    child(control, "description", record.description)
    child(control, "version", record.version)
    child(control, "creationTime", record.creation_time)

    event = child(control, "EventStatus")
    child(event, "currentStatus", status)
    child(
        event,
        "dateTime",
        record.creation_time if status == 0 else record.start_time,
    )
    child(event, "potentiallySuperseded", "false")

    interval = child(control, "interval")
    child(interval, "duration", record.duration)
    child(interval, "start", record.start_time)

    copy_control_base(control, record.control_xml)
    return control


def controls_for_program(program_id):
    records = DER_CONTROL_REPOSITORY.list_for_program(
        program_id,
        include_terminal=False,
    )
    return [
        record
        for record in records
        if persisted_control_status(record) is not None
    ]


def control_list_for_program(fsa_id, program_id):
    program_record = program_for_route(fsa_id, program_id)

    if program_record is None:
        return None

    records = controls_for_program(program_record.id)
    href = f"/edev/1/fsa/{fsa_id}/derp/{program_id}/derc"
    root = element(
        "DERControlList",
        attributes={
            "href": href,
            "all": len(records),
            "results": len(records),
        },
    )

    for record in records:
        add_persisted_control(
            root,
            record,
            f"{href}/{record.id}",
        )

    return serialize(root)


def control_list():
    return control_list_for_program(1, 1)


def control():
    records = controls_for_program(1)

    if not records:
        return None

    holder = element("Holder")
    return serialize(add_persisted_control(holder, records[0]))


def control_by_id(
    control_id,
    fsa_id=None,
    program_id=None,
):
    record = DER_CONTROL_REPOSITORY.get_by_id(control_id)

    if record is None or record.device_id != 1:
        return None

    record_program_id = getattr(record, "program_id", 1)

    expected_program = (
        record_program_id
        if program_id is None
        else int(program_id)
    )
    expected_fsa = (
        expected_program
        if fsa_id is None
        else int(fsa_id)
    )

    if record_program_id != expected_program:
        return None

    if expected_fsa != expected_program:
        return None

    if persisted_control_status(record) is None:
        return None

    holder = element("Holder")
    href = (
        f"/edev/1/fsa/{expected_fsa}"
        f"/derp/{expected_program}"
        f"/derc/{record.id}"
    )
    return serialize(
        add_persisted_control(holder, record, href)
    )



def legacy_program():
    record = active_program()

    if record is None:
        return None

    holder = element("Holder")
    return serialize(add_program(holder, record, 1))


def program():
    return legacy_program()


def legacy_program_list():
    record = active_program()

    if record is None:
        root = element(
            "DERProgramList",
            attributes={
                "href": "/edev/1/fsa/1/derp",
                "all": 0,
                "results": 0,
            },
        )
        return serialize(root)

    root = element(
        "DERProgramList",
        attributes={
            "href": "/edev/1/fsa/1/derp",
            "all": 1,
            "results": 1,
        },
    )
    add_program(root, record, 1)
    return serialize(root)


def program_list():
    return legacy_program_list()


def legacy_default_control():
    program_record = active_program()

    if program_record is not None:
        record = DEFAULT_DER_CONTROL_REPOSITORY.get_for_program(
            program_record.id
        )

        if record is not None:
            root = ET.fromstring(record.control_xml)
            root.set(
                "href",
                "/edev/1/fsa/1/derp/1/dderc",
            )
            return serialize(root)

    root = element(
        "DefaultDERControl",
        attributes={
            "href": "/edev/1/fsa/1/derp/1/dderc",
        },
    )
    child(root, "mRID", config.DEFAULT_CONTROL_MRID)
    child(root, "description", "Control DER por defecto")
    child(root, "version", 1)
    child(root, "DERControlBase")
    return serialize(root)


def default_control():
    return legacy_default_control()


def add_store_control(parent):
    state = STORE.control
    status = state.status()

    if status is None:
        raise ValueError("DERControl expirado")

    control = child(
        parent,
        "DERControl",
        attributes={
            "href": "/edev/1/fsa/1/derp/1/derc/1",
        },
    )
    child(control, "mRID", config.DER_CONTROL_MRID)
    child(control, "description", "Control DER temporal")
    child(control, "version", 1)
    child(control, "creationTime", state.creation_time)

    event = child(control, "EventStatus")
    child(event, "currentStatus", status)
    child(
        event,
        "dateTime",
        state.creation_time if status == 0 else state.start_time,
    )
    child(event, "potentiallySuperseded", "false")

    interval = child(control, "interval")
    child(interval, "duration", state.duration)
    child(interval, "start", state.start_time)

    base = child(control, "DERControlBase")

    if state.op_mod_connect:
        child(base, "opModConnect", "true")

    return control


def persisted_controls():
    program_record = active_program()

    if program_record is None:
        return None

    records = DER_CONTROL_REPOSITORY.list_applicable(
        1,
        current_time=int(time.time()),
    )

    return [
        record
        for record in records
        if persisted_control_status(record) is not None
    ]


def legacy_control_list():
    records = persisted_controls()

    if records is not None:
        root = element(
            "DERControlList",
            attributes={
                "href": "/edev/1/fsa/1/derp/1/derc",
                "all": len(records),
                "results": len(records),
            },
        )

        for record in records:
            add_persisted_control(
                root,
                record,
                f"/edev/1/fsa/1/derp/1/derc/{record.id}",
            )

        return serialize(root)

    status = STORE.control.status()
    count = 0 if status is None else 1

    root = element(
        "DERControlList",
        attributes={
            "href": "/edev/1/fsa/1/derp/1/derc",
            "all": count,
            "results": count,
        },
    )

    if status is not None:
        add_store_control(root)

    return serialize(root)


def control_list():
    return legacy_control_list()


def legacy_control():
    records = persisted_controls()

    if records is not None:
        if not records:
            return None

        holder = element("Holder")
        return serialize(
            add_persisted_control(
                holder,
                records[0],
                f"/edev/1/fsa/1/derp/1/derc/{records[0].id}",
            )
        )

    if STORE.control.status() is None:
        return None

    holder = element("Holder")
    return serialize(add_store_control(holder))


def control():
    return legacy_control()


def add_response_set(parent):
    response_set = child(parent, "ResponseSet", attributes={"href": "/rsps/1"})
    child(response_set, "mRID", "05")
    child(response_set, "description", "Respuestas del EndDevice 1")
    child(response_set, "version", 1)
    child(response_set, "ResponseListLink", attributes={"all": len(CONTROL_RESPONSE_REPOSITORY.list_for_device(1)), "href": "/rsps/1/rsp"})
    return response_set


def response_set_list():
    root = element("ResponseSetList", attributes={"href": "/rsps", "all": 1, "results": 1, "pollRate": config.POLL_RATE})
    add_response_set(root)
    return serialize(root)


def response_set():
    holder = element("Holder")
    return serialize(add_response_set(holder))


def response_value(root, name):
    node = root.find(f"{{{config.NAMESPACE}}}{name}")
    return node.text.strip() if node is not None and node.text else None


def add_response(parent, record):
    stored = ET.fromstring(record.xml_body)
    response = child(parent, "Response", attributes={"href": f"/rsps/1/rsp/{record.id}"})

    for name in ("createdDateTime", "endDeviceLFDI", "status", "subject"):
        value = response_value(stored, name)

        if value is not None:
            child(response, name, value)

    return response


def response_list():
    records = CONTROL_RESPONSE_REPOSITORY.list_for_device(1)
    root = element("ResponseList", attributes={"href": "/rsps/1/rsp", "all": len(records), "results": len(records)})

    for record in reversed(records):
        add_response(root, record)

    return serialize(root)


def response_by_id(response_id):
    record = CONTROL_RESPONSE_REPOSITORY.get_by_id(response_id)

    if record is None or record.device_id != 1:
        return None

    root = ET.fromstring(record.xml_body)
    root.set("href", f"/rsps/1/rsp/{record.id}")
    return serialize(root)

def add_mirror_usage_point(parent, record):
    root = ET.fromstring(record.xml_body)
    root.set("href", f"/mup/{record.id}")
    parent.append(root)
    return root


def mirror_usage_point_list():
    records = MIRROR_USAGE_POINT_REPOSITORY.list_for_device(1)
    root = element("MirrorUsagePointList", attributes={"href": "/mup", "all": len(records), "results": len(records), "pollRate": config.POLL_RATE})

    for record in records:
        add_mirror_usage_point(root, record)

    return serialize(root)


def mirror_usage_point_by_id(usage_point_id):
    record = MIRROR_USAGE_POINT_REPOSITORY.get_by_id(usage_point_id)

    if record is None or record.device_id != 1:
        return None

    root = ET.fromstring(record.xml_body)
    root.set("href", f"/mup/{record.id}")
    return serialize(root)
PHASE_CODES = {
    None: 0,
    "A": 128,
    "AN": 129,
    "B": 64,
    "BN": 65,
    "C": 32,
    "CN": 33,
    "AB": 132,
    "BC": 66,
    "CA": 40,
    "ABC": 224,
}


def add_reading_type(parent, record):
    reading_type = child(parent, "ReadingType")

    if record.accumulation_behaviour is not None:
        child(reading_type, "accumulationBehaviour", record.accumulation_behaviour)

    if record.commodity is not None:
        child(reading_type, "commodity", record.commodity)

    if record.data_qualifier is not None:
        child(reading_type, "dataQualifier", record.data_qualifier)

    if record.flow_direction is not None:
        child(reading_type, "flowDirection", record.flow_direction)

    if record.kind is not None:
        child(reading_type, "kind", record.kind)

    phase_code = PHASE_CODES.get(record.phase, 0)

    if phase_code:
        child(reading_type, "phase", phase_code)

    child(reading_type, "powerOfTenMultiplier", record.power_of_ten_multiplier)

    if record.uom is not None:
        child(reading_type, "uom", record.uom)

    return reading_type


def add_reading(parent, record, href=None):
    attributes = {"href": href} if href else None
    reading = child(parent, "Reading", attributes=attributes)

    if record.quality_flags is not None:
        child(reading, "qualityFlags", f"{record.quality_flags:02x}")

    period = child(reading, "timePeriod")
    child(period, "duration", 0)
    child(period, "start", record.reading_time)
    child(reading, "value", record.value)
    return reading

def add_mirror_meter_reading(parent, record, include_latest=True):
    href = f"/mup/{record.usage_point_id}/mr/{record.id}"
    meter = child(parent, "MirrorMeterReading", attributes={"href": href})
    child(meter, "mRID", record.mrid)

    if record.description:
        child(meter, "description", record.description)

    latest = METER_READING_REPOSITORY.get_latest(record.id) if include_latest else None

    if latest is not None:
        child(meter, "lastUpdateTime", latest.reading_time)
        add_reading(meter, latest, f"{href}/r/{latest.id}")

    add_reading_type(meter, record)
    return meter


def mirror_meter_reading_list(usage_point_id):
    usage_point = MIRROR_USAGE_POINT_REPOSITORY.get_by_id(usage_point_id)

    if usage_point is None or usage_point.device_id != 1:
        return None

    records = MIRROR_METER_READING_REPOSITORY.list_for_usage_point(usage_point_id)
    href = f"/mup/{usage_point_id}/mr"
    root = element("MirrorMeterReadingList", attributes={"href": href, "all": len(records), "results": len(records)})

    for record in records:
        add_mirror_meter_reading(root, record)

    return serialize(root)


def mirror_meter_reading_by_id(usage_point_id, meter_id):
    usage_point = MIRROR_USAGE_POINT_REPOSITORY.get_by_id(usage_point_id)
    record = MIRROR_METER_READING_REPOSITORY.get_by_id(meter_id)

    if usage_point is None or record is None:
        return None

    if usage_point.device_id != 1 or record.usage_point_id != usage_point.id:
        return None

    holder = element("Holder")
    return serialize(add_mirror_meter_reading(holder, record))

def meter_reading_list(usage_point_id, meter_id, limit=100):
    usage_point = MIRROR_USAGE_POINT_REPOSITORY.get_by_id(usage_point_id)
    meter = MIRROR_METER_READING_REPOSITORY.get_by_id(meter_id)

    if usage_point is None or meter is None:
        return None

    if usage_point.device_id != 1 or meter.usage_point_id != usage_point.id:
        return None

    records = METER_READING_REPOSITORY.list_for_meter(meter_id, limit=limit)
    href = f"/mup/{usage_point_id}/mr/{meter_id}/r"
    root = element("ReadingList", attributes={"href": href, "all": len(records), "results": len(records)})

    for record in reversed(records):
        add_reading(root, record, f"{href}/{record.id}")

    return serialize(root)


RESOURCES = {
    "/dcap": device_capability, 
    "/tm": time_resource, 
    "/edev": end_device_list, 
    "/edev/1": end_device,
    "/edev/1/rg": registration,
    "/edev/1/der": der_list, 
    "/edev/1/der/1": der, 
    "/edev/1/der/1/dera": der_availability,
    "/edev/1/der/1/dercap": der_capability,
    "/edev/1/der/1/derg": der_settings,
    "/edev/1/der/1/ders": der_status,
    "/edev/1/fsa": fsa_list, 
    "/edev/1/fsa/1": fsa,
    "/edev/1/fsa/1/derp": program_list, 
    "/edev/1/fsa/1/derp/1": program,
    "/edev/1/fsa/1/derp/1/dderc": default_control, 
    "/edev/1/fsa/1/derp/1/derc": control_list,
    "/edev/1/fsa/1/derp/1/derc/1": control,
    "/rsps": response_set_list,
    "/rsps/1": response_set,
    "/rsps/1/rsp": response_list,    
    "/mup": mirror_usage_point_list,    
    }

