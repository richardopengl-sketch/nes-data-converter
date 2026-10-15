from dataclasses import dataclass


@dataclass
class Canonical:
    input_context: dict
    expected_result: dict[str, str]
    metadata: dict
