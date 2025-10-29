#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, csv, re, zipfile
from pathlib import Path
from datetime import datetime

# PDF deps
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import Color, white
    HAVE_RL = True
except Exception:
    HAVE_RL = False

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OPENAPI = DOCS / "openapi.snapshot.json"
POSTMAN = DOCS / "postman_collection.json"
SCHEMAS_DIR = DOCS / "schemas"
EXAMPLES_DIR = DOCS / "examples"
ENDPOINTS_CSV = DOCS / "endpoints.csv"

OUT_MD = ROOT / "API_GUIDE.md"
OUT_PDF = ROOT / "API_GUIDE_SUMMARY.pdf"
OUT_ZIP = ROOT / "API_DOCUMENTATION_BUNDLE.zip"

def safe_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def type_of(schema: dict) -> str:
    if not isinstance(schema, dict): return "object"
    t = schema.get("type")
    if t: return t if not isinstance(t, list) else "|".join(t)
    if "properties" in schema: return "object"
    if "items" in schema: return "array"
    if "oneOf" in schema: return "oneOf"
    if "anyOf" in schema: return "anyOf"
    if "allOf" in schema: return "allOf"
    return "object"

def flatten_allof(schema: dict) -> dict:
    if not isinstance(schema, dict): return schema
    if "allOf" in schema:
        merged = {}
        for part in schema["allOf"]:
            part = flatten_allof(part)
            if not isinstance(part, dict): continue
            for k,v in part.items():
                if k == "properties":
                    merged.setdefault("properties", {}).update(v or {})
                elif k == "required":
                    merged.setdefault("required", [])
                    merged["required"] = list(sorted(set(merged["required"]) | set(v or [])))
                else:
                    merged[k] = v
        return merged
    return schema

def resolve_ref(obj, comp_schemas):
    if not isinstance(obj, dict): return obj
    ref = obj.get("$ref")
    if ref and ref.startswith("#/components/schemas/"):
        name = ref.split("/")[-1]
        return comp_schemas.get(name, {})
    return obj

def example_for(name: str, schema: dict, depth=0):
    if not isinstance(schema, dict): return "example"
    if "example" in schema: return schema["example"]
    if "default" in schema: return schema["default"]
    if "enum" in schema: return schema["enum"][0]
    t = schema.get("type")
    fmt = schema.get("format")
    if t == "string" or t is None:
        if fmt == "date-time": return "2025-01-01T12:00:00Z"
        if fmt == "date": return "2025-01-01"
        if fmt == "email" or (name and "email" in name.lower()): return "user@example.com"
        if fmt == "uuid" or (name and name.lower().endswith("_id")): return "123e4567-e89b-12d3-a456-426614174000"
        return f"example_{name or 'text'}"
    if t == "integer": return 123
    if t == "number": return 12.34
    if t == "boolean": return True
    if t == "array":
        item = example_for(f"{name}_item", schema.get("items", {}), depth+1)
        return [item] if depth>1 else [item, item]
    if t == "object" or "properties" in schema:
        props = (schema.get("properties") or {})
        return {k: example_for(k, v, depth+1) for k, v in props.items()}
    return "example"

def schema_md(schema: dict, level=0) -> str:
    schema = flatten_allof(schema or {})
    indent = "  " * level
    out = []
    out.append(f"{indent}- **type**: `{type_of(schema)}`")
    if "description" in schema:
        out.append(f"{indent}- **description**: {schema['description']}")
    req = schema.get("required", [])
    if req:
        out.append(f"{indent}- **required**: {', '.join(req)}")
    if "properties" in schema and isinstance(schema["properties"], dict):
        out.append(f"{indent}- **properties**:")
        for k, v in schema["properties"].items():
            out.append(f"{indent}  - `{k}` ({type_of(v)})")
            ex = example_for(k, v)
            out.append(f"{indent}    - example: `{json.dumps(ex, ensure_ascii=False)}`")
            if isinstance(v, dict) and ("properties" in v or "items" in v or "allOf" in v):
                out.append(schema_md(v, level+2))
    if schema.get("type") == "array" and "items" in schema:
        out.append(f"{indent}- **items**:")
        out.append(schema_md(schema["items"], level+1))
    if "enum" in schema:
        out.append(f"{indent}- **enum**: {', '.join(map(str, schema['enum']))}")
    return "\n".join(out)

def parameters_table(params: list) -> str:
    if not params: return "_No parameters._\n"
    rows = ["| In | Name | Required | Type | Description | Example |",
            "|---|---|---|---|---|---|"]
    for p in params:
        loc = p.get("in","query")
        nm = p.get("name","")
        req = "✅" if p.get("required", False) else "⚪"
        sch = p.get("schema", {}) or {}
        t = type_of(sch)
        desc = p.get("description","")
        ex = sch.get("example", example_for(nm, sch))
        rows.append(f"| {loc} | `{nm}` | {req} | `{t}` | {desc} | `{json.dumps(ex)}` |")
    return "\n".join(rows) + "\n"

def invalid_payloads(schema: dict):
    base = example_for("root", schema)
    out = []
    sc = flatten_allof(schema or {})
    req = sc.get("required", [])
    if isinstance(base, dict) and req:
        bad = dict(base); bad.pop(req[0], None); out.append(bad)
    else:
        out.append(None)
    if isinstance(base, dict) and base:
        bad2 = dict(base); k0 = next(iter(bad2)); bad2[k0] = {"oops":"wrong"} if not isinstance(bad2[k0], dict) else 123; out.append(bad2)
    else:
        out.append({"unexpected":"field"})
    if isinstance(base, dict):
        bad3 = dict(base); bad3["_unexpected"] = "surprise"; out.append(bad3)
    else:
        out.append("totally-wrong")
    return out[:3]

# Load documents
openapi = safe_json(OPENAPI) or {}
paths = (openapi.get("paths") or {})
components = (openapi.get("components") or {})
comp_schemas = (components.get("schemas") or {})
servers = (openapi.get("servers") or [{"url":"http://localhost:8000"}])
server_url = servers[0].get("url","http://localhost:8000")

# Group endpoints by tag
by_tag = {}
method_order = ["get","post","put","patch","delete","options","head"]
for path_str, methods in paths.items():
    for m, meta in methods.items():
        if m.lower() not in method_order: 
            continue
        tags = meta.get("tags") or ["Untagged"]
        for t in tags:
            by_tag.setdefault(t, []).append((m.upper(), path_str, meta))
tags_sorted = sorted(by_tag.keys())

# Build Markdown
md = []
md.append("# Unified API Guide")
md.append(f"_Generated by AI Assistant on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%SZ')}_\n")
md.append("> **Single Source of Truth** for this API. Grouped by tags. Includes parameters, full schemas, 3 example requests, and valid/invalid payloads (where applicable).\n")
md.append("## Table of Contents")
for t in tags_sorted:
    anchor = re.sub(r'[^a-z0-9]+','-', t.lower()).strip('-')
    md.append(f"- [{t}](#{anchor})")
md.append("")

# Inventory & cross-check
postman = safe_json(POSTMAN) or {}
pm_count = 0
def walk_pm(items):
    global pm_count
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                pm_count += 1; walk_pm(it.get("item"))
walk_pm(postman.get("item"))
md.append("## Snapshot Validation & Inventory")
md.append(f"- OpenAPI: `{OPENAPI}` {'✅' if openapi else '❌ missing/invalid'}")
md.append(f"- Postman: `{POSTMAN}` {'✅' if postman else '⚠️ not found'} (items: {pm_count})")
md.append(f"- Schemas dir: `{SCHEMAS_DIR}` {'✅' if SCHEMAS_DIR.exists() else '⚠️ not found'}")
if ENDPOINTS_CSV.exists():
    csv_eps = set()
    with ENDPOINTS_CSV.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            meth = (r.get("method") or r.get("METHOD") or "").upper()
            path_val = r.get("path") or r.get("endpoint") or r.get("url") or r.get("PATH") or ""
            if meth and path_val:
                csv_eps.add(f"{meth} {path_val.strip()}")
    oapi_eps = set()
    for pth, methods in paths.items():
        for m in methods:
            if m.lower() in method_order:
                oapi_eps.add(f"{m.upper()} {pth}")
    missing_in_openapi = sorted(list(csv_eps - oapi_eps))
    missing_in_csv = sorted(list(oapi_eps - csv_eps))
    md.append(f"- Endpoints in OpenAPI: **{len(oapi_eps)}** / in CSV: **{len(csv_eps)}**")
    if missing_in_openapi:
        md.append("- ⚠️ In CSV but missing in OpenAPI:")
        for ep in missing_in_openapi[:80]:
            md.append(f"  - `{ep}`")
    if missing_in_csv:
        md.append("- ℹ️ In OpenAPI but not in CSV:")
        for ep in missing_in_csv[:80]:
            md.append(f"  - `{ep}`")
md.append("")

# Endpoint docs
for t in tags_sorted:
    md.append(f"## {t}\n")
    items = by_tag[t]
    items.sort(key=lambda x: (x[1], method_order.index(x[0].lower())))
    for method, path_str, meta in items:
        summary = meta.get("summary") or meta.get("operationId") or f"{method} {path_str}"
        op_id = meta.get("operationId","")
        md.append(f"### {method} `{path_str}`")
        md.append(f"**Summary:** {summary}")
        if op_id: md.append(f"**operationId:** `{op_id}`")

        params = meta.get("parameters") or []
        md.append("\n**Parameters**\n")
        md.append(parameters_table(params))

        rb = meta.get("requestBody") or {}
        rb_schema = None
        rb_content = rb.get("content") or {}
        for mt in ["application/json","application/x-www-form-urlencoded","multipart/form-data","text/plain"]:
            if mt in rb_content:
                sch = rb_content[mt].get("schema") or {}
                rb_schema = resolve_ref(sch, comp_schemas)
                break
        if rb_schema:
            md.append("**Request Body Schema**\n")
            md.append(schema_md(rb_schema))
            md.append("\n**Valid Payload Examples (x3)**")
            for i in range(3):
                ex = example_for("body", rb_schema)
                md.append(f"\n<details><summary>Valid #{i+1}</summary>\n\n```json\n{json.dumps(ex, indent=2, ensure_ascii=False)}\n```\n</details>")
            md.append("\n**Invalid Payload Examples (x3)**")
            for i, bad in enumerate(invalid_payloads(rb_schema), 1):
                md.append(f"\n<details><summary>Invalid #{i}</summary>\n\n```json\n{json.dumps(bad, indent=2, ensure_ascii=False)}\n```\n</details>")
        else:
            md.append("**Request Body**: _None_")

        responses = meta.get("responses") or {}
        if responses:
            md.append("\n**Responses**")
            for code, rs in responses.items():
                desc = rs.get("description","")
                md.append(f"- **{code}**: {desc}")
                content = rs.get("content") or {}
                chosen = None
                for mt in ["application/json","*/*","text/plain"]:
                    if mt in content: chosen = content[mt]; break
                if not chosen and content:
                    chosen = list(content.values())[0]
                if chosen:
                    sch = resolve_ref(chosen.get("schema") or {}, comp_schemas)
                    if sch:
                        md.append("  - **Schema**\n")
                        md.append(schema_md(sch))

        headers = {"Accept":"application/json"}
        if rb_schema: headers["Content-Type"]="application/json"
        example_body = example_for("body", rb_schema) if rb_schema else None
        url = server_url.rstrip("/") + path_str
        md.append("\n**Example Requests (x3)**")
        # cURL
        curl_lines = [f"curl -X {method} '{url}' \\"]
        for hk,hv in headers.items(): curl_lines.append(f"  -H '{hk}: {hv}' \\")
        if example_body is not None and method in ("POST","PUT","PATCH","DELETE"):
            curl_lines.append(f"  -d '{json.dumps(example_body)}'")
        md.append("\n<details><summary>cURL</summary>\n\n```bash\n" + "\n".join(curl_lines) + "\n```\n</details>")
        # HTTPie
        httpie = f"http {method.lower()} {url}"
        for hk,hv in headers.items(): httpie += f" {hk}:'{hv}'"
        if example_body is not None and method in ("POST","PUT","PATCH","DELETE"):
            if isinstance(example_body, dict):
                for k,v in example_body.items(): httpie += f" {k}:={json.dumps(v)}"
            else:
                httpie += f" <<< '{json.dumps(example_body)}'"
        md.append("\n<details><summary>HTTPie</summary>\n\n```bash\n" + httpie + "\n```\n</details>")
        # fetch
        fetch_code = f"fetch('{url}', {{\n  method: '{method}',\n  headers: {json.dumps(headers, indent=2)},\n  credentials: 'include'"
        if example_body is not None and method in ("POST","PUT","PATCH","DELETE"):
            fetch_code += f",\n  body: JSON.stringify({json.dumps(example_body)})"
        fetch_code += "\n}).then(r => r.json()).then(console.log).catch(console.error);"
        md.append("\n<details><summary>JavaScript fetch()</summary>\n\n```javascript\n" + fetch_code + "\n```\n</details>\n")
        md.append("---\n")

# Append component schemas
if comp_schemas:
    md.append("## Data Models Appendix (OpenAPI components)\n")
    for name, sc in comp_schemas.items():
        md.append(f"### `{name}`\n")
        md.append(schema_md(sc))

# Append external schemas
if SCHEMAS_DIR.exists():
    md.append("## Data Models Appendix (External)\n")
    for p in sorted(SCHEMAS_DIR.glob("*.json")):
        try:
            sc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        md.append(f"### `{p.stem}`\n")
        md.append(schema_md(sc))

md.append(f"\n---\n*Generated by AI Assistant on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%SZ')}*")

OUT_MD.write_text("\n".join(md), encoding="utf-8")

# PDF (dark, compact)
if HAVE_RL:
    PAGE_W, PAGE_H = A4
    c = canvas.Canvas(str(OUT_PDF), pagesize=A4)
    bg = Color(0.11, 0.12, 0.14); fg = white; accent = Color(0.4, 0.8, 1.0)

    def new_page():
        c.setFillColor(bg); c.rect(0,0,PAGE_W,PAGE_H, fill=1, stroke=0); c.setFillColor(fg)

    def draw_wrapped(text, x, y, width, leading=11, font="Helvetica", size=9, color=white):
        from reportlab.lib.utils import simpleSplit
        c.setFont(font, size); c.setFillColor(color)
        lines = simpleSplit(text, font, size, width)
        for ln in lines:
            c.drawString(x, y, ln); y -= leading
        return y

    new_page()
    c.setFont("Helvetica-Bold", 18); c.setFillColor(accent)
    c.drawString(20*mm, PAGE_H-20*mm, "API Guide – Summary (Dark)")
    c.setFillColor(fg); c.setFont("Helvetica", 10)
    c.drawString(20*mm, PAGE_H-26*mm, f"Generated on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%SZ')}")
    y = PAGE_H-34*mm

    # Build short data
    method_order = ["get","post","put","patch","delete","options","head"]
    def short_payload(schema: dict, max_keys=5):
        ex = example_for("body", schema or {})
        if isinstance(ex, dict):
            keys = list(ex.keys())[:max_keys]
            return {k: ex[k] for k in keys}
        return ex

    for tag in sorted(by_tag.keys()):
        eps = sorted(by_tag[tag], key=lambda x: (x[1], x[0]))
        if y < 30*mm: c.showPage(); new_page(); y = PAGE_H-20*mm
        c.setFont("Helvetica-Bold", 12); c.setFillColor(accent); c.drawString(15*mm, y, tag); y -= 6*mm
        c.setFillColor(fg); c.setFont("Helvetica", 9)
        for method, path_str, meta in eps:
            if y < 35*mm:
                c.showPage(); new_page(); y = PAGE_H-20*mm
                c.setFont("Helvetica-Bold", 12); c.setFillColor(accent); c.drawString(15*mm, y, f"{tag} (cont.)"); y -= 6*mm
                c.setFillColor(fg); c.setFont("Helvetica", 9)
            c.setFillColor(Color(0.85,0.9,1.0))
            c.drawString(18*mm, y, f"{method}  {path_str}"); y -= 5*mm
            c.setFillColor(fg)
            smry = meta.get("summary") or meta.get("operationId") or ""
            if smry: y = draw_wrapped(f"• {smry}", 18*mm, y, PAGE_W-36*mm, leading=10)
            reqs = [p.get("name") for p in (meta.get("parameters") or []) if p.get("required")]
            if reqs: y = draw_wrapped("Required: " + ", ".join(reqs[:6]), 18*mm, y, PAGE_W-36*mm, leading=10)
            rb = meta.get("requestBody") or {}
            rb_schema = None
            rb_content = rb.get("content") or {}
            for mt in ["application/json","application/x-www-form-urlencoded","multipart/form-data","text/plain"]:
                if mt in rb_content:
                    sch = rb_content[mt].get("schema") or {}
                    rb_schema = resolve_ref(sch, comp_schemas)
                    break
            if rb_schema is not None:
                y = draw_wrapped("Payload: " + json.dumps(short_payload(rb_schema), ensure_ascii=False), 18*mm, y, PAGE_W-36*mm, leading=10)
            y -= 3*mm

    c.setFont("Helvetica-Oblique", 8); c.setFillColor(Color(0.7,0.7,0.7))
    c.drawString(20*mm, 12*mm, "Generated by AI Assistant • Dark Summary PDF")
    c.save()

# ZIP
with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(OUT_MD, arcname="API_GUIDE.md")
    if OUT_PDF.exists(): z.write(OUT_PDF, arcname="API_GUIDE_SUMMARY.pdf")

print("DONE:", OUT_MD, OUT_PDF if OUT_PDF.exists() else "(no-pdf)", OUT_ZIP)
