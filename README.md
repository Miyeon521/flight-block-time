# Flight Block Time

Calculates elapsed flight durations and arrival times across time zone changes, including DST transitions.

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from flight_block_time import FlightCalculator, FlightBlock

calc = FlightCalculator()
block = FlightBlock(
    dep_local=datetime(2024, 7, 15, 12, 0, tzinfo=ZoneInfo("Europe/London")),
    block_minutes=480,
    origin_zone=ZoneInfo("Europe/London"),
    dest_zone=ZoneInfo("America/New_York"),
)
result = calc.calculate(block)
result.arr_local_dest   # 2024-07-15 15:00:00-04:00
result.elapsed          # datetime.timedelta(seconds=28800)
result.arr_utc          # 2024-07-15 19:00:00+00:00
```

## Why

Schedules quote departure and arrival in local wall-clock times, but the actual elapsed block time is a real duration measured in UTC. When origin and destination offsets differ — and especially when a DST transition falls inside the flight — the local times alone do not recover that duration. This library takes an unambiguous departure instant plus a block length in minutes and returns the arrival in both UTC and the destination zone.

## Exports

- `FlightBlock(dep_local: datetime, block_minutes: int, origin_zone: ZoneInfo, dest_zone: ZoneInfo)`
- `FlightCalculator().calculate(block: FlightBlock) -> ArrivalResult`
- `ArrivalResult` with `dep_utc`, `arr_utc`, `arr_local_dest`, `elapsed`
- `InvalidFlightError` raised on invalid construction input

## Edge cases

Departure times must carry a UTC offset (a `ZoneInfo` or fixed offset). Bare local strings are rejected because, at a DST boundary, a wall time like `02:30` may not exist or may exist twice. The library relies on the IANA tz database shipped with Python; if your platform lacks `zoneinfo` data, `ZoneInfo("…")` raises `ZoneInfoNotFoundError` independently of this library.
