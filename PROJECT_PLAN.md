# HKU Agentic Knowledge Assistant Plan

## Goal

Build an HKU-focused Agentic RAG assistant on top of this repository. The assistant should answer student questions from public HKU official sources, cite evidence, ask clarification questions when needed, remember stable user preferences, and expose a deployable API for future WeChat or web integration.

## Phase 0: Run the Original Project

- Use Python 3.11 or 3.12. Python 3.14 is likely too new for this dependency set.
- Create `.venv`.
- Install `requirements.txt`.
- Create `project/.env` from `project/.env.example` and set `GOOGLE_API_KEY`.
- Start `python project/app.py`.
- Upload a small PDF or Markdown file and verify chat retrieval works.

## Phase 1: HKU Data Ingestion

- Maintain source definitions in `project/data_sources/hku_sources.json`.
- Add an ingestion module that fetches public HKU web pages and stores cleaned Markdown in `markdown_docs/`.
- Preserve metadata on every document: `source_url`, `title`, `category`, `audience`, `degree_level`, `source_type`, `official`, `last_indexed_at`.
- Keep the first source set small and high quality before crawling more pages.

## Phase 2: HKU-Specific RAG

- Extend chunk metadata so parent and child chunks keep HKU source metadata.
- Keep parent-child chunking from the original project.
- Keep hybrid dense + sparse retrieval from the original project.
- Add metadata-aware retrieval later for category, degree level, faculty, and audience.

## Phase 3: Agentic Workflow

- Adapt prompts to the HKU domain.
- Classify questions into categories such as admissions, academic regulations, fees, scholarships, student life, visa, career, and faculty policy.
- Ask clarification questions when the user does not provide degree level, faculty, programme, or year and the answer depends on it.
- Generate answers only from retrieved evidence and include source URLs.

## Phase 4: Memory

- Start with lightweight profile memory: language preference, degree level, faculty, programme, and recurring topics.
- Store only stable facts or preferences, not every conversation detail.
- Use memory to improve query rewriting, not to override official sources.

## Phase 5: Evaluation

- Build `evals/questions.jsonl` with common HKU student questions.
- Track retrieval hit rate, citation presence, groundedness, refusal quality, and clarification quality.
- Include Chinese and English questions.

## Phase 6: Productization

- Keep Gradio for early demos.
- Add FastAPI once the RAG flow is stable.
- Expose `/chat`, `/sources`, `/feedback`, and `/health`.
- Connect WeChat Official Account or Mini Program through the FastAPI layer.

## First MVP Definition

- Index 20-50 public HKU official pages or documents.
- Answer in English or Chinese.
- Include citations.
- Ask for clarification on ambiguous policy questions.
- Provide a clear non-official disclaimer for high-impact topics.
