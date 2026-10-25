"""Problems found while compiling and resolving classes."""

from collections import Counter
from dataclasses import dataclass
from dataclasses import field
from typing import Literal

Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True, order=True)
class Problem:
    """One problem, located in a source file."""

    file: str
    line: int
    severity: Severity
    code: str
    message: str

    def format(self) -> str:
        location = f"{self.file}:{self.line}" if self.line else self.file
        return f"{self.severity.upper()} [{self.code}] {location}: {self.message}"


@dataclass
class Report:
    """Collects problems; never raises."""

    problems: list[Problem] = field(default_factory=list)

    def add(
        self,
        severity: Severity,
        code: str,
        message: str,
        file: str = "",
        line: int | None = None,
    ) -> None:
        self.problems.append(Problem(file, line or 0, severity, code, message))

    def error(
        self, code: str, message: str, file: str = "", line: int | None = None
    ) -> None:
        self.add("error", code, message, file, line)

    def warning(
        self, code: str, message: str, file: str = "", line: int | None = None
    ) -> None:
        self.add("warning", code, message, file, line)

    def info(
        self, code: str, message: str, file: str = "", line: int | None = None
    ) -> None:
        self.add("info", code, message, file, line)

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == "error"]

    def counts(self) -> Counter:
        """Number of problems per ``(severity, code)``."""
        return Counter((p.severity, p.code) for p in self.problems)

    def render(self) -> str:
        """The report as deterministic text: a summary, then every problem."""
        problems = sorted(set(self.problems))
        lines = ["# NXDS build report", ""]
        totals = Counter(p.severity for p in problems)
        lines.append(
            "errors: {}, warnings: {}, infos: {}".format(
                totals["error"], totals["warning"], totals["info"]
            )
        )
        lines.append("")
        lines.append("## Counts by code")
        for (severity, code), count in sorted(
            Counter((p.severity, p.code) for p in problems).items()
        ):
            lines.append(f"{severity:8s} {code:32s} {count}")
        lines.append("")
        lines.append("## Problems")
        lines.extend(p.format() for p in problems)
        return "\n".join(lines) + "\n"
