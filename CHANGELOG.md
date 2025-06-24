# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


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