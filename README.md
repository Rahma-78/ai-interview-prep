# 🎯 AI Interview Prep

> **AI-powered technical interview preparation system** that analyzes resumes, discovers authoritative sources, and generates deep technical questions using state-of-the-art LLMs.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![Hugging Face Spaces](https://img.shields.io/badge/%F0%9F%A4%96%20Hugging%20Face-Spaces-yellow.svg)](https://huggingface.co/spaces/Rahma07/AI-questions-gen)


---

## 📋 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [API Documentation](#-api-documentation)
- [Project Structure](#-project-structure)
- [Development](#-development)

---

## 🌟 Overview

AI Interview Prep is an intelligent system that transforms resume PDFs into comprehensive technical interview question sets. It leverages multiple LLM providers to:

1. **Extract** key technical skills from resumes
2. **Discover** authoritative sources via Google Search (Gemini grounding)
3. **Generate** insightful interview questions based on real-world context

---

## ✨ Features

### Core Capabilities

- ✅ **Multi-LLM Pipeline**
  - Groq (LLaMA 3.3 70B) for skill extraction
  - Google Gemini 2.5 Flash for source discovery with search grounding
  - Groq (GPT-OSS 120B) for question generation

- ✅ **Intelligent Context Handling**
  - **Context-Based**: Uses sourced technical content for deep, specific questions
  - **Context-Free**: Fallback to conceptual/verbal questions when no sources are found
  - **Auto-Detection**: Dynamically switches strategies per skill

- ✅ **Intelligent Processing**
  - **Parallel Batch Processing**: Configurable concurrency for speed
  - **Recursive Batch Splitting**: Automatically splits batches when token limits are exceeded
  - **Token Optimization**: Minimizes API costs while maximizing context

- ✅ **Modern Web Stack**
  - FastAPI with async/await throughout
  - Real-time WebSocket status updates
  - NDJSON streaming for progressive results
  - Responsive UI with accordion-style question display

---

## 🏗 Architecture

### Pipeline Architecture Flow

<div align="center">
  <img src="pipeline_flow.png" alt="AI Interview Prep Pipeline Architecture" width="100%">
</div>

<br>

### Pipeline Stages Breakdown

| Stage | Component | Provider | Concurrency | Purpose |
|-------|-----------|----------|-------------|---------|
| **📥 Input** | `FileValidator` | - | Serial | Validate file (size, type, exists) |
| **📝 Extraction** | `file_text_extractor` | PyPDF | Serial | Extract text from resume PDF |
| **🧠 Skill Analysis** | `LLMService.extract_skills` | Groq LLaMA 3.3 70B | Serial | Identify top 9 technical skills |
| **📦 Batching** | `InterviewPipeline` | - | Serial | Group skills (3 per batch) |
| **🔍 Source Discovery** | `BatchProcessor.discover_sources` | Gemini 2.5 Flash | **Parallel (3x)** | Find Google Search context |
| **💭 Question Generation** | `BatchProcessor.generate_questions` | Groq GPT-OSS 120B | **Parallel (3x)** | Generate interview questions (Context/No-Context) |
| **📊 Streaming** | `event_queue` | FastAPI | Real-time | Stream results via NDJSON |
| **💾 Export** | `download_results` | Local FS | On-Demand | Download results as formatted TXT |

### Key Features

- **⚡Parallel Processing**: 3 batches processed simultaneously (source discovery + questions)
- **Token-Aware Splitting**: Iterative batch splitting when context exceeds safe limits (50K tokens)
- **📊 Real-time Streaming**: Results appear as they're generated (NDJSON + WebSocket progress)
- **🛡️ Error Handling**: 
  - Fast-fail on quota exhaustion (no retries on 429 RESOURCE_EXHAUSTED)
  - Unified retry logic for transient errors (503, 502, rate limits)
  - Fallback to context-free generation when source discovery fails
- **⏱️ Rate Limiting**: Service-specific limits (Gemini: 5 RPM, Groq: 60 RPM)
- **💾 On-Demand Downloads**: Export results to formatted TXT report

---

## 🛠 Tech Stack

### Backend
- **FastAPI** - High-performance async web framework
- **Uvicorn** - ASGI server
- **Pydantic** - Data validation with type hints

### LLM Providers
- **LangChain** - LLM abstraction layer
  - `langchain_groq` - Groq integration (supports both LLaMA and GPT-OSS models)
- **Google GenAI SDK** - Gemini with search grounding

---

## 📦 Installation

### Prerequisites

- Python 3.11+
- API Keys for:
  - [Groq](https://console.groq.com/) (Free tier available - provides both LLaMA 3.3 70B and GPT-OSS 120B)
  - [Google AI Studio](https://makersuite.google.com/app/apikey) (Gemini)

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/ai-interview-prep.git
   cd ai-interview-prep
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# LLM Provider API Keys
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_gemini_api_key
```

### Customization

| Setting | Default | Description |
|---------|---------|-------------|
| `SKILL_COUNT` | 9 | Number of skills to extract from resume |
| `BATCH_SIZE` | 3 | Skills per batch (affects parallelism) |
| `MAX_CONCURRENT_BATCHES` | 3 | Max parallel processing pipelines |
| `SOURCE_DISCOVERY_CONCURRENCY` | 3 | Concurrent source discovery requests |
| `SAFE_TOKEN_LIMIT` | 50000 | Max tokens allowed before recursive batch splitting |
| `MAX_FILE_SIZE_MB` | 10 | Max upload size in megabytes |

---

## 🚀 Usage

### Try the Live Demo

Experience the application running live on Hugging Face Spaces:

👉 **[AI Interview Prep Demo](https://huggingface.co/spaces/Rahma07/AI-questions-gen)**

### Start the Server Locally

```bash
cd ai-interview-prep
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Access the UI

Open your browser to **http://localhost:8000**

### Using the Application

1. **Upload Resume**: Click "Choose File" and select a PDF resume
2. **Start Processing**: Click "Generate Interview Questions"
3. **Real-time Updates**: Watch as the system:
   - Extracts skills
   - Discovers sources (or detects missing context)
   - Generates questions (streamed live)
4. **View Results**: Questions appear in expandable accordions by skill
5. **Download**: Click "Download Results (TXT)" to save a text report

---

## 📡 API Documentation

### Endpoints

#### `POST /api/v1/generate-questions/`

Generate interview questions from a resume.

**Request:**
- **Method**: `POST`
- **Content-Type**: `multipart/form-data`
- **Body**:
  - `resume_file`: PDF file (required)
  - `client_id`: WebSocket client ID (required)

**Response:**
- **Content-Type**: `application/x-ndjson`
- **Format**: Newline-delimited JSON stream

**Example Response Stream:**
```json
{"type":"status","content":"step_1"}
{"type":"status","content":"step_2"}
{"skill":"Python","questions":["Q1","Q2"],"isLoading":false}
{"skill":"Docker","questions":["Q1","Q2"],"isLoading":false}
```

#### `POST /api/v1/download-results`

Download the generated questions as a formatted text file.

**Request:**
- **Method**: `POST`
- **Content-Type**: `application/json`
- **Body**:
  ```json
  {
    "results": [
      {
        "skill": "Python",
        "questions": ["What is GIL?", "Explain decorators..."]
      }
    ],
    "filename": "candidate_resume"
  }
  ```

**Response:**
- **Content-Type**: `text/plain`
- **Header**: `Content-Disposition: attachment; filename="candidate_resume_20251206_120000_results.txt"`

#### `WS /api/v1/ws/{client_id}`

WebSocket endpoint for real-time status updates.

**Events:**
- Status updates during processing
- Progress notifications
- Error messages

---

## 📁 Project Structure

```
ai-interview-prep/
├── app/
│   ├── api/                    # HTTP layer
│   │   ├── v1/
│   │   │   └── interview.py   # Interview endpoints (Generation & Download)
│   │   └── deps.py            # Dependency injection
│   ├── core/                  # Infrastructure
│   │   ├── config.py          # Settings & environment
│   │   ├── llm.py             # LLM client instances
│   │   ├── logger.py          # Logging setup
│   │   ├── websocket.py       # WebSocket manager
│   │   ├── exceptions.py      # Error handlers
│   │   └── prompts.py         # Prompt templates
│   ├── schemas/               # Pydantic models
│   │   └── interview.py       # Data schemas
│   ├── services/              # Business logic
│   │   ├── pipeline/          # Interview pipeline
│   │   │   ├── interview_pipeline.py # Orchestrator
│   │   │   ├── batch_processor.py    # Batch pipeline (Splitting & Context)
│   │   │   ├── llm_service.py        # Direct LLM calls
│   │   │   ├── llm_parser.py         # Response parsing
│   │   │   └── file_validator.py     # File validation
│   │   └── tools/             # Utilities
│   │       ├── extractors.py         # Text extraction
│   │       ├── source_discovery.py   # Gemini search
│   │       ├── helpers.py            # JSON/query helpers
│   │       ├── report_generator.py   # Report formatting (TXT)
│   │       └── rate_limiter.py       # Rate limiting
│   ├── static/                # Frontend assets
│   │   ├── css/
│   │   └── js/
│   ├── templates/             # HTML templates
│   └── main.py                # FastAPI application
├── tests/                     # Test files
├── logs/                      # Application logs
├── .env.example               # Environment template
├── .gitignore                 # Git ignore rules
├── requirements.txt           # Python dependencies
└── README.md
```

### Key Design Patterns

- **Single Responsibility**: Each module has one clear purpose
- **Dependency Injection**: FastAPI's DI system for testability
- **Factory Pattern**: Crew creation deferred until file path known
- **Producer-Consumer**: Event queue for streaming results
- **Strategy Pattern**: Dynamic switch between Batch, Recursive Split, and Context-Free strategies based on input

---

## 🔧 Development

### Code Quality

The codebase follows:
- **SOLID Principles** - Clean architecture with separation of concerns
- **DRY** - Consolidated retry logic, unified error handling, single-pass parsing
- **Type Hints** - Full Pydantic validation and Python type annotations
- **Async/Await** - Non-blocking I/O throughout

### Logging

Logs are written to `logs/app.log` with rotation (5MB max, 5 backups).

**Log Levels:**
- `INFO` - Pipeline stages, API calls
- `WARNING` - Token limit warnings, rate limiting, retries
- `ERROR` - LLM failures, parsing errors

---


## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---


**Built with ❤️ using Python, FastAPI, and cutting-edge LLMs**
