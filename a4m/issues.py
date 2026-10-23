"""Validation issues, shared by the loader, validator and ADR checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    code: str  # stable, machine-readable (tests and LLMs key off it)
    message: str
    file: str = ""
    ref: str = ""  # element / relationship / view / ADR id the issue is about

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        where = f"{self.file}: " if self.file else ""
        ref = f"[{self.ref}] " if self.ref else ""
        return f"{self.severity.upper():7} {self.code:24} {where}{ref}{self.message}"


def error(code: str, message: str, file: str = "", ref: str = "") -> Issue:
    return Issue("error", code, message, file, ref)


def warning(code: str, message: str, file: str = "", ref: str = "") -> Issue:
    return Issue("warning", code, message, file, ref)
