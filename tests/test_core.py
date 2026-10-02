from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flight_block_time import (
    FlightCalculator,
    FlightBlock,
    InvalidFlightError,
    ArrivalResult,
)


class FlightBlockConstructionTests(unittest.TestCase):
    def test_requires_timezone_aware_departure(self) -> None:
        with self.assertRaises(InvalidFlightError):
            FlightBlock(
                dep_local=datetime(2024, 6, 15, 14, 30),
                block_minutes=300,
                origin_zone=ZoneInfo("Europe/Berlin"),
                dest_zone=ZoneInfo("America/New_York"),
            )

    def test_rejects_negative_block_minutes(self) -> None:
        with self.assertRaises(InvalidFlightError):
            FlightBlock(
                dep_local=datetime(2024, 6, 15, 14, 30, tzinfo=timezone.utc),
                block_minutes=-1,
                origin_zone=ZoneInfo("UTC"),
                dest_zone=ZoneInfo("UTC"),
            )

    def test_rejects_non_zoneinfo_zones(self) -> None:
        with self.assertRaises(InvalidFlightError):
            FlightBlock(
                dep_local=datetime(2024, 6, 15, 14, 30, tzinfo=timezone.utc),
                block_minutes=60,
                origin_zone=timezone.utc,  # type: ignore[arg-type]
                dest_zone=ZoneInfo("UTC"),
            )


class CalculationTests(unittest.TestCase):
    def test_same_timezone_simple(self) -> None:
        dep = datetime(2024, 1, 15, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        block = FlightBlock(
            dep_local=dep,
            block_minutes=180,
            origin_zone=ZoneInfo("America/Los_Angeles"),
            dest_zone=ZoneInfo("America/Los_Angeles"),
        )
        result = FlightCalculator().calculate(block)
        self.assertEqual(result.dep_utc, dep.astimezone(timezone.utc))
        self.assertEqual(
            result.arr_utc,
            dep.astimezone(timezone.utc) + timedelta(minutes=180),
        )
        self.assertEqual(result.elapsed, timedelta(minutes=180))
        # Local arrival is 12:00 PT in January (UTC-8).
        self.assertEqual(result.arr_local_dest.hour, 12)
        self.assertEqual(result.arr_local_dest.minute, 0)

    def test_cross_timezone_westbound(self) -> None:
        # LHR -> JFK, 8h block, dep 12:00 London (UTC+1 in summer).
        dep = datetime(2024, 7, 15, 12, 0, tzinfo=ZoneInfo("Europe/London"))
        block = FlightBlock(
            dep_local=dep,
            block_minutes=480,
            origin_zone=ZoneInfo("Europe/London"),
            dest_zone=ZoneInfo("America/New_York"),
        )
        result = FlightCalculator().calculate(block)
        # Departure UTC = 11:00; arrival UTC = 19:00; JFK in July = UTC-4 => 15:00.
        self.assertEqual(result.dep_utc, datetime(2024, 7, 15, 11, 0, tzinfo=timezone.utc))
        self.assertEqual(result.arr_utc, datetime(2024, 7, 15, 19, 0, tzinfo=timezone.utc))
        self.assertEqual(result.arr_local_dest.hour, 15)
        self.assertEqual(result.elapsed, timedelta(minutes=480))

    def test_cross_timezone_eastbound_with_dst_loss(self) -> None:
        # SFO -> FRA, 11h block, dep 14:30 PT (UTC-7 in summer).
        # Arrival UTC = 21:30 + 11h = next day 08:30; FRA in summer = UTC+2 => 10:30.
        dep = datetime(2024, 7, 20, 14, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
        block = FlightBlock(
            dep_local=dep,
            block_minutes=660,
            origin_zone=ZoneInfo("America/Los_Angeles"),
            dest_zone=ZoneInfo("Europe/Berlin"),
        )
        result = FlightCalculator().calculate(block)
        self.assertEqual(
            result.arr_local_dest,
            datetime(2024, 7, 21, 10, 30, tzinfo=ZoneInfo("Europe/Berlin")),
        )
        self.assertEqual(result.arr_utc.day, 21)
        self.assertEqual(result.elapsed, timedelta(minutes=660))

    def test_flight_crossing_dst_spring_forward_in_destination(self) -> None:
        # US spring-forward: 2024-03-10 02:00 -> 03:00 local.
        # Depart SFO at 2024-03-09 22:00 PT (standard time, UTC-8)
        # with a 6h block: arr_utc = 06:00+6 = 12:00 UTC.
        # In America/New_York on 2024-03-10, DST began at 02:00 EST (UTC-5 -> UTC-4),
        # so 12:00 UTC = 08:00 EDT.
        dep = datetime(2024, 3, 9, 22, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        block = FlightBlock(
            dep_local=dep,
            block_minutes=360,
            origin_zone=ZoneInfo("America/Los_Angeles"),
            dest_zone=ZoneInfo("America/New_York"),
        )
        result = FlightCalculator().calculate(block)
        self.assertEqual(result.dep_utc, datetime(2024, 3, 10, 6, 0, tzinfo=timezone.utc))
        self.assertEqual(result.arr_utc, datetime(2024, 3, 10, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(result.arr_local_dest.hour, 8)
        self.assertEqual(result.arr_local_dest.tzname(), "EDT")

    def test_arrival_result_is_frozen_and_consistent(self) -> None:
        dep = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        block = FlightBlock(
            dep_local=dep,
            block_minutes=60,
            origin_zone=ZoneInfo("UTC"),
            dest_zone=ZoneInfo("UTC"),
        )
        r = FlightCalculator().calculate(block)
        self.assertIsInstance(r, ArrivalResult)
        self.assertEqual(r.arr_utc - r.dep_utc, r.elapsed)
        # dataclass is frozen
        with self.assertRaises(Exception):
            r.dep_utc = datetime(2020, 1, 1, tzinfo=timezone.utc)  # type: ignore[misc]

    def test_zero_block_minutes(self) -> None:
        dep = datetime(2024, 5, 1, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        block = FlightBlock(
            dep_local=dep,
            block_minutes=0,
            origin_zone=ZoneInfo("Asia/Tokyo"),
            dest_zone=ZoneInfo("Asia/Tokyo"),
        )
        r = FlightCalculator().calculate(block)
        self.assertEqual(r.arr_utc, r.dep_utc)
        self.assertEqual(r.elapsed, timedelta(0))

    def test_calculator_accepts_injected_now(self) -> None:
        # Ensures the constructor signature accepts a clock without affecting
        # results, so tests can stay deterministic.
        frozen = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        calc = FlightCalculator(now=frozen)
        dep = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        block = FlightBlock(
            dep_local=dep,
            block_minutes=120,
            origin_zone=ZoneInfo("UTC"),
            dest_zone=ZoneInfo("UTC"),
        )
        r = calc.calculate(block)
        self.assertEqual(r.arr_utc, datetime(2024, 6, 1, 14, 0, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
