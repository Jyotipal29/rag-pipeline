---
status: active
created: 2026-06-01
updated: 2026-06-01
title: DocMind AI Backend Implementation Plan
version: 1.0
---

# DocMind AI Backend Implementation Plan

**Objective:** Build a production FastAPI backend that wraps the existing research RAG pipeline, adding user authentication, personal document uploads, shared research library, and real-time chat with strict data isolation.

**Key Constraint:** Never rewrite the existing RAG pipeline. Import and call it. User data isolation is mandatory at every layer.

**Scope:** 20+ implementation units across 6 phases, 8+ new modules, comprehensive test coverage.

**Success Criteria:**
- All new modules are async/await throughout
- User data is isolated (no user can access another user's documents)
- Existing RAG pipeline is called unchanged
- Full test coverage for new modules (auth, documents, chat, library)
- Production-ready error handling and logging
- SSE streaming works end-to-end

---

## Executive Summary

DocMind AI is a multi-user research platform. Phase 1 (this plan) focuses on the backend foundation:

1. **Authentication** — email/password + Google OAuth
2. **User Management** — profile, stats, token management
3. **Document Upload & Indexing** — personal PDFs with background processing
4. **Chat & History** — SSE streaming Q&A over personal docs + shared papers
5. **Research Library** — pre-loaded papers with topic search
6. **Integration** — wraps existing RAG pipeline without modification

After Phase 1, the backend will be ready for a Next.js 15 frontend to consume.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Client (Next.js 15)                        │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
          ┌─────────▼─────────┐        ┌──────────▼──────────┐
          │   FastAPI Backend │        │    Websocket/SSE    │
          │   (New Layer 1)   │        │     Chat Stream     │
          └─────────┬─────────┘        └────────────────────┘
                    │
        ┌───────────┼───────────┐
        │           │           │
   ┌────▼──┐  ┌─────▼────┐  ┌──▼────┐
   │ Auth  │  │  Users   │  │Docs   │
   └────┬──┘  └─────┬────┘  └──┬────┘
        │           │          │
   ┌────▼──────┐ ┌──▼──────┐ ┌─▼──────────────┐
   │  JWT      │ │MongoDB  │ │ Background Job │
   │  Manager  │ │ (Motor) │ │  (Pipeline Adp)│
   └───────────┘ └─────────┘ └────────┬───────┘
                                       │
                                ┌──────▼──────────┐
                                │  Existing RAG   │
                                │  Pipeline       │
                                │  (Unchanged)    │
                                ├─────────────────┤
                                │ Qdrant + BM25   │
                                │ (two collections)
                                └─────────────────┘
```

**New Layer 1** handles:
- User authentication (email/password, Google OAuth)
- User & document lifecycle
- Background indexing via pipeline wrapper
- Chat streaming + history
- Research library search
- Request/response contracts
- Logging & error handling

**Pipeline Adapter** is the critical bridge:
- Receives user_id + doc data
- Calls existing ingestion/indexing services
- Ensures user_id metadata reaches Qdrant payloads
- Reports status back to MongoDB

**Two Qdrant Collections:**
- `user_documents`: user-uploaded PDFs (filtered by user_id + doc_id)
- `research_papers`: shared library papers (filtered by doc_id only)

---

## Requirements Trace

### Functional

1. **User Registration** — email + password OR Google OAuth
2. **User Login** — email/password with refresh token rotation
3. **JWT Token Management** — access (15min) + refresh (30d) tokens
4. **PDF Upload** — multipart, validation, background processing
5. **Document Status** — polling endpoint for upload progress
6. **Chat with Q&A** — SSE streaming, history, citations
7. **Research Library** — search, filter by topic/year, pagination
8. **Data Isolation** — users cannot access each other's documents
9. **Error Handling** — structured JSON errors with HTTP codes
10. **Rate Limiting** — auth endpoints (5/min), upload (10/hr)

### Non-Functional

1. **Async Throughout** — FastAPI async, Motor for DB, no blocking
2. **Type Safety** — Pydantic models for all I/O
3. **Logging** — structlog with request context
4. **Testing** — pytest + httpx AsyncClient, >80% coverage
5. **Security** — no hardcoded secrets, bcrypt hashing, JWT validation

---

## Implementation Phases

### Phase 0: Setup & Configuration
**Duration:** 1-2 hours  
**Deliverable:** Dependencies installed, config extended, Docker compose updated

| Unit | Goal | Files |
|------|------|-------|
| **U0** | Install dependencies & extend config | `requirements.txt`, `app/config/settings.py`, `.env.example`, `docker-compose.yml` |

### Phase 1: Authentication & JWT
**Duration:** 3-4 hours  
**Deliverable:** Functional auth endpoints, JWT token mgmt, refresh rotation

| Unit | Goal | Files |
|------|------|-------|
| **U1** | Auth schemas & JWT utils | `app/auth/schemas.py`, `app/auth/utils.py` |
| **U2** | Email/password registration | `app/auth/router.py` (register), `app/auth/service.py` |
| **U3** | Email/password login + refresh | `app/auth/router.py` (login, refresh), token rotation logic |
| **U4** | Google OAuth integration | `app/auth/router.py` (google, callback), httpx token exchange |
| **U5** | JWT dependencies | `app/auth/dependencies.py` (get_current_user, optional_user) |
| **U6** | Email service (Resend) | `app/auth/email_service.py` (send verification, reset) |
| **U7** | Auth tests | `tests/test_auth.py` (register, login, google, refresh, email) |

### Phase 2: User & Document Management
**Duration:** 4-5 hours  
**Deliverable:** User profiles, document CRUD, upload pipeline, status polling

| Unit | Goal | Files |
|------|------|-------|
| **U8** | MongoDB setup | `app/db/mongo.py`, `app/db/collections.py` (indexes) |
| **U9** | Users schema & service | `app/users/schemas.py`, `app/users/service.py`, `app/users/router.py` |
| **U10** | Documents schema & service | `app/documents/schemas.py`, `app/documents/service.py` |
| **U11** | Upload endpoint & validation | `app/documents/router.py` (POST /upload) |
| **U12** | Pipeline adapter | `app/documents/pipeline_adapter.py` (**critical: user_id injection**) |
| **U13** | Document status polling | `app/documents/router.py` (GET /status) |
| **U14** | Document CRUD (list, get, delete) | `app/documents/router.py` (GET /, GET /{id}, DELETE) |
| **U15** | Documents tests | `tests/test_documents.py` (upload, status, crud) |

### Phase 3: Chat & Streaming
**Duration:** 3-4 hours  
**Deliverable:** SSE streaming Q&A, message history, citations

| Unit | Goal | Files |
|------|------|-------|
| **U16** | Chat schema & service | `app/chat/schemas.py`, `app/chat/service.py` |
| **U17** | SSE streaming endpoint | `app/chat/router.py` (POST /message), EventSourceResponse |
| **U18** | Message history CRUD | `app/chat/router.py` (GET /history, DELETE /history) |
| **U19** | Chat tests | `tests/test_chat.py` (streaming, history, user isolation) |

### Phase 4: Research Library
**Duration:** 2-3 hours  
**Deliverable:** Library seeding, search, filtering

| Unit | Goal | Files |
|------|------|-------|
| **U20** | Library schema & service | `app/library/schemas.py`, `app/library/service.py` |
| **U21** | Library endpoints | `app/library/router.py` (GET /, GET /{id}, GET /topics) |
| **U22** | Library seeding script | `app/library/seed.py`, `scripts/seed_library.py` |
| **U23** | Library tests | `tests/test_library.py` (list, search, filter, seed) |

### Phase 5: Integration & Polish
**Duration:** 2-3 hours  
**Deliverable:** Main app wiring, middleware, error handling, final tests

| Unit | Goal | Files |
|------|------|-------|
| **U24** | Core exceptions & responses | `app/core/exceptions.py`, `app/core/responses.py` |
| **U25** | Logging middleware | `app/middleware/logging.py` (structlog request logging) |
| **U26** | Main app wiring | `app/main.py` (extend: add routers, CORS, rate limiter) |
| **U27** | Rate limiting | Slowapi integration on auth & upload endpoints |
| **U28** | Integration tests | `tests/test_pipeline_adapter.py`, end-to-end chat flow |
| **U29** | Final review & polish | Type checking, logging completeness, edge cases |

---

## Critical Integration Points

### Pipeline Adapter (`app/documents/pipeline_adapter.py`)

This module bridges new backend to existing RAG pipeline. **Do not modify the existing pipeline; call it as-is.**

**User ID Injection (CRITICAL):**
The existing pipeline's `app/indexing/` and `app/vectorstore/qdrant_client.py` must store `user_id` in Qdrant chunk payloads. Check if metadata passthrough exists; if not, add a thin wrapper in `pipeline_adapter.py` that:
1. Calls existing `extract_pdf()` (from `app/ingestion/pdf_extractor.py`)
2. Calls existing `index_document()` (from `app/indexing/` — check current implementation)
3. **Injects metadata:** `{"user_id": user_id, "doc_type": "user_doc"}` into chunk payloads before Qdrant upsert
4. Reports status back to MongoDB

**Verification:** After indexing a user doc, query Qdrant with filter `user_id == <id>` and confirm chunks are isolated.

### Query Filtering

Every chat request must add user_id filter to Qdrant query:

```python
# In app/chat/service.py
# For user docs:
retrieve_for_question(
    question,
    document_ids=[qdrant_doc_id],  # Existing pipeline param
    user_id=current_user.id,       # NEW: add this
    # Existing pipeline's retrieve_for_question must accept user_id
    # and apply it in hybrid_search() filters
)
```

**Verification:** Write a test where User A uploads a doc, User B queries → User B gets "no results" (not User A's data).

---

## Data Models (MongoDB)

### Users Collection
```python
{
    "_id": ObjectId,
    "email": str,               # unique index
    "password_hash": str | None,  # None for OAuth users
    "name": str,
    "auth_provider": "email" | "google",
    "google_id": str | None,    # sparse unique index
    "is_verified": bool,
    "verification_token": str | None,
    "reset_token": str | None,
    "reset_token_expires": datetime | None,
    "refresh_token_hash": str | None,
    "created_at": datetime,
    "updated_at": datetime,
}
```

### Documents Collection
```python
{
    "_id": ObjectId,
    "user_id": ObjectId,        # compound index
    "filename": str,
    "storage_path": str,
    "page_count": int | None,
    "file_size_bytes": int,
    "status": "processing" | "ready" | "error",
    "error_message": str | None,
    "summary": str | None,
    "chunk_count": int | None,
    "qdrant_collection": str,   # "user_documents"
    "qdrant_doc_id": str,       # document_id for retrieval
    "created_at": datetime,
    "updated_at": datetime,
}
```

### Chat Messages Collection
```python
{
    "_id": ObjectId,
    "user_id": ObjectId,        # compound index
    "doc_id": str,              # MongoDB ObjectId or paper_id
    "doc_type": "user_doc" | "paper",
    "role": "user" | "assistant",
    "content": str,
    "source_chunks": [          # assistant only
        {"page": int, "preview": str, "score": float}
    ],
    "query_type": str | None,
    "created_at": datetime,
}
```

### Research Papers Collection
```python
{
    "_id": ObjectId,
    "title": str,
    "authors": list[str],
    "year": int,
    "abstract": str,
    "topic_tags": list[str],    # index for filtering
    "summary": str,
    "source_url": str | None,
    "reading_time_mins": int,
    "chunk_count": int,
    "qdrant_doc_id": str,
    "qdrant_collection": str,   # "research_papers"
    "created_at": datetime,
}
```

---

## Environment Variables

Extend `app/config/settings.py` with:

```python
# MongoDB
MONGODB_URL: str = "mongodb://localhost:27017"
MONGODB_DB_NAME: str = "docmind"

# JWT
JWT_SECRET: str
JWT_REFRESH_SECRET: str
JWT_ACCESS_EXPIRE_MINUTES: int = 15
JWT_REFRESH_EXPIRE_DAYS: int = 30

# Google OAuth
GOOGLE_CLIENT_ID: str
GOOGLE_CLIENT_SECRET: str
GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"

# Email (Resend)
RESEND_API_KEY: str
EMAIL_FROM: str = "noreply@docmind.ai"
FRONTEND_URL: str = "http://localhost:3000"

# File Limits
MAX_PDF_SIZE_MB: int = 50
MAX_PDF_PAGES: int = 200

# Storage
UPLOAD_DIR: str = "data/raw"

# Rate Limiting
RATE_LIMIT_AUTH: str = "5/minute"
RATE_LIMIT_UPLOAD: str = "10/hour"

# Existing RAG pipeline (already present, verify):
# OPENAI_API_KEY, COHERE_API_KEY, etc.
```

---

## API Endpoints

### Auth Routes

```
POST   /auth/register             # email + password signup
POST   /auth/login                # returns access token
POST   /auth/logout               # invalidates refresh token
POST   /auth/refresh              # rotate refresh token
GET    /auth/google               # redirect to Google consent
GET    /auth/google/callback      # exchange code → JWT
POST   /auth/verify-email         # consume verification token
POST   /auth/forgot-password      # send reset email
POST   /auth/reset-password       # consume reset token
```

### User Routes

```
GET    /users/me                  # current user profile + stats
PUT    /users/me                  # update profile
DELETE /users/me                  # delete account
```

### Document Routes

```
POST   /documents/upload          # multipart upload
GET    /documents/                # list user's docs
GET    /documents/{id}            # document detail
GET    /documents/{id}/status     # upload progress
DELETE /documents/{id}            # delete doc + vectors + history
```

### Chat Routes

```
POST   /chat/{doc_id}/message     # SSE streaming Q&A
GET    /chat/{doc_id}/history     # paginated message history
DELETE /chat/{doc_id}/history     # clear history for doc
```

### Library Routes

```
GET    /library/                  # list papers (search, filter, sort)
GET    /library/{id}              # paper detail
GET    /library/topics            # list unique topic tags
```

---

## Testing Strategy

### Test Fixtures (conftest.py)

```python
@pytest.fixture
async def test_user():
    """Create test user in test DB."""
    user = {"email": "test@example.com", "password_hash": "...", ...}
    return await db.users.insert_one(user)

@pytest.fixture
async def test_auth_header(test_user):
    """Generate JWT for test user."""
    token = create_access_token(str(test_user["_id"]))
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
async def async_client():
    """FastAPI test client."""
    return AsyncClient(app=app, base_url="http://test")

@pytest.fixture
async def test_db():
    """Test MongoDB instance."""
    # Connect to test DB, create indexes
    yield db
    # Cleanup
```

### Test Coverage by Unit

| Unit | Test File | Key Scenarios |
|------|-----------|--------------|
| U1-U7 | `test_auth.py` | register, login, refresh, google oauth, email verification |
| U8-U15 | `test_documents.py` | upload, validation, status, list, get, delete, isolation |
| U16-U19 | `test_chat.py` | streaming, history, citations, user isolation |
| U20-U23 | `test_library.py` | search, filter, topics, seed, pagination |
| U12 | `test_pipeline_adapter.py` | user_id injection, qdrant metadata, existing pipeline calls |

### Integration Tests

**End-to-End Chat Flow:**
1. User registers
2. User uploads PDF
3. Wait for processing (poll status endpoint)
4. User queries document via SSE stream
5. Verify citations + source chunks
6. Verify message appears in history
7. User B tries to query User A's doc → 403 or "no results"

---

## Critical Design Decisions

### 1. User ID Injection

**Decision:** Qdrant payloads must include `user_id` for every chunk (user docs and papers).

**Rationale:** Every retrieval query must filter by user_id to prevent data leakage. The existing pipeline's `retrieve_for_question()` must be extended to accept a `user_id` parameter and apply it in Qdrant filters.

**Implementation:** Check `app/retrieval/hybrid.py` (the BM25 + dense search logic). If it doesn't support user_id filters, add them in `pipeline_adapter.py` as a thin wrapper around the existing function.

**Verification Test:** Upload same question doc to two users, query from each → User B sees 0 results from User A's doc.

### 2. Refresh Token Rotation

**Decision:** On `/refresh`, issue a new refresh token and invalidate the old one (hash stored in MongoDB).

**Rationale:** Limits damage if a refresh token is leaked. Each refresh token is single-use.

**Implementation:** `app/auth/utils.py` maintains `refresh_token_hash` in MongoDB. On refresh, verify incoming token hash against stored value, delete the old hash, store the new one.

**Verification Test:** Refresh twice in sequence → second refresh (with original token) fails.

### 3. Background Processing

**Decision:** Use FastAPI `BackgroundTasks` for initial MVP (not Celery).

**Rationale:** Simpler for Phase 1; can upgrade to Celery/RabbitMQ in Phase 2 if needed.

**Implementation:** `/documents/upload` returns immediately with `status: processing`. Background task calls `pipeline_adapter.run_pipeline()`, updates MongoDB status.

**Verification Test:** Upload triggers background job. Poll `/status` endpoint and watch transition from "processing" → "ready".

### 4. SSE Streaming

**Decision:** Use `sse-starlette` library for Server-Sent Events (not WebSocket).

**Rationale:** HTTP-based, compatible with all reverse proxies, simpler than WebSocket for unidirectional streaming.

**Implementation:** `app/chat/router.py` returns `EventSourceResponse()` that yields JSON-formatted SSE events.

**Verification Test:** Stream a query, verify token-by-token arrival in browser DevTools Network tab.

### 5. Two Qdrant Collections

**Decision:** Separate `user_documents` (per-user, filtered by user_id) from `research_papers` (shared, filtered by topic/year).

**Rationale:** Different indexing cadence and access patterns. User docs need re-indexing on upload; papers are static seed data.

**Implementation:** Chat service checks `doc_type` field in MongoDB document and routes to the correct collection. Retrieval queries apply user_id filter only for user docs.

**Verification Test:** Query paper by ID → no user_id filter applied. Query user doc → user_id filter applied.

---

## Execution Notes

### Deferred to Implementation

1. **Existing Pipeline Integration:** Before starting U12 (pipeline adapter), read `app/indexing/` to understand how metadata is passed to Qdrant. May need to extend it slightly to accept `user_id` in chunk payloads.

2. **Qdrant Filter Syntax:** Confirm Qdrant's filter syntax for `user_id` field in the existing pipeline's `retrieve_for_question()` function (likely in `app/retrieval/hybrid.py`).

3. **Motor Connection Pooling:** Research optimal Motor connection pool settings for the expected concurrency.

4. **SSE Client Support:** Test SSE stream in a real browser to confirm event format and error handling.

### Pattern Matching

Before implementing, check existing patterns in the codebase:

- **Async utilities:** How are background tasks currently handled in the RAG pipeline?
- **Pydantic models:** How are request/response models structured in `app/models/`?
- **Error handling:** What exception classes exist in the pipeline?
- **Logging:** How is structlog configured (if at all)?

### Branch & Commit Strategy

**Branch:** `feat/docmind-backend`

**Commits by phase:**
- Phase 0: "setup: install dependencies, extend config, docker-compose"
- Phase 1: "feat: add authentication (JWT, OAuth, email)"
- Phase 2: "feat: add user & document management"
- Phase 3: "feat: add chat with SSE streaming"
- Phase 4: "feat: add research library"
- Phase 5: "feat: integrate and polish, rate limiting, logging"

---

## Success Criteria Checklist

### Phase 1 Completion (Auth)
- [ ] `POST /auth/register` works with email/password
- [ ] `POST /auth/login` returns access + refresh tokens
- [ ] `POST /auth/refresh` rotates tokens
- [ ] `GET /auth/google` returns auth URL
- [ ] `GET /auth/google/callback` exchanges code → JWT
- [ ] All auth tests pass (>80% coverage)

### Phase 2 Completion (Documents)
- [ ] `POST /documents/upload` triggers background job
- [ ] `GET /documents/{id}/status` reflects processing state
- [ ] Document appears in Qdrant with `user_id` payload
- [ ] `GET /documents/` lists only current user's docs
- [ ] `DELETE /documents/{id}` removes doc + vectors + history
- [ ] All document tests pass, including isolation tests

### Phase 3 Completion (Chat)
- [ ] `POST /chat/{doc_id}/message` streams SSE events
- [ ] Stream includes tokens, sources, metadata
- [ ] `GET /chat/{doc_id}/history` returns paginated messages
- [ ] User A cannot see User B's chat history
- [ ] All chat tests pass

### Phase 4 Completion (Library)
- [ ] `GET /library/` searches papers by topic, year, title
- [ ] Papers are searchable and indexed in Qdrant
- [ ] Seeding script populates 20+ papers
- [ ] All library tests pass

### Phase 5 Completion (Integration)
- [ ] Main app routes all modules correctly
- [ ] Rate limiting applied to auth & upload
- [ ] Logging captures all requests with context
- [ ] End-to-end integration test (register → upload → query → history) passes
- [ ] Type checking (mypy/pyright) passes
- [ ] All tests pass, >80% coverage

---

## References & Dependencies

### Technology Stack (New)

| Concern | Library | Version |
|---------|---------|---------|
| Database | Motor (async MongoDB) | 3.6+ |
| Auth | python-jose | 3.3+ |
| Password | passlib[bcrypt] | 1.7+ |
| Google OAuth | httpx | 0.27+ |
| Email | resend | 1.3+ |
| MIME Check | python-magic | 0.4+ |
| Rate Limit | slowapi | 0.1+ |
| SSE | sse-starlette | 1.3+ |
| Logging | structlog | 24.1+ |

### Existing Pipeline (Do Not Modify)

- `app/ingestion/` — PDF extraction
- `app/chunking/` — Token-aware chunking
- `app/embeddings/` — OpenAI embeddings
- `app/vectorstore/qdrant_client.py` — Vector store ops
- `app/retrieval/` — Hybrid search, reranking
- `app/rag/pipeline.py` — Q&A pipeline
- `app/generation/` — LLM calls

### Key Files to Create

**Phase 1:**
- `app/auth/{router, service, utils, dependencies, schemas, email_service}.py`
- `app/config/settings.py` (extend)
- `requirements.txt` (extend)
- `tests/test_auth.py`

**Phase 2:**
- `app/db/{mongo, collections}.py`
- `app/users/{router, service, schemas}.py`
- `app/documents/{router, service, schemas, pipeline_adapter}.py`
- `tests/test_documents.py`

**Phase 3:**
- `app/chat/{router, service, schemas}.py`
- `tests/test_chat.py`

**Phase 4:**
- `app/library/{router, service, schemas, seed}.py`
- `scripts/seed_library.py`
- `tests/test_library.py`

**Phase 5:**
- `app/core/{exceptions, responses}.py`
- `app/middleware/logging.py`
- `app/main.py` (extend)
- `tests/test_pipeline_adapter.py`
- `docker-compose.yml` (extend with MongoDB)

---

## Next Steps

1. **Phase 0:** Install dependencies, extend config (1-2 hours)
2. **Phases 1-5:** Execute units in order, running tests after each unit completion
3. **Final Review:** Type checking, logging completeness, edge cases
4. **Documentation:** Update README with new API endpoints and setup instructions

---

**Document Status:** Ready for implementation  
**Plan Version:** 1.0  
**Last Updated:** 2026-06-01
