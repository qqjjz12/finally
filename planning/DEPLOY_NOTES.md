# Deploy Notes (DevOps -> API/Frontend engineers)

Assumptions the Dockerfile makes:
- Backend: `/app` is the contents of `backend/`; entry `app.main:app`, uvicorn on 0.0.0.0:8000.
- `uv sync --frozen --no-dev`: runtime deps must be in `[project].dependencies` (not the `dev` extra) and `backend/uv.lock` must be current. `backend/README.md` must exist (pyproject `readme`).
- Static frontend: `frontend/` must build with `npm run build` into `frontend/out/` (`output: 'export'`); copied to `/app/static`. API app should serve `static/` (relative to app root, i.e. `<backend>/static`) with `html=True`, mounted AFTER `/api` routes.
- DB path: env `FINALLY_DB_PATH=/app/db/finally.db` (volume `finally-data` -> `/app/db`). Locally default should be `<repo>/db/finally.db`.
- `.env` is passed via `--env-file`; backend does not read it. `.dockerignore` excludes `test/`, `planning/`, `.env`.
- Frontend: a `package-lock.json` is recommended (`npm ci`); Dockerfile falls back to `npm install`.
- Scripts: `scripts/start_mac.sh [--build] [--open]`, `scripts/start_windows.ps1 [-Build] [-Open]`; container and image name `finally`.
