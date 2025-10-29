# SPECIFY: Generate Comprehensive API Documentation for FastAPI Project

project_name: games_backend
project_type: fastapi
description: >
  This FastAPI backend powers multiple game services (users, profiles, games,
  leaderboards, store, groups, wallets, anti-cheat, and score). The goal is to
  auto-scan all APIs, models, and schemas, and generate a detailed README guide
  showing how to use every endpoint with examples.

entry_point:
  module: app.main_application
  app_instance: app
  port: 8000
  base_url: http://localhost:8000

output:
  docs_dir: docs/
  main_readme: API_GUIDE.md
  postman_collection: docs/postman_collection.json
  openapi_snapshot: docs/openapi.snapshot.json
  schema_exports: docs/schemas/
  endpoint_examples: docs/examples/
  endpoint_list_csv: docs/endpoints.csv
  validation_report: docs/report.txt

scan_targets:
  - app/
  - app/models/
  - app/schemas/
  - app/api/
  - app/routers/
  - app/services/
  - app/dependencies/
  - scripts/

generation_steps:
  - Try fetching OpenAPI from http://localhost:8000/openapi.json
  - If unavailable, import app.main_application:app and call app.openapi()
  - If both fail, statically scan @router decorators in app/api and app/routers
  - Parse all Pydantic models and schemas (BaseModel)
  - Detect relationships among models (e.g., user → profile → game → leaderboard)
  - Extract endpoint metadata (summary, tags, params, responses, examples)
  - Build comprehensive markdown guide (API_GUIDE.md)
  - Export OpenAPI JSON, schemas, and sample requests/responses
  - Generate per-endpoint runnable examples in curl, HTTPie, and Python requests
  - Create a Postman collection for quick import

validation:
  enabled: true
  safe_endpoints:
    - /health
    - /health/detailed
    - /health/database
    - /health/ready
    - /health/live
    - /api/v1/auth/health
  destructive_allowed: false
  request_timeout: 5

documentation_content:
  overview:
    - Base URL: http://localhost:8000
    - Swagger UI: /docs
    - ReDoc: /redoc
    - OpenAPI JSON: /openapi.json
    - Authentication: Bearer token (JWT)
  include_sections:
    - Quick Start
    - Authentication and Security Schemes
    - Endpoint Catalog (grouped by tag)
    - Parameters and Request Schemas
    - Response Schemas and Examples
    - Error Codes and Validation
    - Models and Data Relationships
    - Example Code Snippets
  examples:
    formats:
      - curl
      - httpie
      - python_requests

rules:
  - Every endpoint listed in OpenAPI must appear in API_GUIDE.md
  - Each documented POST/PUT/PATCH must include a sample payload
  - For GET endpoints, show sample query parameters if available
  - All schemas must have field types, required/default flags, and examples
  - No placeholder or TODO text is allowed in the generated guide

output_checks:
  - Verify API_GUIDE.md exists and is >500 lines
  - Verify docs/openapi.snapshot.json is valid JSON
  - Verify every tag in OpenAPI appears in the markdown guide
  - Validate 3 safe GET endpoints to confirm live docs match code

success_message: |
  ✅ Documentation successfully generated!
  API_GUIDE.md and supporting files are available in the docs/ directory.

notes:
  - This project uses MongoDB at mongodb://localhost:27017 (database: games_backend)
  - Related models:
      * users → profiles → games → leaderboards
      * store → wallets → groups → anti-cheat → score
  - Prefer to import and call app.openapi() instead of manual scanning when possible.
  - Agent may execute `python tools/docgen.py --prefer import --validate sample` if file exists.
