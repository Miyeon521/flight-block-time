"""Core logic for calculating elapsed flight durations and arrival times.

A flight's *block time* is the elapsed wall-clock duration from gate-departure
to gate-arrival. When the origin and destination time zones differ, the
arrival time expressed in local zones is not enough to recover that duration,
so the calculator also keeps the arrival UTC instant to make the duration
unambiguous.

Design decision: every local time input is ISO-8601 with a numeric UTC
offset (e.g. ``2024-06-15T14:30+02:00``). We do NOT support bare local
strings such as ``2024-06-15T14:30`` because, in the presence of a DST
boundary, the same local wall time can map to two different UTC instants
(or none at all).  Refusing ambiguous input is preferable to silently
guessing, so we raise :class:`InvalidFlightError` if no offset is present.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


class InvalidFlightError(ValueError):
    """Raised when a flight block cannot be constructed or computed.

    Subclasses ``ValueError`` so callers using ``except ValueError`` still
    work; a dedicated type lets tests assert on the specific failure mode.
    """


@dataclass(frozen=True)
class FlightBlock:
    """A single flight leg with its origin and destination zones.

    Attributes:
        dep_local: Departure as a timezone-aware ``datetime``. Its ``tzinfo``
            carries the offset used at the origin, but we still store
            ``origin_zone`` so that DST re-bases can be applied if the local
            departure offset were ever elided (we currently require it).
        block_minutes: Planned gate-to-gate time in whole minutes.
            Fractional minutes would introduce floating-point comparison
            hazards in tests, so we restrict to integers and the API stays
            deterministic.
        origin_zone, dest_zone: ``ZoneInfo`` objects identifying the IANA
            time zones. They are used for formatting the local arrival in the
            destination zone rather than relying on a bare offset, which is
            essential when the destination changes its UTC offset mid-flight
            due to DST.
    """

    dep_local: datetime
    block_minutes: int
    origin_zone: ZoneInfo
    dest_zone: ZoneInfo

    def __post_init__(self) -> None:
        if self.dep_local.tzinfo is None:
            raise InvalidFlightError(
                "dep_local must be timezone-aware; a bare local time is "
                "ambiguous around DST boundaries."
            )
        if self.block_minutes < 0:
            raise InvalidFlightError("block_minutes must be non-negative")
        if not isinstance(self.origin_zone, ZoneInfo):
            raise InvalidFlightError("origin_zone must be a ZoneInfo instance")
        if not isinstance(self.dest_zone, ZoneInfo):
            raise InvalidFlightError("dest_zone must be a ZoneInfo instance")


@dataclass(frozen=True)
class ArrivalResult:
    """Computed result of a flight block calculation.

    Attributes:
        dep_utc: Departure instant in UTC (``tzinfo=timezone.utc``).
        arr_utc: Arrival instant in UTC (``tzinfo=timezone.utc``).
        arr_local_dest: Arrival wall time in the destination zone.
            Computed by converting ``arr_utc`` into ``dest_zone``; if a DST
            transition happens exactly at arrival, zoneinfo's fold rules pick
            the standard offset, which is the convention used by IATA schedules.
        elapsed: The real elapsed :class:`~datetime.timedelta`.
            Equal to ``arr_utc - dep_utc`` and identical to
            ``timedelta(minutes=block_minutes)``; stored redundantly because
            many callers want a ``timedelta`` and it documents intent.
    """

    dep_utc: datetime
    arr_utc: datetime
    arr_local_dest: datetime
    elapsed: timedelta


class FlightCalculator:
    """Compute arrival times and durations for :class:`FlightBlock` instances.

    The calculator is stateless; it exists as a class so that callers can
    inject a fake clock via the ``now`` argument in tests, avoiding any
    dependence on wall-clock time.
    """

    def __init__(self, now: datetime | None = None) -> None:
        # ``now`` is only used for sanity-checks such as "departure is far in
        # the past" if a caller opts in later; it is never consulted in the
        # core arithmetic so results stay deterministic. We store it so tests
        # can pass a frozen clock without affecting block-time math.
        self._now = now

    def calculate(self, block: FlightBlock) -> ArrivalResult:
        """Return the :class:`ArrivalResult` for *block*.

        The math is intentionally trivial: convert the departure to UTC, add
        ``block_minutes``, and convert the arrival UTC instant back into the
        destination zone. The complexity we care about lives in the DST
        handling performed by ``datetime.astimezone`` and by the
        :class:`ZoneInfo` data, not in our code.
        """
        dep_utc = block.dep_local.astimezone(_UTC)
        arr_utc = dep_utc + timedelta(minutes=block.block_minutes)
        arr_local_dest = arr_utc.astimezone(block.dest_zone)
        return ArrivalResult(
            dep_utc=dep_utc,
            arr_utc=arr_utc,
            arr_local_dest=arr_local_dest,
            elapsed=arr_utc - dep_utc,
        )


# Module-level constant kept private; callers should not rely on a specific
# UTC singleton since ``datetime.timezone.utc`` is the canonical one.
_UTC = __import__("datetime").timezone.utc
