"""toxindb - RAG retrieval-time poisoning detector."""

from .trace import Trace, IngestEvent, QueryEvent, CanaryClaim
from .engine import Engine
from .heuristics import Alert
from .models import Result
from .config import Config
from .sarif import alerts_to_sarif

__all__ = [
    "Trace",
    "IngestEvent",
    "QueryEvent",
    "CanaryClaim",
    "Engine",
    "Alert",
    "Result",
    "Config",
    "alerts_to_sarif",
]

__version__ = "1.0.0"
