from dataclasses import dataclass, field


class ConversionError(Exception):
    """An actionable input, network or rendering failure."""


@dataclass(frozen=True)
class SourceFile:
    path: str
    content: str

    @property
    def lines(self) -> int:
        return len(self.content.splitlines())


@dataclass
class Document:
    title: str
    origin: str
    ref: str
    revision: str = ""
    files: list[SourceFile] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Options:
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    language: str | None = None
    min_lines: int = 1
    max_files: int = 500
    max_file_bytes: int = 256_000
    max_total_bytes: int = 20_000_000
    max_download_bytes: int = 50_000_000

    def __post_init__(self):
        for name in (
            "min_lines",
            "max_files",
            "max_file_bytes",
            "max_total_bytes",
            "max_download_bytes",
        ):
            if getattr(self, name) <= 0:
                raise ConversionError(f"{name} must be positive.")
