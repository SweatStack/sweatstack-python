"""Shared machinery for the resource namespaces (``client.activities``, ``client.traces``, ...)."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypeVar

from open_sport_taxonomy import Sport
from pydantic import BaseModel

from ..schemas import Metric

if TYPE_CHECKING:
    from ..client import Client

ModelT = TypeVar("ModelT", bound=BaseModel)

SportParam: TypeAlias = Sport | str | Sequence[Sport | str]
"""One sport or several; a repeatable ``sport`` query parameter (R8)."""

MetricParam: TypeAlias = Metric | str | Sequence[Metric | str]
"""One metric or several; a repeatable ``metrics`` query parameter (R8)."""

TagParam: TypeAlias = str | Sequence[str]
"""One tag or several; a repeatable ``tags`` query parameter (R8)."""

IntensityMetric: TypeAlias = Literal[Metric.power, Metric.speed] | Literal["power", "speed"]
"""The metrics the mean-max, AWD and segmentation endpoints accept."""


class Resource:
    """A group of endpoints under one URL segment, bound to one client.

    Resources are created by the client (``client.activities``), never by user code.
    """

    def __init__(self, client: Client) -> None:
        self._client = client

    def _wire(self, value: Any) -> list[str] | None:
        """A repeatable query parameter on the wire: one value or a list in, a list of strings out."""
        if value is None:
            return None
        if isinstance(value, (str, Enum, Sport)) or not isinstance(value, Sequence):
            value = [value]
        return self._client._enums_to_strings(list(value))

    def _paginate(
        self,
        path: str,
        params: dict[str, Any],
        model: type[ModelT],
        *,
        page_size: int,
        limit: int,
        offset: int,
    ) -> Generator[ModelT, None, None]:
        """Yield up to ``limit`` items starting at ``offset``, fetching ``page_size`` at a time.

        ``limit`` is the number of items the caller gets, not the server's page size: list
        methods page through the endpoint until they have ``limit`` items or it runs out.
        """
        fetched = 0
        while fetched < limit:
            page_limit = min(page_size, limit - fetched)
            page = self._client._request(
                "get", path, params={**params, "limit": page_limit, "offset": offset + fetched}
            ).json()
            for item in page:
                yield model.model_validate(item)
            fetched += len(page)
            if len(page) < page_limit:
                return


def _with_durations(params: dict[str, Any], durations: Sequence[int] | str | None) -> dict:
    """Add the mean-max ``durations`` query value: omitted, ``"all"``, or comma-separated seconds."""
    if durations is None:
        return params
    if isinstance(durations, str):
        return {**params, "durations": durations}
    return {**params, "durations": ",".join(str(int(d)) for d in durations)}
