# FastAPI API Docs – 10-Minute Setup (reusable)

## 1) Project skeleton (convention)

```
your_app/
  app/
    main.py                 # or main_application.py
    api/ | routers/         # APIRouter files
    schemas/                # Pydantic request/response models
    models/                 # DB/ORM models (optional)
  tools/
    docgen.py               # the generator script (copy from current project)
  .vscode/
    tasks.json              # VS Code tasks (below)
  SPECIFY.md                # spec-kit instructions (optional but nice)
```

> If your FastAPI instance isn’t `app.main:app`, just update the paths in `tasks.json` and `SPECIFY.md`.

- - -

## 2) Drop-in files (copy these forward)

### A) `tools/docgen.py`

Use the same `docgen.py` I generated for you. It:

* Pulls OpenAPI from `http://localhost:8000/openapi.json`

* Falls back to `import app.<entry>:app; app.openapi()`

* Falls back again to static route scan

* Emits:

  * `API_GUIDE.md`

  * `docs/openapi.snapshot.json`, `docs/postman_collection.json`

  * `docs/endpoints.csv`, `docs/examples/*`, `docs/schemas/*`, `docs/report.txt`

Only tweak you may need per project: **entry module** in the import list (e.g., `app.main_application`, `app.main`, etc.).

- - -

### B) `.vscode/tasks.json` (copy/paste)

```
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Start FastAPI (Uvicorn:8000)",
      "type": "shell",
      "command": "${config:python.defaultInterpreterPath}",
      "args": ["-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"],
      "isBackground": true,
      "problemMatcher": {
        "background": { "activeOnStart": true, "beginsPattern": ".", "endsPattern": "Application startup complete." },
        "pattern": [{ "regexp": "^(.*)$", "file": 1, "location": 1, "message": 1 }]
      }
    },
    {
      "label": "Docgen: live + validate",
      "type": "shell",
      "command": "${config:python.defaultInterpreterPath}",
      "args": ["tools/docgen.py", "--prefer", "live", "--validate", "sample"]
    },
    {
      "label": "Docgen: import (no server needed)",
      "type": "shell",
      "command": "${config:python.defaultInterpreterPath}",
      "args": ["tools/docgen.py", "--prefer", "import", "--validate", "none"]
    },
    {
      "label": "Docs: clean",
      "type": "shell",
      "command": "${config:python.defaultInterpreterPath}",
      "args": ["-c", "import os,shutil; shutil.rmtree('docs', ignore_errors=True); p='API_GUIDE.md'; os.remove(p) if os.path.exists(p) else None"]
    },
    {
      "label": "Generate Docs (Live, start server then docgen)",
      "dependsOn": ["Start FastAPI (Uvicorn:8000)", "Docgen: live + validate"],
      "dependsOrder": "sequence"
    }
  ]
}
```

> Change `app.main:app` above if your entry is different.

- - -

### C) (Optional) `SPECIFY.md` (one-pager for your agent)

```
Use tools/docgen.py to generate API_GUIDE.md and docs/*.
Preferred source: live OpenAPI at http://localhost:8000/openapi.json.

Fallback: import app.main:app then app.openapi().
Fallback: static router scan.

Emit curl/HTTPie/Python examples per endpoint and export schemas.
Validate safe GET endpoints. Do not hit destructive routes.
```

- - -

## 3) How you run it (three ways)

**A. One-click in VS Code**

* `Ctrl+Shift+B` → **Generate Docs (Live, start server then docgen)**

**B. Without VS Code**

```
# Option 1: live
uvicorn app.main:app --reload --port 8000
python tools/docgen.py --prefer live --validate sample

# Option 2: no server (imports app)
python tools/docgen.py --prefer import --validate none
```

**C. CI sanity check (copy into .github/workflows/docgen.yml)**

```
name: Docgen
on: [push]
jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: python tools/docgen.py --prefer import --validate none
```

- - -

## 4) “Every time I add or edit an endpoint” — mini-checklist

* **Annotate** request & response with Pydantic models:

  ```
  @router.post("/items", response_model=ItemOut)
  def create_item(payload: ItemIn) -> ItemOut:
      ...
  ```

* **No defaults for path params** (prevents OpenAPI break):

  ```
  def get_item(item_id: str = Path(...)):  # ✅ not Path(None)
  ```

* **Use `Query`, `Path`, `Header`** to expose types/defaults/constraints.

* **Attach tags, summary, description**:

  ```
  @router.get("/items/{item_id}", tags=["items"], summary="Get item by ID")
  ```

* **Auth in OpenAPI**: define security scheme (Bearer/OAuth) and apply it to routes/routers so docs show it.

* **Examples** (optional but nice):

  ```
  class ItemIn(BaseModel):
      name: str = Field(..., examples=["Sword"])
  ```

* Re-run **Generate Docs**. Check:

  * Endpoint appears with method & path

  * Request body example looks right

  * Responses show expected shape

  * `docs/examples/*` created for it

- - -

## 5) Common gotchas (fixes)

* **“Path parameters cannot have a default value”**\
  Use `Path(...)` or no default for path params.

* **Endpoint missing from docs**\
  Ensure it uses FastAPI decorators, and the app/routers are included in the main app.

* **Auth not showing**\
  Your security dependency must be tied to OpenAPI (e.g., add to `app` or router via `dependencies`), and define `securitySchemes` at `app = FastAPI(..., openapi_tags=[...])` time or via dependency.

- - -

## 6) What good output looks like

* `API_GUIDE.md` at repo root: human-readable, grouped by tags.

* `docs/`:

  * `openapi.snapshot.json`

  * `postman_collection.json`

  * `endpoints.csv`

  * `examples/` (per endpoint method+path)

  * `schemas/` (per schema JSON)

  * `report.txt` (“OpenAPI source: LIVE/IMPORT”, plus validation logs)

- - -

## 7) Reuse tip

Keep a tiny **starter repo** (or a `templates/fastapi-docs-kit/` folder) that already contains:

* `tools/docgen.py`

* `.vscode/tasks.json`

* `SPECIFY.md`\
  Then your future projects are literally copy → paste → run.
