"""Installer/API policy, shared with browser via the same static JSON."""
import json
from pathlib import Path
POLICY = json.loads((Path(__file__).parent / 'static/password-policy.json').read_text())
MIN_LENGTH = POLICY['min_length']
MAX_LENGTH = POLICY['max_length']


def validate_password(value: str) -> str:
    if not isinstance(value, str) or not MIN_LENGTH <= len(value) <= MAX_LENGTH or any(
        low <= ord(char) <= high for char in value for low, high in POLICY['forbidden_ranges']
    ):
        raise ValueError(POLICY['message'])
    return value
