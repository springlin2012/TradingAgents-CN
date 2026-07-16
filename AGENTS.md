# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python 3.10+ TradingAgents-CN application with a FastAPI backend, Vue frontend, and multi-agent analysis core. Main Python package code lives in `tradingagents/`; the FastAPI app, routers, services, workers, middleware, and models live in `app/`. The modern SPA is in `frontend/src/`, while `web/` contains the legacy or auxiliary Streamlit-style interface. CLI helpers are in `cli/`. Tests and diagnostic scripts are under `tests/`. Documentation, deployment assets, and static resources are in `docs/`, `docker/`, `nginx/`, `assets/`, and `images/`.

## Build, Test, and Development Commands

- `pip install -r requirements.txt`: install Python runtime dependencies.
- `python main.py`: run the main CLI/package entrypoint.
- `python web/run_web.py`: run the auxiliary web interface.
- `python -m pytest tests/`: run the default pytest suite; `tests/pytest.ini` skips integration-marked and selected long-running tests by default.
- `cd frontend && npm install && npm run dev`: install and start the Vue/Vite dev server.
- `cd frontend && npm run type-check && npm run lint && npm run build`: validate and build the frontend.
- `docker compose up --build`: start the containerized stack locally.

## Coding Style & Naming Conventions

Follow PEP 8 for Python. Use `snake_case` for modules, functions, and variables; use `PascalCase` for classes. Keep comments and docstrings concise and focused on non-obvious behavior. Frontend code uses Vue single-file components, TypeScript, Element Plus, ESLint, and Prettier. Run the frontend lint and type-check scripts before UI changes are submitted.

## Testing Guidelines

Use pytest for Python tests. Name normal tests `test_*.py`; reserve `debug_*.py` or `diagnose_*.py` for manual troubleshooting utilities. Add focused tests for new business logic, data-source behavior, or bug fixes. Integration tests may require API keys and should be marked or isolated so the default suite remains practical.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit-style prefixes such as `feat:`, `fix:`, `refactor:`, and `chore:`, sometimes with Chinese summaries. Keep commits scoped to one logical change. Pull requests should describe the change, list verification commands, link related issues, and include screenshots or screen recordings for UI changes.

## Security & Configuration Tips

Never commit secrets. Copy `.env.example` to `.env` for local keys and service settings. Check configuration precedence carefully: model settings, provider settings, environment variables, MongoDB, Redis, and external market-data APIs can all affect runtime behavior.


## ⚠ 强制规则：规则文件更新与重新加载

- `AGENTS.md`、`CLAUDE.md`、等协作规则文件发生更新后，AI 必须自动重新读取对应规则文件，不依赖用户再次提示。
- AI 不应假设自己能自动感知外部文件更新；为避免沿用旧上下文，每次进入新的仓库分析、文档沉淀、代码修改、测试生成或配置调整任务前，必须重新读取 `AGENTS.md` 和 `CLAUDE.md`。
- 若 AI 本轮修改了 `AGENTS.md` 或 `CLAUDE.md`，修改完成后必须立即重新读取 `AGENTS.md` 和 `CLAUDE.md`，再继续执行后续任务或总结。

## ⚠ 强制规则
- 我是中文用户，在生成文档内容及文档命名时请使用中文，请勿使用英文。

