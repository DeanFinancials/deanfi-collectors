"""Strip API keys from text before it is printed or logged.

A requests exception's message includes the prepared URL, so a key sent as a
query parameter (FRED ``api_key``, Alpha Vantage ``apikey``, Finnhub ``token``)
ends up in ``str(e)``. Pass any such text through ``redact_secrets`` first.
"""
from __future__ import annotations

import re

_PLACEHOLDER = "REDACTED"

# token=..., apikey=..., api_key=... (also access_token= etc.) in URLs and query strings.
_QUERY_SECRET = re.compile(r"(?i)((?:api_?key|token)=)[^&\s'\"#<>)]+")
# 'api_key': '...' in a printed dict.
_DICT_SECRET = re.compile(r"(?i)(['\"](?:api_?key|token)['\"]\s*:\s*['\"])[^'\"]*")


def redact_secrets(text: object) -> str:
    """Return ``str(text)`` with api_key/apikey/token values replaced by REDACTED."""
    s = str(text)
    s = _QUERY_SECRET.sub(rf"\g<1>{_PLACEHOLDER}", s)
    return _DICT_SECRET.sub(rf"\g<1>{_PLACEHOLDER}", s)
