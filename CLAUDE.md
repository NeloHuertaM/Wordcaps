# Repository instructions for Claude

## Repository profile

- **What:** WordCaps, word-by-word animated captions for DaVinci Resolve. A local Python app (standard library only) with a browser UI, a Lua bridge that runs inside Resolve, and whisper.cpp for transcription. See [README.md](README.md).
- **Layout:** `wordcaps/` Python package and `wordcaps/web/` UI; `resolve/` the Lua launcher template and core; `tests/` Python tests, `tests/lua/` Lua tests and the mock Resolve.
- **Python:** 3.9 or later. No third-party packages, at runtime or in tests.
- **Test:** `python -m unittest discover -s tests -t .` from the repository root. `tests/test_bridge_lua_e2e.py` needs Docker and is skipped without it. Lua core alone: `docker run --rm -v "$PWD:/src:ro" alpine:3.20 sh -c "apk add --no-cache luajit >/dev/null && luajit /src/tests/lua/test_core.lua"`.
- **Style enforcement:** none configured. `node --check wordcaps/web/app.js` catches UI syntax errors.
- **HTTP API:** the server in `wordcaps/server.py` binds to 127.0.0.1 and its only consumer is `wordcaps/web/app.js`, served by the same process with a per-session token. It is a private UI backend, not a published API, so the `http-api-design` standards (resource naming, versioning, RFC 7807) do not apply. Errors are JSON `{"error": "<Spanish message>"}`.
- **User-facing text:** Spanish, in the UI, the Lua bridge errors and the README. Code identifiers in English.

## Rules specific to this repository

- The Lua core runs in Resolve 21.1's sandboxed scripting state: no `io`, `ffi`, `require`, `package` or `os.execute`. Files are read only with `loadfile` and `bmd.fileexists`, and replies leave only through `fusion:SetPrefs` plus `SavePrefs`. Anything that needs a file or a process belongs on the Python side.
- The request/response contract between `wordcaps/bridge.py` and `resolve/wordcaps_core.lua` is covered end to end by `tests/test_bridge_lua_e2e.py`. A change to either side runs that test.
- Nothing here has been run against a real DaVinci Resolve yet. The README's *Estado* section lists what needs checking there.
