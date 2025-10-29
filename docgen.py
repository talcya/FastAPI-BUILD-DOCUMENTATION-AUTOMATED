
---

# 2) `tools/docgen.py` (the generator that creates the docs)

> Put this file at `tools/docgen.py`. It runs without external libs (only stdlib).

```python
#!/usr/bin/env python3
"""
FastAPI API Guide Generator
- Prefers live OpenAPI at http://localhost:8000/openapi.json
- Falls back to in-process import of FastAPI app and app.openapi()
- Falls back to static analysis (very basic) if needed
Outputs:
- API_GUIDE.md
- docs/openapi.snapshot.json
- docs/schemas/*.json
- docs/examples/*.{md,json}
- docs/postman_collection.json
- docs/endpoints.csv
- docs/report.txt
"""

import argparse, json, os, re, sys, importlib, inspect, pkgutil, textwrap
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs"
SCHEMAS_DIR = OUT_DIR / "schemas"
EXAMPLES_DIR = OUT_DIR / "examples"

DEFAULT_BASE = "http://localhost:8000"
OPENAPI_URL = f"{DEFAULT_BASE}/openapi.json"

def _mkdirs():
    OUT_DIR.mkdir(exist_ok=True)
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)

def fetch_live_openapi(url: str) -> Optional[Dict[str, Any]]:
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=5) as resp:
            data = json.load(resp)
            return data
    except (URLError, HTTPError, TimeoutError):
        return None

def import_app_and_get_openapi() -> Optional[Dict[str, Any]]:
    """
    Try common import paths to find a FastAPI app and call .openapi()
    """
    candidates = [
        "app.main",
        "app.app",
        "main",
        "app.__init__",
    ]
    for modname in candidates:
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        # find FastAPI instance
        for name, obj in inspect.getmembers(mod):
            # Lazy type check to avoid requiring fastapi import here
            if obj.__class__.__name__ == "FastAPI":
                try:
                    return obj.openapi()
                except Exception:
                    pass
    # Deep scan modules under app/
    app_pkg = ROOT / "app"
    if app_pkg.exists():
        sys.path.insert(0, str(ROOT))
        for _, modname, _ in pkgutil.walk_packages([str(app_pkg)], prefix="app."):
            try:
                mod = importlib.import_module(modname)
            except Exception:
                continue
            for name, obj in inspect.getmembers(mod):
                if obj.__class__.__name__ == "FastAPI":
                    try:
                        return obj.openapi()
                    except Exception:
                        pass
    return None

def static_route_scan() -> Dict[str, Any]:
    """
    Very lightweight fallback: glean routes via decorator strings.
    This is a best-effort heuristic; real completeness comes from OpenAPI.
    """
    routes: Dict[str, Any] = {}
    for path in ROOT.rglob("*.py"):
        if path.parts and any(p.startswith('.') for p in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # match @router.get("/x") / @app.post("/y")
        for m in re.finditer(r'@(?:\w+)\.(get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']', text, flags=re.I):
            method, route = m.group(1).upper(), m.group(2)
            routes.setdefault(route, {})
            routes[route].setdefault(method, {"summary": f"Discovered {method} {route} (static scan)", "parameters": []})
    # Build a minimal openapi-ish structure
    paths = {}
    for p, methods in routes.items():
        paths[p] = {}
        for m, meta in methods.items():
            paths[p][m.lower()] = {
                "summary": meta["summary"],
                "responses": {"200": {"description": "OK"}},
            }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Static Scan (Fallback)", "version": "0.0.0"},
        "paths": paths,
    }

def save_json(data: Dict[str, Any], path: Path):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def sanitize_filename(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._\-]+", "_", s)

def base_url_from_openapi(spec: Dict[str, Any]) -> str:
    servers = spec.get("servers") or []
    if servers and isinstance(servers, list) and servers[0].get("url"):
        return servers[0]["url"].rstrip("/")
    return DEFAULT_BASE

def extract_schemas(spec: Dict[str, Any]) -> Dict[str, Any]:
    return (spec.get("components") or {}).get("schemas") or {}

def op_security(op: Dict[str, Any]) -> bool:
    sec = op.get("security")
    return bool(sec) and isinstance(sec, list) and len(sec) > 0

def example_payload(schema: Dict[str, Any]) -> Any:
    """Very simple example generator based on types/enums/defaults."""
    if not isinstance(schema, dict):
        return None
    if "example" in schema:
        return schema["example"]
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type")
    if t == "string":
        fmt = schema.get("format")
        if fmt == "date-time": return "2025-01-01T00:00:00Z"
        if fmt == "email": return "user@example.com"
        if fmt == "uuid": return "00000000-0000-0000-0000-000000000000"
        return schema.get("default", "string")
    if t == "integer":
        return schema.get("default", 123)
    if t == "number":
        return schema.get("default", 1.23)
    if t == "boolean":
        return schema.get("default", True)
    if t == "array":
        return [example_payload(schema.get("items", {}))]
    if t == "object" or "properties" in schema:
        out = {}
        props = schema.get("properties", {})
        req = set(schema.get("required", []))
        for k, v in props.items():
            out[k] = example_payload(v)
            if out[k] is None and k in req:
                out[k] = "string"
        return out
    return schema.get("default", None)

def body_schema_from_op(op: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    req_body = op.get("requestBody")
    if not req_body:
        return None
    content = req_body.get("content") or {}
    for mt in ("application/json", "application/*+json", "multipart/form-data"):
        if mt in content:
            sch = content[mt].get("schema")
            if isinstance(sch, dict):
                return sch
    return None

def response_schema_from_op(op: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for code, resp in (op.get("responses") or {}).items():
        content = (resp or {}).get("content") or {}
        if "application/json" in content:
            sch = content["application/json"].get("schema")
            if sch:
                return sch
    return None

def code_samples(base: str, method: str, path: str, needs_auth: bool, body: Optional[dict]) -> str:
    url = f"{base}{path}"
    auth = '-H "Authorization: Bearer <token>" ' if needs_auth else ""
    body_json = json.dumps(body, ensure_ascii=False) if body is not None else None
    body_curl = f"-H \"Content-Type: application/json\" -d '{body_json}' " if body_json else ""
    body_httpie = f" Content-Type:application/json <<< '{body_json}'" if body_json else ""
    body_py = f"json={body_json}" if body_json else "params={}" if method == "GET" else "json={}"

    return textwrap.dedent(f"""
    **curl**
    ```bash
    curl -s -X {method} "{url}" {auth}{body_curl}
    ```

    **HTTPie**
    ```bash
    http {method} {url} {auth.strip()}{body_httpie}
    ```

    **Python (requests)**
    ```python
    import requests
    headers = {{"Authorization": "Bearer <token>"}} if {str(needs_auth)} else {{}}
    r = requests.{method.lower()}("{url}", headers=headers, {body_py})
    print(r.status_code)
    print(r.json() if "application/json" in r.headers.get("Content-Type","") else r.text)
    ```
    """).strip()

def write_endpoint_example(path: str, method: str, op: Dict[str, Any], base: str):
    needs_auth = op_security(op)
    body_schema = body_schema_from_op(op)
    body_example = example_payload(body_schema) if body_schema else None
    code = code_samples(base, method, path, needs_auth, body_example)
    fname = EXAMPLES_DIR / f"{sanitize_filename(method)}_{sanitize_filename(path)}.md"
    fname.write_text(code, encoding="utf-8")

def generate_postman(spec: Dict[str, Any], base: str) -> Dict[str, Any]:
    items = []
    for path, methods in (spec.get("paths") or {}).items():
        for method, op in methods.items():
            name = op.get("summary") or f"{method.upper()} {path}"
            url = base + path
            body_schema = body_schema_from_op(op)
            body_example = example_payload(body_schema) if body_schema else None
            item = {
                "name": name,
                "request": {
                    "method": method.upper(),
                    "header": [],
                    "url": {"raw": url, "protocol": "http", "host": ["localhost"], "port": "8000", "path": path.lstrip("/").split("/")},
                }
            }
            if body_example is not None:
                item["request"]["body"] = {
                    "mode": "raw",
                    "raw": json.dumps(body_example, indent=2),
                    "options": {"raw": {"language": "json"}}
                }
            items.append(item)
    return {
        "info": {"name": "FastAPI Collection", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "item": items
    }

def write_markdown(spec: Dict[str, Any], base: str):
    parts = []
    info = spec.get("info", {})
    title = info.get("title", "API Guide")
    version = info.get("version", "0.0.0")
    parts.append(f"# {title}\n\n**Version:** {version}\n\n**Base URL:** `{base}`\n")

    if "description" in info:
        parts.append(info["description"])

    parts.append("## Quick Start\n\n```bash\ncurl -s " + base + "/health || true\n```")

    # Security schemes
    components = spec.get("components", {})
    security_schemes = components.get("securitySchemes") or {}
    if security_schemes:
        parts.append("## Authentication\n")
        for name, sch in security_schemes.items():
            parts.append(f"- **{name}**: {sch.get('type','')} {sch.get('scheme','')}")
        parts.append("Add `Authorization: Bearer <token>` where required.\n")

    # Endpoints
    parts.append("## Endpoints\n")
    paths = spec.get("paths") or {}
    csv_lines = ["method,path,operationId,tags,summary"]
    for path, methods in paths.items():
        for method, op in methods.items():
            opid = op.get("operationId", "")
            tags = ", ".join(op.get("tags", []) or [])
            summary = op.get("summary", "")
            csv_lines.append(f"{method.upper()},{path},{opid},{tags},{summary}")

            parts.append(f"### {method.upper()} `{path}`")
            if summary:
                parts.append(f"**Summary:** {summary}")
            if tags:
                parts.append(f"**Tags:** {tags}")
            if op_security(op):
                parts.append("> Requires authentication\n")

            # Parameters
            params = op.get("parameters") or []
            if params:
                parts.append("**Parameters**")
                for p in params:
                    loc = p.get("in", "")
                    nm = p.get("name", "")
                    req = p.get("required", False)
                    schema = (p.get("schema") or {})
                    typ = schema.get("type", "")
                    dfl = schema.get("default", None)
                    parts.append(f"- `{nm}` ({loc}) — {typ}; required: {req}; default: {dfl}")

            # Request body
            body_schema = body_schema_from_op(op)
            if body_schema:
                ex = example_payload(body_schema)
                parts.append("**Request Body (JSON)**")
                parts.append("```json\n" + json.dumps(ex, indent=2, ensure_ascii=False) + "\n```")

            # Responses
            parts.append("**Responses**")
            for code, resp in (op.get("responses") or {}).items():
                desc = (resp or {}).get("description", "")
                parts.append(f"- **{code}**: {desc}")
                content = (resp or {}).get("content") or {}
                if "application/json" in content:
                    sch = content["application/json"].get("schema")
                    if sch:
                        ex = example_payload(sch)
                        if ex is not None:
                            parts.append("```json\n" + json.dumps(ex, indent=2, ensure_ascii=False) + "\n```")

            # Samples
            write_endpoint_example(path, method.upper(), op, base)
            parts.append(f"[Examples →](docs/examples/{sanitize_filename(method.upper())}_{sanitize_filename(path)}.md)")

            parts.append("")

    # Models/Schemas
    schemas = extract_schemas(spec)
    if schemas:
        parts.append("## Schemas\n")
        for name, sch in schemas.items():
            save_json(sch, SCHEMAS_DIR / f"{sanitize_filename(name)}.json")
            parts.append(f"### `{name}`")
            if "description" in sch:
                parts.append(sch["description"])
            ex = example_payload(sch)
            if ex is not None:
                parts.append("**Example**")
                parts.append("```json\n" + json.dumps(ex, indent=2, ensure_ascii=False) + "\n```")

    (OUT_DIR / "endpoints.csv").write_text("\n".join(csv_lines), encoding="utf-8")
    (ROOT / "API_GUIDE.md").write_text("\n\n".join(parts), encoding="utf-8")

def validate_sample_endpoints(spec: Dict[str, Any], base: str, allow_destructive: bool = False) -> List[str]:
    """
    Make safe GET requests for a few endpoints (health, docs, etc.).
    Avoid POST/PUT/PATCH/DELETE unless explicitly allowed.
    """
    import http.client, urllib.parse
    logs = []
    test_paths = []
    paths = spec.get("paths") or {}
    # Pick a few "safe" candidates
    for p, methods in paths.items():
        if "get" in methods and any(seg in p for seg in ["/health", "/live", "/ready", "/docs", "/openapi.json"]):
            test_paths.append(("GET", p))
    # Fallback: first 3 GET endpoints
    if not test_paths:
        for p, methods in list(paths.items())[:10]:
            if "get" in methods:
                test_paths.append(("GET", p))
                if len(test_paths) >= 3:
                    break

    parsed = urllib.parse.urlparse(base)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=3)
    for method, path in test_paths:
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            logs.append(f"{method} {path} -> {resp.status}")
            resp.read()
        except Exception as e:
            logs.append(f"{method} {path} -> ERROR {e}")
    conn.close()
    return logs

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefer", choices=["live","import","static"], default="live", help="Preferred openapi source")
    parser.add_argument("--validate", choices=["none","sample"], default="none")
    parser.add_argument("--allow-destructive", action="store_true")
    parser.add_argument("--openapi-url", default=OPENAPI_URL)
    args = parser.parse_args()

    _mkdirs()
    report = []

    # Select source
    spec = None
    order = {
        "live": ["live", "import", "static"],
        "import": ["import", "live", "static"],
        "static": ["static", "live", "import"]
    }[args.prefer]

    for mode in order:
        if mode == "live":
            spec = fetch_live_openapi(args.openapi_url)
            if spec:
                report.append(f"OpenAPI source: LIVE ({args.openapi_url})")
                break
        elif mode == "import":
            spec = import_app_and_get_openapi()
            if spec:
                report.append("OpenAPI source: IMPORT (app.openapi())")
                break
        elif mode == "static":
            spec = static_route_scan()
            report.append("OpenAPI source: STATIC (fallback)")
            break

    if not spec:
        print("ERROR: Could not obtain OpenAPI spec from any source.", file=sys.stderr)
        sys.exit(2)

    save_json(spec, OUT_DIR / "openapi.snapshot.json")

    base = base_url_from_openapi(spec)
    write_markdown(spec, base)

    # Postman
    postman = generate_postman(spec, base)
    save_json(postman, OUT_DIR / "postman_collection.json")

    # Validation
    if args.validate == "sample":
        logs = validate_sample_endpoints(spec, base, args.allow_destructive)
        report.extend(["Validation:", *logs])

    (OUT_DIR / "report.txt").write_text("\n".join(report), encoding="utf-8")
    print("OK: API_GUIDE.md and docs/ generated.")

if __name__ == "__main__":
    main()
