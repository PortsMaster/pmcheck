from dataclasses import dataclass, asdict

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"
ORDER = {ERROR: 0, WARN: 1, INFO: 2}


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0
    fix: str = ""
    snippet: str = ""

    def dict(self):
        return {k: v for k, v in asdict(self).items() if v not in ("", 0)}
