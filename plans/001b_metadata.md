# Plan: Add App Metadata to Python Client

## Summary

Add methods for managing per-app JSON metadata on activities, traces, tests, and users. These endpoints require an app token (a token with an `aud` claim) and allow apps to store arbitrary JSON data scoped to their application.

## Code Quality Requirements

All code must be extremely clean, robust and maintainable:
- Follow existing patterns and conventions exactly
- Consistent naming across the four entity types
- DRY implementation via shared private helpers
- Comprehensive type hints and docstrings

## Prerequisites

- Schema generation (`uv run generate-response-models`) must have been run (see 001a step 1). The `app_metadata` field appears on entity response schemas.
- Plan 001a (Tests) should be completed first since test metadata endpoints reference the tests resource.

## Step 1: Add private helpers to `client.py`

All eight public methods do the same thing with different paths. Extract two private helpers to keep the implementation DRY:

```python
def _set_app_metadata(self, path: str, data: dict) -> None:
    """PUT arbitrary JSON dict to an app-metadata endpoint."""
    with self._http_client() as client:
        response = client.put(url=path, json=data)
        self._raise_for_status(response)

def _delete_app_metadata(self, path: str) -> None:
    """DELETE an app-metadata endpoint."""
    with self._http_client() as client:
        response = client.delete(url=path)
        self._raise_for_status(response)
```

## Step 2: Add public App Metadata methods to `client.py`

Eight methods, four entity types x two operations (set/delete). Each is a thin wrapper over the helpers.

Naming convention: `set_*_app_metadata` / `delete_*_app_metadata` - uses "set" since PUT has full-replace semantics (not a partial merge), and includes "app" to match the API path (`/app-metadata`) and the response field name (`app_metadata`).

```python
def set_activity_app_metadata(self, activity_id: str, *, data: dict) -> None:
    # PUT /api/v1/activities/{activity_id}/app-metadata
    self._set_app_metadata(f"/api/v1/activities/{activity_id}/app-metadata", data)

def delete_activity_app_metadata(self, activity_id: str) -> None:
    # DELETE /api/v1/activities/{activity_id}/app-metadata
    self._delete_app_metadata(f"/api/v1/activities/{activity_id}/app-metadata")

def set_trace_app_metadata(self, trace_id: str, *, data: dict) -> None:
def delete_trace_app_metadata(self, trace_id: str) -> None:

def set_test_app_metadata(self, test_id: str, *, data: dict) -> None:
def delete_test_app_metadata(self, test_id: str) -> None:

def set_user_app_metadata(self, *, data: dict) -> None:
    # PUT /api/v1/profile/app-metadata (no entity_id, operates on authenticated user)

def delete_user_app_metadata(self) -> None:
    # DELETE /api/v1/profile/app-metadata
```

**Implementation notes:**
- `data` is keyword-only (after `*`) to be explicit about what's being sent
- For entity methods, `entity_id` is positional (consistent with `get_activity(activity_id)` etc.)
- All error handling delegated to `_raise_for_status`: 403 (no app token), 413 (over size limit), 422 (nesting too deep)
- Each method gets a proper docstring despite being thin - the user-facing API should be self-documenting

## Step 3: Register singleton methods

Add all eight to `_generate_singleton_methods()`:
```python
"set_activity_app_metadata",
"delete_activity_app_metadata",
"set_trace_app_metadata",
"delete_trace_app_metadata",
"set_test_app_metadata",
"delete_test_app_metadata",
"set_user_app_metadata",
"delete_user_app_metadata",
```

## Step 4: Tests (pytest)

Add `tests/test_metadata.py`. Lightweight - the methods are thin wrappers, so there's not much pure logic to test.

Focus on:
- **Path construction**: Verify the correct API path is built for each entity type. Can test by checking the URL passed to the helper (or by testing the helpers directly with a mock/spy on `_http_client`).

Don't over-test: these are simple PUT/DELETE wrappers. If the paths are correct and `_raise_for_status` is called, the methods are correct.

## Step 5: Update skill docs

Update `.claude/skills/sweatstack-python/client.md` with the new metadata methods.

## Step 6: Changelog

Add entries to the `[Unreleased]` section of `CHANGELOG.md`.

## API Reference

| Method | Path | Body | Size Limit | Response |
|--------|------|------|------------|----------|
| PUT | `/api/v1/activities/{id}/app-metadata` | JSON dict | 1KB | `{"message": "..."}` |
| DELETE | `/api/v1/activities/{id}/app-metadata` | - | - | 204 |
| PUT | `/api/v1/traces/{id}/app-metadata` | JSON dict | 1KB | `{"message": "..."}` |
| DELETE | `/api/v1/traces/{id}/app-metadata` | - | - | 204 |
| PUT | `/api/v1/tests/{id}/app-metadata` | JSON dict | 1KB | `{"message": "..."}` |
| DELETE | `/api/v1/tests/{id}/app-metadata` | - | - | 204 |
| PUT | `/api/v1/profile/app-metadata` | JSON dict | 4KB | `{"message": "..."}` |
| DELETE | `/api/v1/profile/app-metadata` | - | - | 204 |

### Key Behaviors
- All require app token (token with `aud` claim) - 403 otherwise
- PUT replaces the entire metadata dict (no partial merge)
- Each app's metadata is isolated (apps can't see each other's metadata)
- `app_metadata` field appears on entity responses only when accessed via app token
- Metadata cascades on entity or app deletion
