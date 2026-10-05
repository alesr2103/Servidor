"""Estado persistente en memoria para dispositivos, programas y controles."""

from dataclasses import dataclass, field
from .identity import identity_from_certificate_file
import threading
import time

from . import config


@dataclass
class ControlState:
    creation_time: int = 0
    start_time: int = 0
    end_time: int = 0
    duration: int = config.CONTROL_DURATION
    enabled: bool = True
    op_mod_connect: bool = True

    def reset(self):
        self.creation_time = int(time.time())
        self.duration = config.CONTROL_DURATION
        self.start_time = (
            self.creation_time + config.CONTROL_START_DELAY
        )
        self.end_time = self.start_time + self.duration
        self.enabled = True

    def status(self, now=None):
        if not self.enabled:
            return None

        current_time = (
            int(time.time())
            if now is None
            else int(now)
        )

        if current_time < self.start_time:
            return 0

        if current_time < self.end_time:
            return 1

        return None


@dataclass
class MockStore:
    sfdi: int = 0
    lfdi_hex: str = ""
    certificate_fingerprint: str = ""
    registration_time: int = 0

    control: ControlState = field(default_factory=ControlState)
    responses: list[bytes] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock,repr=False,)
    

    def reset(self):
        with self.lock:
            self.control.reset()
            self.responses.clear()

    def add_response(self, response: bytes):
        with self.lock:
            self.responses.append(response)

    def get_responses(self):
        with self.lock:
            return list(self.responses)
    
    def register_client_certificate(
        self,
        certificate_path,
    ):
        identity = identity_from_certificate_file(
            certificate_path
        )

        with self.lock:
            self.sfdi = identity.sfdi
            self.lfdi_hex = identity.lfdi_hex
            self.certificate_fingerprint = (
                identity.fingerprint_sha256
            )
            self.registration_time = int(time.time())

        return identity

    def is_authorized_identity(
        self,
        lfdi_hex,
    ):
        with self.lock:
            return (
                bool(self.lfdi_hex)
                and self.lfdi_hex.lower()
                == lfdi_hex.lower()
            )

STORE = MockStore()
