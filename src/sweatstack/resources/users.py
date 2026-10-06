"""``client.users``: ``/api/v1/users/...``."""

from __future__ import annotations

import builtins
from collections.abc import Iterable

from ..schemas import UserResponse, UserSummary
from ._base import Resource


class Users(Resource):
    """The users you can access: yourself, managed users you created, and people who shared.

    A *managed user* is an account you created (``create``); it has no login of its own and
    you manage its data. A *shared user* has their own account and granted you access, for
    example an athlete you coach. ``list`` covers everyone; ``retrieve``, ``update`` and
    ``delete`` work on managed users only, as on the server.
    """

    def list(
        self,
        *,
        include_managed: bool = True,
        include_shared: bool = True,
        name: str | None = None,
    ) -> builtins.list[UserSummary]:
        """Lists the users you can access, yourself included.

        Endpoint: ``GET /api/v1/users/``

        Always runs as the signed-in (principal) user, also on a delegated client, because the
        endpoint does not accept delegated tokens.

        Args:
            include_managed: Include managed users.
            include_shared: Include users who shared access with you.
            name: Only users whose display name contains this, ignoring case. Returns every
                match, so check the length before picking one.

        Returns:
            list[UserSummary]: The users, each with the ``scopes`` you hold for them.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            matches = client.users.list(name="carla")
            if len(matches) != 1:
                raise ValueError(f"Expected one user matching 'carla', found {len(matches)}")
            athlete = client.delegated_client(matches[0])
            ```
        """
        params: dict = {}
        if not include_managed:
            params["include_managed"] = False
        if not include_shared:
            params["include_shared"] = False
        if name is not None:
            params["name"] = name
        principal = self._client.principal_client()
        response = principal._request("get", "/api/v1/users/", params=params)
        return filter_by_name((UserSummary.model_validate(u) for u in response.json()), name)

    def create(self, *, first_name: str, last_name: str | None = None) -> UserResponse:
        """Creates a managed user: an account without a login, managed by you.

        Endpoint: ``POST /api/v1/users/``

        Args:
            first_name: First name.
            last_name: Last name.

        Returns:
            UserResponse: The new user. Act as them with ``client.delegated_client(user.id)``.

        Raises:
            SweatStackAuthError: If you may not create managed users.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            junior = client.users.create(first_name="Bob", last_name="Smit")
            junior_client = client.delegated_client(junior.id)
            ```
        """
        response = self._client._request(
            "post", "/api/v1/users/", json={"first_name": first_name, "last_name": last_name}
        )
        return UserResponse.model_validate(response.json())

    def retrieve(self, user_id: str) -> UserResponse:
        """Retrieves a managed user.

        Endpoint: ``GET /api/v1/users/{user_id}``

        Only users you manage. For anyone else, yourself included, use :meth:`list`.

        Args:
            user_id: The managed user's ID.

        Returns:
            UserResponse: The user.

        Raises:
            SweatStackNotFoundError: If the user does not exist or is not managed by you.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            print(client.users.retrieve("usr_bob").display_name)
            ```
        """
        response = self._client._request("get", f"/api/v1/users/{user_id}")
        return UserResponse.model_validate(response.json())

    def update(
        self,
        user_id: str,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> UserResponse:
        """Updates a managed user's name. Fields you leave out are unchanged.

        Endpoint: ``PUT /api/v1/users/{user_id}``

        Args:
            user_id: The managed user's ID.
            first_name: The new first name.
            last_name: The new last name.

        Returns:
            UserResponse: The updated user.

        Raises:
            SweatStackNotFoundError: If the user does not exist or is not managed by you.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            client.users.update("usr_bob", last_name="de Vries")
            ```
        """
        fields = {"first_name": first_name, "last_name": last_name}
        response = self._client._request(
            "put",
            f"/api/v1/users/{user_id}",
            data={key: value for key, value in fields.items() if value is not None},
        )
        return UserResponse.model_validate(response.json())

    def delete(self, user_id: str) -> None:
        """Deletes a managed user **and all their data**. This cannot be undone.

        Endpoint: ``DELETE /api/v1/users/{user_id}``

        Args:
            user_id: The managed user's ID.

        Raises:
            SweatStackNotFoundError: If the user does not exist or is not managed by you.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            client.users.delete("usr_bob")
            ```
        """
        self._client._request("delete", f"/api/v1/users/{user_id}")


def filter_by_name(users: Iterable[UserSummary], name: str | None) -> builtins.list[UserSummary]:
    """Users whose display name contains ``name``, ignoring case; every user when ``None``.

    The SDK filters even though it also sends ``name`` to the server: the server may not
    support the filter yet, and filtering an already-filtered list changes nothing. The
    server's filter has to mean exactly this.
    """
    if name is None:
        return list(users)
    needle = name.casefold()
    return [user for user in users if needle in user.display_name.casefold()]
