## 💡 Where to put this

* Save it in your **repo root** as:

  ```
  specify.yaml
  ```

  or

  ```
  SPECIFY.md
  ```

* Your AI agent will detect it automatically if it supports GitHub-style “spec-kit” conventions.

- - -

## 🛠️ Optional: Quick command for your agent

If your AI agent supports instructions-in-context:

```
Run Python script tools/docgen.py to generate documentation for all APIs and models.
Prefer importing app.main_application:app and using app.openapi().
Output files in /docs/ and API_GUIDE.md.
```

# .vscode/tasks.json

Create a folder `.vscode/` in your repo root and paste this file as `.vscode/tasks.json`.

```
{
  // VS Code build tasks for games_backend
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Start FastAPI (Uvicorn:8000)",
      "type": "shell",
      "command": "${config:python.defaultInterpreterPath}",
      "args": [
        "-m",
        "uvicorn",
        "app.main_application:app",
        "--reload",
        "--port",
        "8000"
      ],
      "options": {
        "cwd": "${workspaceFolder}"
      },
      "isBackground": true,
      "problemMatcher": {
        "owner": "python",
        "background": {
          "activeOnStart": true,
          "beginsPattern": ".",
          "endsPattern": "Application startup complete."
        },
        "pattern": [
          {
            "regexp": "^(.*)$",
            "file": 1,
            "location": 1,
            "message": 1
          }
        ]
      },
      "detail": "Runs Uvicorn so the doc generator can pull live OpenAPI at http://localhost:8000/openapi.json"
    },

    {
      "label": "Docgen: live + validate",
      "type": "shell",
      "command": "${config:python.defaultInterpreterPath}",
      "args": [
        "tools/docgen.py",
        "--prefer",
        "live",
        "--validate",
        "sample"
      ],
      "options": {
        "cwd": "${workspaceFolder}"
      },
      "problemMatcher": []
    },

    {
      "label": "Docgen: import (no server needed)",
      "type": "shell",
      "command": "${config:python.defaultInterpreterPath}",
      "args": [
        "tools/docgen.py",
        "--prefer",
        "import",
        "--validate",
        "none"
      ],
      "options": {
        "cwd": "${workspaceFolder}"
      },
      "problemMatcher": []
    },

    {
      "label": "Docgen: static fallback",
      "type": "shell",
      "command": "${config:python.defaultInterpreterPath}",
      "args": [
        "tools/docgen.py",
        "--prefer",
        "static",
        "--validate",
        "none"
      ],
      "options": {
        "cwd": "${workspaceFolder}"
      },
      "problemMatcher": []
    },

    {
      "label": "Docs: clean (API_GUIDE.md + docs/)",
      "type": "shell",
      "command": "${config:python.defaultInterpreterPath}",
      "args": [
        "-c",
        "import os,shutil; shutil.rmtree('docs', ignore_errors=True); \
p='API_GUIDE.md'; \
print('Removed docs/'); \
(open(p,'w').close() if os.path.exists(p) else None) or (os.remove(p) if os.path.exists(p) else None)"
      ],
      "options": {
        "cwd": "${workspaceFolder}"
      },
      "problemMatcher": []
    },

    {
      "label": "Generate Docs (Live, start server then docgen)",
      "dependsOn": [
        "Start FastAPI (Uvicorn:8000)",
        "Docgen: live + validate"
      ],
      "dependsOrder": "sequence"
    }
  ]
}
```

### Notes

* `${config:python.defaultInterpreterPath}` uses your selected Python from VS Code’s Python extension. If that’s not set, replace with `python` (Linux/macOS) or `py` (Windows).

* The Uvicorn task runs **in the background** and waits for the log line `Application startup complete.` before the docgen task proceeds.

- - -

# Quick How-To

1. **Make sure the spec-kit is in place**

   * You already copied `SPECIFY.md`.

   * Ensure `tools/docgen.py` exists (from my earlier zip) and is tracked in your repo.

2. **Open your repo in VS Code**

   * The `.vscode/tasks.json` file should be detected automatically.

3. **Run one of these tasks**

   * Press `Ctrl+Shift+B` (or `Cmd+Shift+B` on macOS) to open the task picker:

     * **Generate Docs (Live, start server then docgen)** → starts Uvicorn on port **8000** and generates docs using the live `openapi.json` (recommended).

     * **Docgen: import (no server needed)** → imports `app.main_application:app` and calls `app.openapi()` directly.

     * **Docgen: static fallback** → quick best-effort scan if both live/import are unavailable.

     * **Docs: clean** → removes `docs/` and `API_GUIDE.md` so you can regenerate fresh.

4. **Where outputs land**

   * Root: `API_GUIDE.md`

   * `docs/`:

     * `openapi.snapshot.json`

     * `postman_collection.json`

     * `endpoints.csv`

     * `examples/` (per-endpoint runnable examples)

     * `schemas/` (per-schema JSON)

     * `report.txt` (source used + validation results)

5. **What to read first**

   * Open `API_GUIDE.md` for the comprehensive, human-friendly reference.

   * Import `docs/postman_collection.json` into Postman for quick testing.

- - -

# Optional (nice to have)

## .vscode/launch.json (debug FastAPI easily)

If you want to F5-debug the API while generating docs, add this file:

```
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Debug FastAPI (Uvicorn:8000)",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": [
        "app.main_application:app",
        "--reload",
        "--port",
        "8000"
      ],
      "jinja": true,
      "justMyCode": true,
      "console": "integratedTerminal",
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  ]
}
```

Then:

* F5 to start the server in debug mode.

* Run **Docgen: live + validate** (no need for the compound task if you prefer manual control).

- - -

# Troubleshooting

* **Python not found in tasks**\
  Set your interpreter in VS Code (bottom status bar) or update tasks to use `python` / `py`.

* **Port conflict**\
  If something else is on `8000`, change the port in both:

  * `Start FastAPI (Uvicorn:8000)` args

  * The `base_url` and `--openapi-url` you pass to docgen, e.g.:

    ```
    json
    Copy code
    "args": ["tools/docgen.py", "--prefer", "live", "--validate", "sample", "--openapi-url", "http://localhost:9000/openapi.json"]
    ```

* **AssertionError: Path parameters cannot have a default value**\
  That’s a FastAPI error from a route like `def get_item(id: str = Path(None))`. Fix by removing the default: `id: str = Path(...)` or `id: str` with no default. (This is separate from the doc tool, but it will block `openapi.json` from loading.)
  
