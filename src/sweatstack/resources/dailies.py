"""``client.dailies``: ``/api/v1/dailies/{measure}``."""

from __future__ import annotations

import builtins
from datetime import date
from typing import TYPE_CHECKING, Literal, overload

from .._frames import ListOutput
from ..schemas import DailyMeasure, DailyResponse
from ._base import Resource

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa


class Dailies(Resource):
    """Dailies: one value per measure per day (body mass, resting heart rate, HRV, sleep, ...)."""

    @overload
    def list(
        self,
        measure: DailyMeasure | str,
        *,
        start: date,
        end: date,
        interpolate: bool = True,
        output: Literal["models"] | None = None,
    ) -> builtins.list[DailyResponse]: ...

    @overload
    def list(
        self,
        measure: DailyMeasure | str,
        *,
        start: date,
        end: date,
        interpolate: bool = True,
        output: Literal["pandas"],
    ) -> pd.DataFrame: ...

    @overload
    def list(
        self,
        measure: DailyMeasure | str,
        *,
        start: date,
        end: date,
        interpolate: bool = True,
        output: Literal["polars"],
    ) -> pl.DataFrame: ...

    @overload
    def list(
        self,
        measure: DailyMeasure | str,
        *,
        start: date,
        end: date,
        interpolate: bool = True,
        output: Literal["arrow"],
    ) -> pa.Table: ...

    def list(
        self,
        measure: DailyMeasure | str,
        *,
        start: date,
        end: date,
        interpolate: bool = True,
        output: ListOutput | None = None,
    ) -> builtins.list[DailyResponse] | pd.DataFrame | pl.DataFrame | pa.Table:
        """Lists one value per day for a measure, every day in the range included.

        Endpoint: ``GET /api/v1/dailies/{measure}``

        Args:
            measure: The measure, e.g. ``"body_mass"`` or ``DailyMeasure.hrv``.
            start: First date (inclusive).
            end: Last date (inclusive).
            interpolate: Fill gaps with the server's estimate for the measure. Note that the
                API's own default is ``false``; the SDK defaults to ``True``. With ``False``, a
                missing day has ``value=None`` and ``source="missing"``.
            output: ``"models"`` (default), ``"pandas"``, ``"polars"`` or ``"arrow"``.

        Returns:
            DailyResponse objects, or a frame with one row per date (``date`` is a column).

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from datetime import date

            from sweatstack import Client

            client = Client()
            hrv = client.dailies.list("hrv", start=date(2026, 4, 1), end=date(2026, 5, 1), output="pandas")
            ```
        """
        response = self._client._request(
            "get",
            f"/api/v1/dailies/{_measure(measure)}",
            params={"start": start.isoformat(), "end": end.isoformat(), "interpolate": interpolate},
        )
        dailies = [DailyResponse.model_validate(item) for item in response.json()]
        return self._client._frame_from_models(dailies, DailyResponse, output)

    def set(self, measure: DailyMeasure | str, *, date: date, value: float) -> DailyResponse:
        """Sets the value of a measure for a day, creating or replacing it.

        Endpoint: ``POST /api/v1/dailies/{measure}``

        A value you set is never overwritten by an integration import.

        Args:
            measure: The measure, e.g. ``"body_mass"``.
            date: The day.
            value: The value, in the measure's unit.

        Returns:
            DailyResponse: The stored value.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from datetime import date

            from sweatstack import Client

            client = Client()
            client.dailies.set("body_mass", date=date(2026, 5, 1), value=71.4)
            ```
        """
        response = self._client._request(
            "post",
            f"/api/v1/dailies/{_measure(measure)}",
            json={"date": date.isoformat(), "value": value},
        )
        return DailyResponse.model_validate(response.json())

    def delete(self, measure: DailyMeasure | str, *, date: date) -> None:
        """Deletes the value of a measure for a day.

        Endpoint: ``DELETE /api/v1/dailies/{measure}``

        Args:
            measure: The measure, e.g. ``"body_mass"``.
            date: The day.

        Raises:
            SweatStackNotFoundError: If there is no value for that day.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from datetime import date

            from sweatstack import Client

            client = Client()
            client.dailies.delete("body_mass", date=date(2026, 5, 1))
            ```
        """
        self._client._request(
            "delete", f"/api/v1/dailies/{_measure(measure)}", params={"date": date.isoformat()}
        )


def _measure(measure: DailyMeasure | str) -> str:
    return measure.value if isinstance(measure, DailyMeasure) else measure
