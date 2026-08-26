# Repository Guidelines

## Project Structure & Module Organization

`main.py` is the AstrBot plugin entry point and defines commands, lifecycle hooks, and dependency wiring. API integrations live in `bili_client.py` and `bgm_client.py`. Keep domain models, constants, persistence, and shared helpers in `core/`; place subscription polling, dispatch, and rendering logic in `services/`. AstrBot function tools belong in `tools/`. HTML card templates and bundled images are under `assets/`. The `dev/` package provides mock data and the local template preview server. User-facing configuration is described by `_conf_schema.json`, while plugin metadata is maintained in `metadata.yaml`.

## Build, Test, and Development Commands

Use Python 3.10 or newer (the codebase uses `X | None` type syntax).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python dev_ui.py
python -m compileall main.py core services tools dev
```

The preview command serves card templates at `http://localhost:8765` with mock scenarios. `compileall` is the current lightweight syntax check. Install or link this directory through an AstrBot development instance for end-to-end command, persistence, and notification testing.

## Coding Style & Naming Conventions

Follow PEP 8 with four-space indentation. Use `snake_case` for modules, functions, variables, and configuration keys; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants. Add type hints to new or changed interfaces and prefer focused async methods for network or AstrBot operations. Keep imports grouped as standard library, third-party, then local modules. No formatter or linter is pinned, so avoid unrelated formatting churn and match nearby code.

## Testing Guidelines

There is currently no committed automated test suite. For logic-heavy changes, add `pytest` tests under `tests/` using names such as `test_listener.py` and `test_live_transition()`. Mock Bilibili, Bangumi, and AstrBot APIs; tests must not require real credentials or send live messages. For template changes, exercise representative scenarios in `dev/mock_data.py` and visually check every template in `assets/`.

## Commit & Pull Request Guidelines

Recent history favors concise Conventional Commit-style subjects such as `fix(listener): ...`, `feat: ...`, and `chore: update to v1.6.4`. Keep each commit scoped to one behavior. Pull requests should explain the user-visible impact, testing performed, and configuration or migration effects; link relevant issues and include before/after screenshots for rendered-card changes. Update `README.md`, `CHANGELOG.md`, and `metadata.yaml` together when releasing or changing documented behavior.

## Security & Configuration

Never commit `sessdata`, Bangumi tokens, QR-login credentials, proxy secrets, or generated plugin data. Use a non-primary Bilibili account for development, and redact UIDs and session identifiers from logs and screenshots.
