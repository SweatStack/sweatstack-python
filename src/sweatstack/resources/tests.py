"""``client.tests``: ``/api/v1/tests/...`` (fitness assessments, not unit tests)."""

from __future__ import annotations

import builtins
from datetime import date, datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal, overload

from .._frames import ListOutput
from ..schemas import Sport, TestDetails, TestResults, TestSummary, TraceResolution
from ._app_metadata import AppMetadata
from ._base import Resource, SportParam, TagParam

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa

_PAGE_SIZE = 50  # the server's maximum page size for tests


class Tests(Resource):
    """Tests: fitness assessments with structured results (thresholds, VO2max, critical power)."""

    __test__ = False  # not a pytest test class, despite the name

    @cached_property
    def app_metadata(self) -> AppMetadata:
        """This app's metadata on tests: ``set(test_id, data=...)`` and ``delete``."""
        return AppMetadata(self._client, "tests")

    @overload
    def list(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: SportParam | None = None,
        tags: TagParam | None = None,
        created_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
        output: Literal["models"] | None = None,
    ) -> builtins.list[TestSummary]: ...

    @overload
    def list(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: SportParam | None = None,
        tags: TagParam | None = None,
        created_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
        output: Literal["pandas"],
    ) -> pd.DataFrame: ...

    @overload
    def list(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: SportParam | None = None,
        tags: TagParam | None = None,
        created_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
        output: Literal["polars"],
    ) -> pl.DataFrame: ...

    @overload
    def list(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: SportParam | None = None,
        tags: TagParam | None = None,
        created_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
        output: Literal["arrow"],
    ) -> pa.Table: ...

    def list(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: SportParam | None = None,
        tags: TagParam | None = None,
        created_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
        output: ListOutput | None = None,
    ) -> builtins.list[TestSummary] | pd.DataFrame | pl.DataFrame | pa.Table:
        """Lists tests, newest first.

        Endpoint: ``GET /api/v1/tests/``

        Args:
            start: Only tests on or after this date.
            end: Only tests on or before this date.
            sport: One sport or a list; a test matches any of them.
            tags: One tag or a list; a test must have all of them.
            created_by: Only tests created by this app (client ID).
            limit: How many tests to return. The client pages through the endpoint until it
                has this many or there are no more.
            offset: How many of the newest matching tests to skip.
            output: ``"models"`` (default), ``"pandas"``, ``"polars"`` or ``"arrow"``.

        Returns:
            TestSummary objects, or a frame with one row per test; ``results`` is flattened to
            dotted columns in pandas and a struct in Polars and Arrow.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            tests = client.tests.list(sport="cycling", output="pandas")
            ```
        """
        params: dict[str, Any] = {}
        if start is not None:
            params["start"] = start.isoformat()
        if end is not None:
            params["end"] = end.isoformat()
        if sport is not None:
            params["sport"] = self._wire(sport)
        if tags is not None:
            params["tags"] = self._wire(tags)
        if created_by is not None:
            params["created_by"] = created_by
        tests = list(
            self._paginate(
                "/api/v1/tests/",
                params,
                TestSummary,
                page_size=_PAGE_SIZE,
                limit=limit,
                offset=offset,
            )
        )
        return self._client._frame_from_models(tests, TestSummary, output, flatten=("results",))

    def retrieve(
        self,
        test_id: str,
        *,
        trace_resolution: TraceResolution | str = TraceResolution.auto,
    ) -> TestDetails:
        """Retrieves a test with its traces and the activities it overlaps.

        Endpoint: ``GET /api/v1/tests/{test_id}``

        Args:
            test_id: The test's ID.
            trace_resolution: Which traces the ``traces`` list holds (``activities`` is always
                matched by time overlap). Sent as the ``traces`` query parameter.

                - ``"auto"`` (default): traces inside the test's time range, plus traces linked
                  to this test, minus traces linked to another test.
                - ``"linked"``: only traces linked to this test, whatever their timestamp.

        Returns:
            TestDetails: The test with its traces and activities.

        Raises:
            SweatStackNotFoundError: If the test does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            test = client.tests.retrieve("test_123", trace_resolution="linked")
            print([trace.lactate for trace in test.traces])
            ```
        """
        resolution = self._client._enums_to_strings([trace_resolution])[0]
        params = {} if resolution == TraceResolution.auto.value else {"traces": resolution}
        response = self._client._request("get", f"/api/v1/tests/{test_id}", params=params)
        return TestDetails.model_validate(response.json())

    def create(
        self,
        *,
        sport: Sport | str,
        start: datetime,
        title: str | None = None,
        end: datetime | None = None,
        results: TestResults | None = None,
        tags: builtins.list[str] | None = None,
    ) -> TestSummary:
        """Creates a test.

        Endpoint: ``POST /api/v1/tests/``

        Args:
            sport: The sport.
            start: When the test started. Must be timezone-aware.
            title: A title.
            end: When the test ended. Must be timezone-aware. Defaults to ``start`` plus three
                hours, server-side.
            results: Structured results: thresholds, capacities, and so on.
            tags: Tags.

        Returns:
            TestSummary: The created test.

        Raises:
            ValueError: If ``start`` or ``end`` is timezone-naive.
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from datetime import datetime, timezone

            from sweatstack import Client, Marker, TestResults

            client = Client()
            test = client.tests.create(
                sport="cycling",
                start=datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
                title="Lactate step test",
                results=TestResults(lt1=Marker(power=210), lt2=Marker(power=285)),
            )
            ```
        """
        body = self._body(
            sport=sport, start=start, title=title, end=end, results=results, tags=tags
        )
        response = self._client._request("post", "/api/v1/tests/", json=body)
        return TestSummary.model_validate(response.json())

    def replace(
        self,
        test_id: str,
        *,
        sport: Sport | str,
        start: datetime,
        title: str | None = None,
        end: datetime | None = None,
        results: TestResults | None = None,
        tags: builtins.list[str] | None = None,
    ) -> None:
        """Replaces every field of a test.

        Endpoint: ``PUT /api/v1/tests/{test_id}``

        **Every field you leave out is cleared.** To change one field, retrieve the test first
        and pass all its fields back.

        Args:
            test_id: The test's ID.
            sport: The sport.
            start: When the test started. Must be timezone-aware.
            title: A title.
            end: When the test ended. Must be timezone-aware.
            results: Structured results.
            tags: Tags.

        Raises:
            ValueError: If ``start`` or ``end`` is timezone-naive.
            SweatStackNotFoundError: If the test does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            test = client.tests.retrieve("test_123")
            client.tests.replace(
                test.id, sport=test.sport, start=test.start, end=test.end,
                title="Renamed", results=test.results, tags=test.tags,
            )
            ```
        """
        body = self._body(
            sport=sport, start=start, title=title, end=end, results=results, tags=tags
        )
        self._client._request("put", f"/api/v1/tests/{test_id}", json=body)

    def delete(self, test_id: str) -> None:
        """Deletes a test.

        Endpoint: ``DELETE /api/v1/tests/{test_id}``

        Args:
            test_id: The test's ID.

        Raises:
            SweatStackNotFoundError: If the test does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            client.tests.delete("test_123")
            ```
        """
        self._client._request("delete", f"/api/v1/tests/{test_id}")

    def _body(
        self,
        *,
        sport: Sport | str,
        start: datetime,
        title: str | None,
        end: datetime | None,
        results: TestResults | None,
        tags: builtins.list[str] | None,
    ) -> dict:
        """The full-replace request body: every field, ``None`` included."""
        self._client._require_aware(start, "start")
        if end is not None:
            self._client._require_aware(end, "end")
        return {
            "title": title,
            "sport": self._client._enums_to_strings([sport])[0],
            "start": start.isoformat(),
            "end": end.isoformat() if end is not None else None,
            "results": results.model_dump() if results is not None else None,
            "tags": tags,
        }
