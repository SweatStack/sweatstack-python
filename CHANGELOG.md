# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [0.51.0] - 2025-08-28

### Added

- Added a new `show_logout` parameter to the `ss.StreamlitAuth.authenticate()` method that allows for disabling the logout button. The logout button can be shown by calling `ss.StreamlitAuth.logout_button()`. This is for example useful when you want to show the login button on the main page, but the logout button in the sidebar.


## [0.50.0] - 2025-08-25

### Added

- Added a new `offset` parameter to the `ss.get_activities()`, `ss.get_activity_data()`, `ss.get_latest_activity_data()`, `ss.get_traces()`, and `ss.get_trace_data()` methods that allows for pagination of the results.


## [0.49.0] - 2025-08-18

### Added

- Added a new `metrics` parameter to the `ss.get_activity_data()` and `ss.get_latest_activity_data()` methods that allows for filtering the data by specific metrics.


## [0.48.0] - 2025-08-12

### Added

- Added optional local caching of longitudinal data, enabled by setting the `SWEATSTACK_CACHE_ENABLED` environment variable to `true`. The cache directory can be specified by setting the `SWEATSTACK_CACHE_DIR` environment variable. The cache can be cleared by calling `ss.clear_cache()`.


## [0.47.0] - 2025-08-07

### Added

- Added a new `ss.get_backfill_status()` method that returns the current backfill status from the activities backfill-status endpoint.
- Added a new `ss.watch_backfill_status()` method that watches the backfill status from the activities backfill-status endpoint.


## [0.46.0] - 2025-08-01

### Added

- Added a new `registered_at` field to the `UserInfoResponse` model that is returned by `ss.get_userinfo()`. This field is the timestamp of the user's registration with SweatStack.



## [0.45.0] - 2025-06-24

### Added

- Added a new `ss.whoami()` method that returns the authenticated user's summary information. This method is recommended over `ss.get_userinfo()` which only exists for OpenID compatibility and requires the `profile` scope.
- Added a new `ss.Metric.display_name()` method that returns a human-readable display name for a metric. For example, `ss.Metric.heart_rate.display_name()` returns "heart rate".

## [0.44.0] - 2025-06-18

### Added

- Added support for persistent storage of API keys and refresh tokens.
- Added a new `ss.authenticate()` method that handles authentication comprehensively, including calling `ss.login()` when needed. This method is now the recommended way to authenticate the client.


## Changed

- The `sweatlab` and `sweatshell` commands now use the new `ss.authenticate()` method.