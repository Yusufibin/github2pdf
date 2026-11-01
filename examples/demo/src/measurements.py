"""Collect a few measurements and prepare a readable summary."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Measurement:
    sensor: str
    temperature: float
    valid: bool = True


def summarize(samples: list[Measurement]) -> dict:
    # Only validated readings contribute to the mean.
    readings = [sample.temperature for sample in samples if sample.valid]
    return {
        "count": len(readings),
        "mean": round(sum(readings) / len(readings), 2) if readings else None,
        "label": "Température moyenne",
    }


if __name__ == "__main__":
    samples = [
        Measurement("Libreville", 28.4),
        Measurement("Port-Gentil", 27.8),
        Measurement("Test sensor", -999.0, valid=False),
    ]
    print(summarize(samples))
