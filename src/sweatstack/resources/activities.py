"""``client.activities``: ``/api/v1/activities/...``."""

from __future__ import annotations

import builtins
import logging
import time
from collections.abc import Generator, Sequence
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Literal, overload

from .._frames import FrameOutput, ListOutput
from ..exceptions import SweatStackConnectionError
from ..schemas import ActivityDetails, ActivitySummary, BackfillStatus, SourceResponse, Sport
from ._app_metadata import ActivityAppMetadata
from ._base import (
    IntensityMetric,
    MetricParam,
    Resource,
    SportParam,
    TagParam,
    _with_durations,
)

if TYPE_CHECKING:  # frame libraries are optional extras; only annotations need them here
    import pandas as pd
    import polars as pl
    import pyarrow as pa

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100


class Activities(Resource):
    """Activities: the summaries, their time series, and analyses over one or many."""

    @cached_property
    def app_metadata(self) -> ActivityAppMetadata:
        """This app's metadata on activities: ``set(activity_id, data=...)`` and ``delete``."""
        return ActivityAppMetadata(self._client)

    @cached_property
    def longitudinal(self) -> Longitudinal:
        """Data and analyses across many activities: ``data``, ``mean_max`` and ``awd``."""
        return Longitudinal(self._client)

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
    ) -> builtins.list[ActivitySummary]: ...

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
    ) -> builtins.list[ActivitySummary] | pd.DataFrame | pl.DataFrame | pa.Table:
        """Lists activities, newest first.

        Endpoint: ``GET /api/v1/activities/``

        Args:
            start: Only activities on or after this date.
            end: Only activities on or before this date.
            sport: One sport or a list; an activity matches any of them. A parent sport
                (``"cycling"``) also matches its sub-sports.
            tags: One tag or a list; an activity must have all of them.
            limit: How many activities to return. The client pages through the endpoint
                until it has this many or there are no more.
            offset: How many of the newest matching activities to skip.
            output: ``"models"`` (default), ``"pandas"``, ``"polars"`` or ``"arrow"``. Overrides
                the client-level default for this call.

        Returns:
            ActivitySummary objects, or a frame with one row per activity. Nested fields are
            flattened to dotted columns in pandas and typed structs in Polars and Arrow.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from datetime import date

            from sweatstack import Client

            client = Client()
            rides = client.activities.list(sport="cycling", start=date(2026, 1, 1), limit=20)
            frame = client.activities.list(output="polars")
            ```
        """
        params: dict = {}
        if start is not None:
            params["start"] = start.isoformat()
        if end is not None:
            params["end"] = end.isoformat()
        if sport is not None:
            params["sport"] = self._wire(sport)
        if tags is not None:
            params["tags"] = self._wire(tags)
        activities = list(
            self._paginate(
                "/api/v1/activities/",
                params,
                ActivitySummary,
                page_size=_PAGE_SIZE,
                limit=limit,
                offset=offset,
            )
        )
        return self._client._frame_from_models(
            activities, ActivitySummary, output, flatten=("summary", "laps", "traces")
        )

    def retrieve(self, activity_id: str) -> ActivityDetails:
        """Retrieves one activity with its summary and laps.

        Endpoint: ``GET /api/v1/activities/{activity_id}``

        Args:
            activity_id: The activity's ID.

        Returns:
            ActivityDetails: The activity.

        Raises:
            SweatStackNotFoundError: If the activity does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            activity = client.activities.retrieve("act_123")
            print(activity.sport, activity.start)
            ```
        """
        response = self._client._request("get", f"/api/v1/activities/{activity_id}")
        return ActivityDetails.model_validate(response.json())

    def latest(self, *, sport: Sport | str | None = None) -> ActivityDetails | None:
        """Retrieves the most recent activity, or ``None`` if there is none.

        Endpoint: ``GET /api/v1/activities/latest``

        Args:
            sport: Only consider this sport. A parent sport (``"cycling"``) also matches
                its sub-sports.

        Returns:
            ActivityDetails | None: The most recent matching activity, or ``None`` when the
            user has no matching activity.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            latest = client.activities.latest(sport="cycling")
            if latest is not None:
                data = client.activities.data(latest.id)
            ```
        """
        params = {"sport": self._client._enums_to_strings([sport])[0]} if sport else {}
        body = self._client._request("get", "/api/v1/activities/latest", params=params).json()
        return ActivityDetails.model_validate(body) if body is not None else None

    @overload
    def data(
        self,
        activity_id: str,
        *,
        segmentation_on: IntensityMetric | None = None,
        metrics: MetricParam | None = None,
        output: None = None,
    ) -> pd.DataFrame | pl.DataFrame: ...

    @overload
    def data(
        self,
        activity_id: str,
        *,
        segmentation_on: IntensityMetric | None = None,
        metrics: MetricParam | None = None,
        output: Literal["pandas"],
    ) -> pd.DataFrame: ...

    @overload
    def data(
        self,
        activity_id: str,
        *,
        segmentation_on: IntensityMetric | None = None,
        metrics: MetricParam | None = None,
        output: Literal["polars"],
    ) -> pl.DataFrame: ...

    @overload
    def data(
        self,
        activity_id: str,
        *,
        segmentation_on: IntensityMetric | None = None,
        metrics: MetricParam | None = None,
        output: Literal["arrow"],
    ) -> pa.Table: ...

    @overload
    def data(
        self,
        activity_id: str,
        *,
        segmentation_on: IntensityMetric | None = None,
        metrics: MetricParam | None = None,
        output: Literal["bytes"],
    ) -> bytes: ...

    def data(
        self,
        activity_id: str,
        *,
        segmentation_on: IntensityMetric | None = None,
        metrics: MetricParam | None = None,
        output: FrameOutput | None = None,
    ) -> pd.DataFrame | pl.DataFrame | pa.Table | bytes:
        """Retrieves an activity's time series, one row per sample.

        Endpoint: ``GET /api/v1/activities/{activity_id}/data``

        Args:
            activity_id: The activity's ID.
            segmentation_on: Downsample with AISC (Adaptive Intensity Segmentation Codec),
                keyed on ``"power"`` or ``"speed"``. Omit for every sample.
            metrics: One metric or a list. Defaults to the server's selection.
            output: ``"pandas"``, ``"polars"``, ``"arrow"`` or ``"bytes"`` (the raw parquet
                response). Defaults to the installed frame library, Polars if both are.

        Returns:
            A frame with a timezone-aware UTC ``timestamp`` column, ``timestamp_local``, and
            one column per metric.

        Raises:
            SweatStackNotFoundError: If the activity does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            latest = client.activities.latest()
            df = client.activities.data(latest.id, metrics=["power", "heart_rate"], output="polars")
            ```
        """
        params: dict = {}
        if segmentation_on is not None:
            params["segmentation_on"] = self._client._enums_to_strings([segmentation_on])[0]
        if metrics is not None:
            params["metrics"] = self._wire(metrics)
        response = self._client._request(
            "get", f"/api/v1/activities/{activity_id}/data", params=params
        )
        return self._client._read_frame(response.content, output)

    @overload
    def mean_max(
        self,
        activity_id: str,
        *,
        metric: IntensityMetric,
        durations: Sequence[int] | Literal["all"] | None = None,
        output: None = None,
    ) -> pd.DataFrame | pl.DataFrame: ...

    @overload
    def mean_max(
        self,
        activity_id: str,
        *,
        metric: IntensityMetric,
        durations: Sequence[int] | Literal["all"] | None = None,
        output: Literal["pandas"],
    ) -> pd.DataFrame: ...

    @overload
    def mean_max(
        self,
        activity_id: str,
        *,
        metric: IntensityMetric,
        durations: Sequence[int] | Literal["all"] | None = None,
        output: Literal["polars"],
    ) -> pl.DataFrame: ...

    @overload
    def mean_max(
        self,
        activity_id: str,
        *,
        metric: IntensityMetric,
        durations: Sequence[int] | Literal["all"] | None = None,
        output: Literal["arrow"],
    ) -> pa.Table: ...

    @overload
    def mean_max(
        self,
        activity_id: str,
        *,
        metric: IntensityMetric,
        durations: Sequence[int] | Literal["all"] | None = None,
        output: Literal["bytes"],
    ) -> bytes: ...

    def mean_max(
        self,
        activity_id: str,
        *,
        metric: IntensityMetric,
        durations: Sequence[int] | Literal["all"] | None = None,
        output: FrameOutput | None = None,
    ) -> pd.DataFrame | pl.DataFrame | pa.Table | bytes:
        """Retrieves an activity's mean-max curve: the best average for each duration.

        Endpoint: ``GET /api/v1/activities/{activity_id}/mean-max``

        Args:
            activity_id: The activity's ID.
            metric: ``"power"`` or ``"speed"``.
            durations: In seconds. ``None`` (default) for 19 durations from 1 s to 6 h,
                ``"all"`` for the full grid (1 s steps to 3 min, then 5, 10, 30 and 60 s
                steps), or a list. Durations the activity did not last are left out.
            output: ``"pandas"``, ``"polars"``, ``"arrow"`` or ``"bytes"``. Defaults to the
                installed frame library, Polars if both are.

        Returns:
            A frame, one row per duration: ``duration``, the metric (W or m/s) and ``start``,
            the UTC time the best effort began. The curve can rise again at longer durations
            (intermittent efforts); it is returned as it is.

        Raises:
            SweatStackNotFoundError: If the activity does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            latest = client.activities.latest(sport="cycling")
            curve = client.activities.mean_max(latest.id, metric="power", durations=[5, 60, 300, 1200])
            ```
        """
        params = _with_durations({"metric": self._client._enums_to_strings([metric])[0]}, durations)
        response = self._client._request(
            "get", f"/api/v1/activities/{activity_id}/mean-max", params=params
        )
        return self._client._read_frame(response.content, output)

    @overload
    def awd(
        self,
        activity_id: str,
        *,
        metric: IntensityMetric | None = None,
        output: None = None,
    ) -> pd.DataFrame | pl.DataFrame: ...

    @overload
    def awd(
        self,
        activity_id: str,
        *,
        metric: IntensityMetric | None = None,
        output: Literal["pandas"],
    ) -> pd.DataFrame: ...

    @overload
    def awd(
        self,
        activity_id: str,
        *,
        metric: IntensityMetric | None = None,
        output: Literal["polars"],
    ) -> pl.DataFrame: ...

    @overload
    def awd(
        self,
        activity_id: str,
        *,
        metric: IntensityMetric | None = None,
        output: Literal["arrow"],
    ) -> pa.Table: ...

    @overload
    def awd(
        self,
        activity_id: str,
        *,
        metric: IntensityMetric | None = None,
        output: Literal["bytes"],
    ) -> bytes: ...

    def awd(
        self,
        activity_id: str,
        *,
        metric: IntensityMetric | None = None,
        output: FrameOutput | None = None,
    ) -> pd.DataFrame | pl.DataFrame | pa.Table | bytes:
        """Retrieves an activity's accumulated work duration (AWD) curve.

        Endpoint: ``GET /api/v1/activities/{activity_id}/accumulated-work-duration``

        AWD is how long the activity spent at or above each intensity: the activity's
        samples sorted by intensity.

        Args:
            activity_id: The activity's ID.
            metric: ``"power"`` or ``"speed"``. Defaults to power for cycling, speed otherwise.
            output: ``"pandas"``, ``"polars"``, ``"arrow"`` or ``"bytes"``. Defaults to the
                installed frame library, Polars if both are.

        Returns:
            A frame with the metric value and ``duration`` as columns.

        Raises:
            SweatStackNotFoundError: If the activity does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            latest = client.activities.latest(sport="cycling")
            awd = client.activities.awd(latest.id, metric="power")
            ```
        """
        params = {"metric": self._client._enums_to_strings([metric])[0]} if metric else {}
        response = self._client._request(
            "get", f"/api/v1/activities/{activity_id}/accumulated-work-duration", params=params
        )
        return self._client._read_frame(response.content, output)

    def upload(
        self,
        files: str | Path | Sequence[str | Path],
    ) -> builtins.list[SourceResponse]:
        """Uploads activity files (FIT or CSV); they are processed in the background.

        Endpoint: ``POST /api/v1/activities/upload``

        FIT files carry their sport. CSV files need a ``sport`` column with an Open Sport
        Taxonomy code (``cycling.road``) and a ``timestamp`` column with offset-aware ISO 8601
        datetimes (``...+02:00`` or ``...Z``); naive timestamps are rejected during processing.

        Args:
            files: One path or a list of paths.

        Returns:
            list[SourceResponse]: One entry per file. ``status`` starts as ``"processing"``;
            retrieve the activities by ID once processed.

        Raises:
            FileNotFoundError: If a file does not exist.
            SweatStackBadRequestError: If the server rejects the upload.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            sources = client.activities.upload(["ride.fit", "run.fit"])
            print([source.status for source in sources])
            ```
        """
        paths = [Path(files)] if isinstance(files, (str, Path)) else [Path(f) for f in files]
        opened = []
        try:
            multipart = []
            for path in paths:
                handle = path.open("rb")
                opened.append(handle)
                multipart.append(("files", (path.name, handle)))
            response = self._client._request("post", "/api/v1/activities/upload", files=multipart)
        finally:
            for handle in opened:
                handle.close()
        return [SourceResponse.model_validate(s) for s in response.json()["sources"]]

    def watch_backfill_status(
        self, *, auto_reconnect: bool = False
    ) -> Generator[BackfillStatus, None, None]:
        """Streams how far the activity backfill of a newly connected user has reached.

        Endpoint: ``GET /api/v1/activities/backfill-status``

        Yields an update every few seconds. The server closes the stream after 60 seconds;
        with ``auto_reconnect=True`` the generator reconnects and keeps yielding until you
        stop iterating.

        Args:
            auto_reconnect: Reconnect after the server closes the stream or the connection
                drops.

        Yields:
            BackfillStatus: ``backfill_loaded_until``, the earliest date loaded so far.

        Raises:
            SweatStackAPIError: If the API request fails.
            SweatStackConnectionError: If the connection fails and ``auto_reconnect`` is off.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            for status in client.activities.watch_backfill_status():
                print(status.backfill_loaded_until)
            ```
        """
        while True:
            try:
                with self._client._http_client() as http:
                    with http.stream("GET", "/api/v1/activities/backfill-status") as response:
                        self._client._raise_for_status(response)
                        for line in response.iter_lines():
                            if not line.strip():
                                continue
                            try:
                                status = BackfillStatus.model_validate_json(line)
                            except ValueError as error:
                                # Skip it, but visibly: a silent skip once hid every update.
                                logger.warning("Skipping a backfill status line: %s", error)
                                continue
                            yield status
            except SweatStackConnectionError:
                if not auto_reconnect:
                    raise
                time.sleep(1)
            if not auto_reconnect:
                return

    def backfill_status(self) -> BackfillStatus:
        """Retrieves how far the activity backfill has reached: the first update of the stream.

        Endpoint: ``GET /api/v1/activities/backfill-status``

        Returns:
            BackfillStatus: ``backfill_loaded_until``, the earliest date loaded so far.

        Raises:
            ValueError: If the stream ends without an update.
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            print(client.activities.backfill_status().backfill_loaded_until)
            ```
        """
        for status in self.watch_backfill_status():
            return status
        raise ValueError("The backfill status stream ended without an update")


class Longitudinal(Resource):
    """Data and analyses across many activities: ``/api/v1/activities/longitudinal-*``."""

    @overload
    def data(
        self,
        *,
        sport: SportParam,
        start: date,
        end: date | None = None,
        metrics: MetricParam | None = None,
        segmentation_on: IntensityMetric | None = None,
        output: None = None,
    ) -> pd.DataFrame | pl.DataFrame: ...

    @overload
    def data(
        self,
        *,
        sport: SportParam,
        start: date,
        end: date | None = None,
        metrics: MetricParam | None = None,
        segmentation_on: IntensityMetric | None = None,
        output: Literal["pandas"],
    ) -> pd.DataFrame: ...

    @overload
    def data(
        self,
        *,
        sport: SportParam,
        start: date,
        end: date | None = None,
        metrics: MetricParam | None = None,
        segmentation_on: IntensityMetric | None = None,
        output: Literal["polars"],
    ) -> pl.DataFrame: ...

    @overload
    def data(
        self,
        *,
        sport: SportParam,
        start: date,
        end: date | None = None,
        metrics: MetricParam | None = None,
        segmentation_on: IntensityMetric | None = None,
        output: Literal["arrow"],
    ) -> pa.Table: ...

    @overload
    def data(
        self,
        *,
        sport: SportParam,
        start: date,
        end: date | None = None,
        metrics: MetricParam | None = None,
        segmentation_on: IntensityMetric | None = None,
        output: Literal["bytes"],
    ) -> bytes: ...

    def data(
        self,
        *,
        sport: SportParam,
        start: date,
        end: date | None = None,
        metrics: MetricParam | None = None,
        segmentation_on: IntensityMetric | None = None,
        output: FrameOutput | None = None,
    ) -> pd.DataFrame | pl.DataFrame | pa.Table | bytes:
        """Retrieves the time series of every matching activity in a date range, concatenated.

        Endpoint: ``GET /api/v1/activities/longitudinal-data``

        Responses are cached on disk when :func:`sweatstack.enable_cache` is on.

        Args:
            sport: One sport or a list. Required by the API.
            start: First date of the range.
            end: Last date of the range. Defaults to today.
            metrics: One metric or a list. Defaults to ``duration``, ``power``,
                ``heart_rate`` and ``speed``.
            segmentation_on: Downsample with AISC, keyed on ``"power"`` or ``"speed"``.
            output: ``"pandas"``, ``"polars"``, ``"arrow"`` or ``"bytes"``. Defaults to the
                installed frame library, Polars if both are.

        Returns:
            A frame, one row per sample, with ``timestamp`` (UTC), ``timestamp_local``,
            ``activity_id`` and ``sport`` columns plus one column per metric.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from datetime import date

            from sweatstack import Client

            client = Client()
            season = client.activities.longitudinal.data(
                sport="cycling", start=date(2026, 1, 1), metrics=["power"], output="polars"
            )
            ```
        """
        params: dict = {"sport": self._wire(sport), "start": start}
        if end is not None:
            params["end"] = end
        if metrics is not None:
            params["metrics"] = self._wire(metrics)
        if segmentation_on is not None:
            params["segmentation_on"] = self._client._enums_to_strings([segmentation_on])[0]
        return self._cached_frame(
            "longitudinal_data", "/api/v1/activities/longitudinal-data", params, output
        )

    @overload
    def mean_max(
        self,
        *,
        sport: SportParam,
        metric: IntensityMetric,
        start: date | None = None,
        end: date | None = None,
        after: float | Sequence[float] | None = None,
        durations: Sequence[int] | Literal["all"] | None = None,
        output: None = None,
    ) -> pd.DataFrame | pl.DataFrame: ...

    @overload
    def mean_max(
        self,
        *,
        sport: SportParam,
        metric: IntensityMetric,
        start: date | None = None,
        end: date | None = None,
        after: float | Sequence[float] | None = None,
        durations: Sequence[int] | Literal["all"] | None = None,
        output: Literal["pandas"],
    ) -> pd.DataFrame: ...

    @overload
    def mean_max(
        self,
        *,
        sport: SportParam,
        metric: IntensityMetric,
        start: date | None = None,
        end: date | None = None,
        after: float | Sequence[float] | None = None,
        durations: Sequence[int] | Literal["all"] | None = None,
        output: Literal["polars"],
    ) -> pl.DataFrame: ...

    @overload
    def mean_max(
        self,
        *,
        sport: SportParam,
        metric: IntensityMetric,
        start: date | None = None,
        end: date | None = None,
        after: float | Sequence[float] | None = None,
        durations: Sequence[int] | Literal["all"] | None = None,
        output: Literal["arrow"],
    ) -> pa.Table: ...

    @overload
    def mean_max(
        self,
        *,
        sport: SportParam,
        metric: IntensityMetric,
        start: date | None = None,
        end: date | None = None,
        after: float | Sequence[float] | None = None,
        durations: Sequence[int] | Literal["all"] | None = None,
        output: Literal["bytes"],
    ) -> bytes: ...

    def mean_max(
        self,
        *,
        sport: SportParam,
        metric: IntensityMetric,
        start: date | None = None,
        end: date | None = None,
        after: float | Sequence[float] | None = None,
        durations: Sequence[int] | Literal["all"] | None = None,
        output: FrameOutput | None = None,
    ) -> pd.DataFrame | pl.DataFrame | pa.Table | bytes:
        """Retrieves the mean-max curve across every matching activity in a date range.

        Endpoint: ``GET /api/v1/activities/longitudinal-mean-max``

        Responses are cached on disk when :func:`sweatstack.enable_cache` is on.

        Args:
            sport: One sport or a list.
            metric: ``"power"`` or ``"speed"``.
            start: First date of the range.
            end: Last date of the range. Defaults to today.
            after: One or more fatigue states (at most 5). For each, the curve is computed over
                the part of every activity after that much accumulated work (kJ, for power) or
                distance (m, for speed; experimental), then enveloped across activities. The
                frame gains an ``after`` column. The date range is capped at one year.
            durations: In seconds. ``None`` (default) for 19 durations from 1 s to 6 h,
                ``"all"`` for the full grid, or a list.
            output: ``"pandas"``, ``"polars"``, ``"arrow"`` or ``"bytes"``. Defaults to the
                installed frame library, Polars if both are.

        Returns:
            A frame, one row per duration (and per ``after`` value): ``duration``, the metric,
            ``start`` (UTC), and the ``activity_id`` and ``sport`` that set it.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from datetime import date

            from sweatstack import Client

            client = Client()
            curve = client.activities.longitudinal.mean_max(
                sport="cycling", metric="power", start=date(2026, 1, 1), after=[0, 1000]
            )
            ```
        """
        params = _with_durations(
            {
                "sport": self._wire(sport),
                "metric": self._client._enums_to_strings([metric])[0],
            },
            durations,
        )
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        if after is not None:
            params["after"] = [after] if isinstance(after, (int, float)) else list(after)
        return self._cached_frame(
            "mean_max", "/api/v1/activities/longitudinal-mean-max", params, output
        )

    @overload
    def awd(
        self,
        *,
        sport: SportParam,
        metric: IntensityMetric,
        start: date | None = None,
        end: date | None = None,
        output: None = None,
    ) -> pd.DataFrame | pl.DataFrame: ...

    @overload
    def awd(
        self,
        *,
        sport: SportParam,
        metric: IntensityMetric,
        start: date | None = None,
        end: date | None = None,
        output: Literal["pandas"],
    ) -> pd.DataFrame: ...

    @overload
    def awd(
        self,
        *,
        sport: SportParam,
        metric: IntensityMetric,
        start: date | None = None,
        end: date | None = None,
        output: Literal["polars"],
    ) -> pl.DataFrame: ...

    @overload
    def awd(
        self,
        *,
        sport: SportParam,
        metric: IntensityMetric,
        start: date | None = None,
        end: date | None = None,
        output: Literal["arrow"],
    ) -> pa.Table: ...

    @overload
    def awd(
        self,
        *,
        sport: SportParam,
        metric: IntensityMetric,
        start: date | None = None,
        end: date | None = None,
        output: Literal["bytes"],
    ) -> bytes: ...

    def awd(
        self,
        *,
        sport: SportParam,
        metric: IntensityMetric,
        start: date | None = None,
        end: date | None = None,
        output: FrameOutput | None = None,
    ) -> pd.DataFrame | pl.DataFrame | pa.Table | bytes:
        """Retrieves accumulated work duration (AWD) across a date range, at four intensities.

        Endpoint: ``GET /api/v1/activities/longitudinal-accumulated-work-duration``

        **Beta**: the server marks this endpoint as in development.

        Args:
            sport: One sport or a list.
            metric: ``"power"`` or ``"speed"``.
            start: First date of the range.
            end: Last date of the range. Defaults to today.
            output: ``"pandas"``, ``"polars"``, ``"arrow"`` or ``"bytes"``. Defaults to the
                installed frame library, Polars if both are.

        Returns:
            A frame with the AWD at the max (highest daily), hard, medium and easy levels.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from datetime import date

            from sweatstack import Client

            client = Client()
            awd = client.activities.longitudinal.awd(
                sport="cycling", metric="power", start=date(2026, 1, 1)
            )
            ```
        """
        params: dict = {
            "sport": self._wire(sport),
            "metric": self._client._enums_to_strings([metric])[0],
        }
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        response = self._client._request(
            "get", "/api/v1/activities/longitudinal-accumulated-work-duration", params=params
        )
        return self._client._read_frame(response.content, output)

    def _cached_frame(self, namespace: str, path: str, params: dict, output: str | None):
        """GET a parquet endpoint through the local cache, when it is enabled."""
        client = self._client
        if not client._cache_enabled():
            return client._read_frame(client._request("get", path, params=params).content, output)
        key = client._generate_cache_key(namespace, **params)
        content = client._read_cache(namespace, key)
        if content is None:
            content = client._request("get", path, params=params).content
            client._write_cache(namespace, key, content)
        return client._read_frame(content, output)
