# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state: backend complete (e2e-tested) + frontend MVP built

**Read [memory-bank/](memory-bank/) first** — it tracks what is done, what is pending, and how to run things (start at [memory-bank/README.md](memory-bank/README.md)). It is the handoff record kept up to date across sessions.

Implemented: full `backend/app/` (FastAPI + LangGraph 6-node graph + HITL via PostgresSaver, e2e-tested with real Gemini) and `frontend/` (Next.js 14 App Router + TS + Tailwind + SWR — MVP with 4 pages; design tokens in `frontend/DESIGN.md`). `docker-compose.yml` runs db + backend + frontend + mailhog. The vector layer (pgvector) is live for semantic search of past applicants; email sending is live over SMTP (MailHog in dev, real SMTP via env in prod); the API is behind JWT auth (username/password login); LangSmith tracing is wired (activates when `LANGCHAIN_*` env is set — no code toggle). Still pending: further hardening (TLS, non-root container, rate-limit backing store) — see [memory-bank/04_security.md](memory-bank/04_security.md) for the security review and pre-deploy checklist.

**Run everything through Docker** (`docker compose up`). The dev machine has Windows Smart App Control (Enforcement) which blocks unsigned binary wheels (`psycopg[binary]`, `charset_normalizer`) in a native Windows venv — Linux containers bypass this. `.venv` at the repo root exists only for IDE type-checking. Do not suggest disabling Smart App Control (one-way door; the user chose Docker). **Frontend runs on host port 4000** (not 3000 — that range is reserved by Windows/WinNAT); backend CORS allows both.

The briefs remain the source of truth for structure, schemas, and prompts. Read the relevant brief before writing code in that layer:

When implementing, the briefs are the source of truth for structure, schemas, and prompts. Read the relevant brief before writing code in that layer:

| Layer | Brief |
| --- | --- |
| Overall goal, workflow, roadmap | [project_brief.md](brief/project_brief.md) |
| LangGraph nodes, state, routing | [backend_langgraph.md](brief/backend_langgraph.md) |
| FastAPI endpoints, folder layout, deps | [backend_fastapi.md](brief/backend_fastapi.md) |
| Postgres DDL, checkpointer setup | [database_supabase.md](brief/database_supabase.md) |
| Next.js pages, design system | [frontend_nextjs.md](brief/frontend_nextjs.md) |
| Embeddings / semantic search | [vectordb_chroma.md](brief/vectordb_chroma.md) |

The briefs are Thai-language; keep new docs and commit messages consistent with whatever the user is writing in.

## What the system is meant to do

An HR resume-screening assistant. HR uploads a job description and a batch of PDF resumes; a multi-agent LangGraph pipeline parses both, scores each candidate against the JD, audits the scoring for bias, and then either drafts interview questions or a rejection email. Candidates in the ambiguous scoring band stop the graph and wait for a human decision.

## Architecture: the pieces only make sense together

**One graph, one state object.** `HRSystemState` (a `TypedDict`) is the single value threaded through every node — raw inputs, parsed JD, parsed resumes, evaluations, HR decisions, and generated outputs all live on it. Nodes are pure state transformers. Changing a field means checking every node that reads it, so keep it in `app/agents/state.py` as the one definition (`project_brief.md` and `backend_langgraph.md` both show it; they must not drift apart).

**Node order is fixed and each stage depends on the previous one's normalized output:** `jd_analyzer` → `resume_parser` → `retrieve_similar` → `matcher` → `bias_auditor` → conditional router. The reason `resume_parser` exists as a separate node is that it must emit resumes in *the same JSON shape* as the JD analyzer's `JobRequirement`, so `matcher` can do a field-by-field gap analysis rather than free-text comparison. Fit score is weighted: required skills 60%, preferred skills 40%.

**`retrieve_similar` is an optional RAG agent** (`app/agents/nodes/retriever.py`), toggled by `RAG_ENABLED`. When off it is a pure no-op — the node stays in the graph so the shape (and checkpointer) never changes; it just returns empty. When on it queries pgvector for past applicants with a similar skill profile (`vectors.search(..., exclude_candidate_id=cid)` so a re-indexed candidate can't match itself), stored on `evaluations.similar_candidates` and surfaced to the UI. It uses **embedding quota (separate from the 20/day chat quota)** and `interview_planner` folds the result into its existing prompt, so it adds **zero** chat calls. Scope: comparative context for the human + sharper interview questions — it does **not** change the deterministic fit score.

**Skill comparison lives in one place: `app/agents/skills.py`.** `matcher` must not compare skill strings itself. Comparison is on *token boundaries*, never substrings — the original `n in o or o in n` counted required `R` as satisfied by `docke**r**`/`redis`/`postg**r**esql` and `ML` by `ht**ml**`. Two tables carry the cases token boundaries can't: `ALIASES` (same thing spelled differently, `NodeJs`/`Node.js`) and `IMPLIES` (one skill subsumes another, PostgreSQL ⟹ SQL). `IMPLIES` is one-directional on purpose. `is_skill()` drops role nouns (`product owners`, `engineers`) that the JD analyzer sometimes emits as skills; they would otherwise inflate the denominator and push everyone's score down. Changes here move every candidate's score — add a case to `tests/test_skills.py` first.

**The router is the heart of the product.** After `bias_auditor`, `route_candidates` decides:
- **an HR decision on record wins over the score, always** — `approved` → advance, `rejected` → reject
- otherwise `> 70` → advance, and `runner` auto-resumes past the interrupt
- otherwise `50–70` → advance, but `runner` stops and waits for HR
- otherwise `< 50` → `email_drafter` (rejection)

**Every threshold lives in `app/agents/bands.py`.** Never write `50` or `70` anywhere else — they were previously duplicated across the router, runner, drafter, matcher, a script, and the frontend, so moving a boundary silently desynced the badge colors from the path the graph actually took. `frontend/lib/types.ts::scoreBand` is the one unavoidable copy; change both together.

**Human-in-the-Loop: resume when paused, rewind when finished.** The graph is compiled with a checkpointer and `interrupt_before=["interview_planner"]`. `runner.resume_after_decision` handles two cases and **must keep handling both**:
- graph paused at the interrupt → write `hr_decision`/`hr_notes`, continue from there
- graph already finished (auto-advanced above 70, or auto-rejected below 50) → `update_state(..., as_node="bias_auditor")` rewinds to just after the auditor so the router re-decides with the HR decision in hand, then `_drive_to_end` walks it out (the interrupt fires again on the way, so a single `invoke` is not enough)

Without the rewind branch, HR could never overturn an automatic decision: the API returned 200 and the UI claimed success while nothing ran. `<50` candidates were unrescuable by construction. `CandidateDetail.graph_status` tells the UI which case it is.

In neither case may the graph re-run from the entry point — that re-bills every LLM call and loses context. Approving a paused candidate costs exactly 2 LLM calls (planner + drafter); rejecting a finished one costs 1 (drafter only). Also note state is cumulative across rewinds: when a rerun takes the reject path it never visits the planner, so `_persist_outputs` clears a stale `interview_plan` whenever the draft is a rejection.

**Checkpointer storage matters.** `backend_langgraph.md` shows `SqliteSaver.from_conn_string(":memory:")`, which is illustrative only — in-memory state dies on restart and breaks HITL. `database_supabase.md` supersedes it: use `PostgresSaver` from `langgraph-checkpoint-postgres` against the Supabase connection string, and call `saver.setup()` once to create the checkpoint tables.

**Deleting a candidate is the narrow-scope sibling of deleting a job.** `DELETE /api/v1/candidates/{id}` exists for the wrong-file / duplicate-upload case — cascade touches only that person's `evaluations`, `hr_decisions`, and `resume_embeddings`. `candidates.py::_candidate_deletion_blocker` applies the same two rules as jobs (409 if an email was sent to them, 409 if the graph is running), and checkpoint cleanup is the same `delete_thread`-after-commit ordering. Note the duplicate-upload case it exists for is not prevented at the source: upload does not dedupe, so the same PDF uploaded twice creates two candidates, two graph runs, and two chances to email the same person — `email_sent_at` lives on `evaluations`, so it is per-row, not per-person.

**Job lifecycle: close, don't delete.** `jobs.status` is `open | closed`; `PATCH /api/v1/jobs/{id}` flips it and `upload_resumes` returns 409 on a closed job. Closing is the intended move when a role is filled, because `candidates.job_id` cascades all the way to `evaluations`, `hr_decisions`, and `resume_embeddings` — deleting a job shrinks the RAG corpus `retrieve_similar` depends on and destroys the `email_sent_at`/`email_sent_to` audit trail. `DELETE /api/v1/jobs/{id}` exists for jobs created by mistake and is guarded by `jobs.py::_deletion_blocker`: it refuses (409) if any email was already sent, or if the graph is mid-run for one of the job's candidates (`runner.active_candidates()`, an in-process set — same single-replica caveat as the login rate limiter). Checkpoint rows have no FK to `candidates`, so `delete_job` collects `candidate_id`s *before* the cascade and calls `PostgresSaver.delete_thread` per thread **after** the DB commit — that order is deliberate: a failure there leaves harmless orphans, whereas the reverse would wreck the HITL state of a job that still exists.

**Resume upload is asynchronous.** `POST /api/v1/jobs/{job_id}/resumes` extracts text with `pdfplumber`, writes candidate rows immediately, then kicks the graph off as a background task and returns. The frontend polls the candidate list; it does not wait on the graph.

**Background tasks die with the process, so stalled candidates need a visible escape hatch.** `BackgroundTasks` is in-process: a container restart, hot-reload, or an exhausted Gemini quota leaves a candidate row with no `evaluations` row and nothing that will ever finish it — and the UI's `pending` band renders that as "กำลังวิเคราะห์…" forever. `candidates.py::_is_stalled` (no evaluation + not in `runner.active_candidates()` + older than `STALLED_AFTER_SEC`, default 90) marks those `stalled` on `CandidateSummary`/`CandidateDetail`, and `POST /api/v1/candidates/{id}/reprocess` re-runs one from the `raw_resume_text` already in the DB — no re-upload. It refuses (409) if an evaluation already exists (a rerun would burn quota and could overwrite an HR decision) or if the candidate is already active. Cost is ~3 chat calls per candidate. Because the registry drives both this badge and the delete guard, `_run_graph_for_job` reserves the **whole batch** up front via `reserve_candidates` — reserving per-candidate would make everyone still queued look dead.

## Stack and conventions

- **Backend:** Python 3.10+, FastAPI + Uvicorn, LangGraph/LangChain, `langchain-google-genai`. The briefs say Gemini 1.5 Flash/Pro, but **1.5 is retired (404 NOT_FOUND) and Pro is unavailable on the free tier (429, `limit: 0`)**. `app/agents/llm.py` therefore defaults both tiers to `gemini-2.5-flash`, overridable via `GEMINI_DEFAULT_MODEL` / `GEMINI_COMPLEX_MODEL`. Restore the Flash/Pro split by setting `GEMINI_COMPLEX_MODEL=gemini-2.5-pro` once the key has billing.
- **Structured output:** every LLM-producing node defines a Pydantic v2 model for its output (e.g. `JobRequirement`) rather than parsing free text.
- **Persistence:** Supabase Postgres. Four app tables — `jobs`, `candidates`, `evaluations`, `hr_decisions` — plus LangGraph's own checkpoint tables. DDL lives in `database_supabase.md`; `hr_decisions.candidate_id` is `UNIQUE` (one decision per candidate).
- **Vectors:** **pgvector** (the `db` service uses `pgvector/pgvector:pg16`), table `resume_embeddings` with an HNSW cosine index; code in `app/vectors.py`, exposed as `GET /api/v1/candidates/search`. Embeddings are `models/gemini-embedding-001` truncated to 768 dims via `output_dimensionality` — the `VECTOR(768)` column and `EMBEDDING_DIM` must stay in sync. (The briefs say `models/text-embedding-004`; that model is no longer callable — it is absent from ListModels.)
  - **Scope: ranking for a human, never a matching decision.** Measured cosine on this model puts PostgreSQL↔MySQL at 0.885 and Java↔JavaScript at 0.865, *above* a pair that should match (React Native↔Mobile Hybrid, 0.838) — so no threshold separates them. Skill matching is deterministic in `app/agents/skills.py`; do not replace it with similarity.
- **Frontend:** Next.js App Router + TypeScript, dark glassmorphism theme (violet `#8B5CF6` primary, emerald = pass, amber = needs review). Backend is published on host port **8080** (container still listens on 8000; host 8000 falls in WinNAT's reserved 7909–8008 range and can't bind — same Windows issue as 3000→4000), frontend at `:4000`; the browser calls the backend via `NEXT_PUBLIC_API_BASE_URL=http://localhost:8080`. CORS must allow the frontend origin explicitly.
- **Tracing:** LangSmith is wired. It is env-driven, not a code toggle — LangChain/LangGraph auto-instrument when `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` are set (SDK also honors `LANGSMITH_*`); absent those, callbacks no-op with zero overhead. `runner._config` labels each graph run (`run_name=screen-candidate-<id8>`, `tags=["talentmatch","screening"]`, `metadata.candidate_id`) so a candidate's trace is findable in the LangSmith UI. `app/tracing.py::tracing_status` logs on/off at startup. Any new graph invocation should pass a config built the same way so its trace is labeled too.

## Secrets

`.env` in `backend/` holds the Gemini API key, Supabase connection string, LangSmith key, and (for prod) SMTP credentials. Nothing runs without them; `.env.example` documents every variable — keep it in sync when adding code that reads a new one. A root `.gitignore` now excludes `.env` (the repo is not yet a git repo, but the guard is in place before the first commit).

**Auth gates every endpoint except `/health` and `/api/v1/auth/login`.** JWT (HS256) with `app/auth.py::get_current_user` applied as a router-level dependency on jobs/candidates/hr — add the same dependency to any new router. `JWT_SECRET` has no hardcoded default on purpose (a shared default = anyone can forge tokens); the app refuses to sign/verify without it. The initial user is seeded from `ADMIN_USERNAME`/`ADMIN_PASSWORD` in `init_db()` (idempotent). Login is rate-limited in memory per IP+username (5 fails / 5 min → 429) — swap for Redis before running more than one backend replica. Frontend stores the Bearer token in `localStorage` and `lib/api.ts::request` attaches it and redirects to `/login` on any 401; `AppShell` guards routes and hides its chrome on `/login`.

**Email send is synchronous and HR-gated.** `POST /api/v1/candidates/{id}/email/send` takes the recipient/subject/body that HR sees and confirms on screen — never the LLM-parsed `candidate.email` directly, because that address comes from an uploaded PDF and sending to it blindly would make the app a spam relay. `app/email_sender.py` uses `email.message.EmailMessage` (header-injection safe) plus a CRLF sanitizer. Dev sends to MailHog (`mailhog:1025`, UI at :8025); prod overrides `SMTP_*` env for real SMTP. Uploads are size/count-capped and magic-byte-checked in `candidates.py`.
