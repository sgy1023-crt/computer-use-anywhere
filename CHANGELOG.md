# Changelog

## [2.0.0] - 2026-02-18
### Major Changes
- **Universal Compatibility Mode**: Switched from Anthropic Beta Tools (`computer_20250124`) to **Standard Function Tools** (OpenAI-compatible) to fix OpenRouter compatibility issues.
- **Model Standard**: Locked to `anthropic/claude-sonnet-4.6` for best performance.

### Added
- **OpenRouter Support**: Now works out-of-the-box with OpenRouter API.
- **JPEG Optimization**: Screenshots are now compressed as JPEG (quality 60), ~50KB per frame.
- **High-DPI Support**: Added `ctypes` calls to fix coordinate mapping on high-res screens.
- **Retry Logic**: Added 3 automatic retries for API timeout/errors.
- **Smart Context**: Initial screenshot is now sent with the first prompt.

### Fixed
- Fixed `400 Invalid Request` errors caused by beta header stripping.
- Fixed `200 OK` but "I cannot take screenshots" errors caused by OpenAI endpoint ignoring beta tools.
- Fixed slow response times due to large PNG payloads.

### Removed
- Removed dependency on `anthropic` SDK (now uses raw `httpx`).
- Removed support for `xiaojingai.com` (replaced by OpenRouter).

