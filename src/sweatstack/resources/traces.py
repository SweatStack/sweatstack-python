"""``client.traces``: ``/api/v1/traces/...``."""

from __future__ import annotations

import builtins
from datetime import date, datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal, overload

from .._frames import ListOutput
from ..schemas import Sport, TraceDetails
from ._app_metadata import AppMetadata
from ._base import Resource, SportParam, TagParam

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa

_PAGE_SIZE = 100


class Traces(Resource):
    """Traces: point measurements such as lactate, RPE or heart rate, optionally linked to a test."""

    @cached_property
    def app_metadata(self) -> AppMetadata:
        """This app's metadata on traces: ``set(trace_id, data=...)`` and ``delete``."""
        return AppMetadata(self._client, "traces")

    @overload
    def list(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: SportParam | None = None,
        tags: TagParam | None = None,
        limit: int = 100,
        offset: int = 0,
        output: Literal["models"] | None = None,
    ) -> builtins.list[TraceDetails]: ...

    @overload
    def list(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: SportParam | None = None,
        tags: TagParam | None = None,
        limit: int = 100,
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
        limit: int = 100,
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
        limit: int = 100,
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
        limit: int = 100,
        offset: int = 0,
        output: ListOutput | None = None,
    ) -> builtins.list[TraceDetails] | pd.DataFrame | pl.DataFrame | pa.Table:
        """Lists traces, newest first.

        Endpoint: ``GET /api/v1/traces/``

        Args:
            start: Only traces on or after this date.
            end: Only traces on or before this date.
            sport: One sport or a list; a trace matches any of them.
            tags: One tag or a list; a trace must have all of them.
            limit: How many traces to return. The client pages through the endpoint until it
                has this many or there are no more.
            offset: How many of the newest matching traces to skip.
            output: ``"models"`` (default), ``"pandas"``, ``"polars"`` or ``"arrow"``.

        Returns:
            TraceDetails objects, or a frame with one row per trace.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            traces = client.traces.list(tags="lactate", limit=50)
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
        traces = list(
            self._paginate(
                "/api/v1/traces/",
                params,
                TraceDetails,
                page_size=_PAGE_SIZE,
                limit=limit,
                offset=offset,
            )
        )
        return self._client._frame_from_models(
            traces, TraceDetails, output, flatten=("activity", "lap")
        )

    def create(
        self,
        *,
        timestamp: datetime,
        lactate: float | None = None,
        rpe: int | None = None,
        notes: str | None = None,
        power: int | None = None,
        speed: float | None = None,
        heart_rate: int | None = None,
        tags: builtins.list[str] | None = None,
        sport: Sport | str | None = None,
        test_id: str | None = None,
    ) -> TraceDetails:
        """Creates a trace.

        Endpoint: ``POST /api/v1/traces/``

        Args:
            timestamp: When the measurement was taken. Must be timezone-aware; the offset is
                stored alongside the instant.
            lactate: Blood lactate, mmol/L.
            rpe: Rating of perceived exertion.
            notes: Free text.
            power: Power, W.
            speed: Speed, m/s.
            heart_rate: Heart rate, bpm.
            tags: Tags.
            sport: The sport.
            test_id: Link the trace to this test. A linked trace belongs to the test whatever
                its timestamp.

        Returns:
            TraceDetails: The created trace.

        Raises:
            ValueError: If ``timestamp`` is timezone-naive.
            SweatStackNotFoundError: If ``test_id`` does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from datetime import datetime, timezone

            from sweatstack import Client

            client = Client()
            trace = client.traces.create(
                timestamp=datetime.now(timezone.utc), lactate=2.1, heart_rate=152, tags=["lactate"]
            )
            ```
        """
        body = self._body(
            timestamp=timestamp,
            lactate=lactate,
            rpe=rpe,
            notes=notes,
            power=power,
            speed=speed,
            heart_rate=heart_rate,
            tags=tags,
            sport=sport,
            test_id=test_id,
        )
        response = self._client._request("post", "/api/v1/traces/", json=body)
        return TraceDetails.model_validate(response.json())

    def replace(
        self,
        trace_id: str,
        *,
        timestamp: datetime,
        lactate: float | None = None,
        rpe: int | None = None,
        notes: str | None = None,
        power: int | None = None,
        speed: float | None = None,
        heart_rate: int | None = None,
        tags: builtins.list[str] | None = None,
        sport: Sport | str | None = None,
        test_id: str | None = None,
    ) -> None:
        """Replaces every field of a trace.

        Endpoint: ``PUT /api/v1/traces/{trace_id}``

        **Every field you leave out is cleared**, including ``test_id``: a trace linked to a
        test is unlinked unless you pass its ``test_id`` again. To change one field, retrieve
        the trace first and pass all its fields back.

        Args:
            trace_id: The trace's ID.
            timestamp: When the measurement was taken. Must be timezone-aware.
            lactate: Blood lactate, mmol/L.
            rpe: Rating of perceived exertion.
            notes: Free text.
            power: Power, W.
            speed: Speed, m/s.
            heart_rate: Heart rate, bpm.
            tags: Tags.
            sport: The sport.
            test_id: The test this trace is linked to; ``None`` unlinks it.

        Raises:
            ValueError: If ``timestamp`` is timezone-naive.
            SweatStackNotFoundError: If the trace or ``test_id`` does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from datetime import datetime, timezone

            from sweatstack import Client

            client = Client()
            client.traces.replace(
                "trace_123", timestamp=datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc), lactate=2.4
            )
            ```
        """
        body = self._body(
            timestamp=timestamp,
            lactate=lactate,
            rpe=rpe,
            notes=notes,
            power=power,
            speed=speed,
            heart_rate=heart_rate,
            tags=tags,
            sport=sport,
            test_id=test_id,
        )
        self._client._request("put", f"/api/v1/traces/{trace_id}", json=body)

    def delete(self, trace_id: str) -> None:
        """Deletes a trace.

        Endpoint: ``DELETE /api/v1/traces/{trace_id}``

        Args:
            trace_id: The trace's ID.

        Raises:
            SweatStackNotFoundError: If the trace does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            client.traces.delete("trace_123")
            ```
        """
        self._client._request("delete", f"/api/v1/traces/{trace_id}")

    def _body(self, *, timestamp: datetime, sport: Sport | str | None, **fields: Any) -> dict:
        """The full-replace request body: every field, ``None`` included."""
        self._client._require_aware(timestamp, "timestamp")
        return {
            "timestamp": timestamp.isoformat(),
            "sport": self._client._enums_to_strings([sport])[0] if sport else None,
            **fields,
        }
