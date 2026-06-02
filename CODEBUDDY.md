# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## Project Overview

A Chinese web novel (武侠/xianxia) AI-powered review, optimization, and generation system. Two interfaces exist: a CLI for batch processing existing novels, and a FastAPI+Vue web platform for interactive generation from outlines.

## Running the System

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env to set OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

# CLI mode — process chapters from a directory
python main.py

# CLI mode — process a single novel file
python main.py --novel-file input/小说.txt

# CLI mode — single chapter with specific mode
python main.py --single 01 --mode generate    # generate from outline
python main.py --single 01 --mode review      # review only
python main.py --single 01 --mode optimize    # review + optimize

# Web platform
python run.py
# Opens browser at http://127.0.0.1:8000
# Set ENV=production to disable hot reload

# Batch reprocessing (example script for chapters 15-50)
python batch_run.py
```

## Architecture

### Two Independent Entry Points

1. **CLI** (`main.py` → `system.py`): Synchronous, processes existing novel chapters. Reads from `chapters/` directory or a single novel file. Uses `memory.md` and `memory_check.md` for cross-chapter state tracking.

2. **Web Platform** (`run.py` → `novel_api/`): Async FastAPI backend + vanilla Vue.js frontend. Supports interactive outline submission, chapter generation, review, and export via REST API + WebSocket real-time updates.

### Core Modules (shared by both modes)

| Module | Purpose |
|--------|---------|
| `system.py` | CLI orchestration: chapter iteration, mode dispatch (generate/review/optimize), memory coordination |
| `ai_reviewer.py` | Synchronous LLM calls (OpenAI API). Builds prompts for generation, review, optimization. Parses structured responses (report + optimized text + state update). Includes retry with exponential backoff. |
| `chapter_reader.py` | `ChapterReader` reads per-chapter files from a directory. `NovelParser` parses a single novel file into chapters using regex-based chapter title detection (supports 第X章/回/节/卷, 楔子/序章, numbered formats). |
| `memory_manager.py` | Reads/writes `memory.md` — tracks processing progress, story timeline, character/org/item/skill states, previous chapter ending state. Markdown-based structured state file. |
| `memory_check.py` | Reads/writes `memory_check.md` — entity memory for cross-chapter consistency checking. Tracks characters, buildings, sects, items, finance, pills, skills, relationships, conflicts, events, timeline. |

### Web Platform (`novel_api/`)

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app: REST endpoints + WebSocket + static file serving |
| `pipeline.py` | Async generation pipeline with 6-model architecture (A-F). Core state machine with pause/resume/cancel. Auto-saves/restores state to `output/pipeline_state.json`. |
| `llm_client.py` | Async LLM client (`AsyncOpenAI`). 600s timeout for long chapter generation. JSON extraction utilities. |
| `models.py` | Pydantic models: `ModelConfig`, `PipelineConfig`, `PipelineState`, `ChapterContent`, request/response schemas |
| `config_manager.py` | Loads/saves `config.json`. Config priority: config.json > .env > hardcoded defaults. 6 independent model configs (A-F). |
| `websocket_manager.py` | WebSocket connection pool with broadcast support for real-time UI updates |

### 6-Model Pipeline Architecture

The web platform uses 6 independently configurable LLM models:

- **Model A**: Outline optimization
- **Model B**: Outline review/assistant
- **Model C**: Content generation (chapter text from outline)
- **Model D**: Content review (audit chapter text)
- **Model E**: Chapter outline generation (generates chapter titles + summaries from plot)
- **Model F**: Review & optimize (combined review+optimization step)

Pipeline flow: Outline submit → (A: optimize + B: review) → E: generate chapter outlines → F: review outlines → F: optimize outlines → C: generate content → F: review & optimize content.

### Frontend

Vanilla Vue.js 3 SPA in `frontend/`. Single `index.html` + `js/app.js` + `css/style.css`. Communicates via REST API + WebSocket for real-time progress.

### State Persistence

- **CLI**: `memory.md` (progress + story state), `memory_check.md` (entity tracking), `output/` (generated chapters + reports)
- **Web**: `output/pipeline_state.json` (full pipeline state), `config.json` (model configs + prompts + plot), `output/memory_web.md` (story state for web mode)

## Configuration

- `.env`: API keys, base URL, model name. Each model (A-F) can have its own `MODEL_X_API_KEY` env var.
- `config.json`: Full pipeline config — 6 model configs, plot text, prompt templates, total chapters, min words per chapter. Config priority: `config.json` values > `.env` defaults.
- Prompt templates are stored in `config.json` fields: `chapter_gen_prompt`, `chapter_review_prompt`, `content_gen_prompt`, `review_optimize_prompt`.

## Key Design Patterns

- **Structured LLM output parsing**: Review responses use `=====审核报告=====`, `=====优化文本=====`, `=====状态更新=====` delimiters. Code parses these sections to extract report, optimized text, and state updates separately.
- **Memory-driven processing**: Both CLI and web modes maintain markdown-based memory files that track story state across chapters. Each chapter processing step updates these files so subsequent chapters have correct context.
- **Force-rewrite detection**: Pipeline detects when the LLM copies original text verbatim instead of actually optimizing, and re-prompts with a stricter "force rewrite" prompt (`_make_review_force_rewrite_prompt`).
