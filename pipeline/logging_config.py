"""
Shared logging setup for Cloud Run's structured JSON convention. Plain
print() shows every entry as severity "DEFAULT" in Cloud Logging (confirmed
in production) -- writing JSON with a "severity" field lets Cloud Run parse
real INFO/WARNING/ERROR levels automatically, no new dependency needed.

Usage: logger = get_logger(__name__), then logger.info(...)/.warning(...)/
.error(...) instead of print(). For exceptions, logger.exception(...)
automatically captures the traceback the same way traceback.print_exc() did.
"""

import json
import logging
import sys
from datetime import datetime, timezone


class CloudRunJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:  # avoid duplicate handlers if a module gets imported twice
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(CloudRunJsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger