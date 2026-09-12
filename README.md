# Northstar — Career Intelligence Assistant

Northstar is my implementation of Option 4, the Career Intelligence Assistant. It compares one resume with multiple job descriptions, separates required from additional qualifications, explains strengths and gaps, prepares interview questions, and answers grounded follow-up questions.

The stack is React + TypeScript, FastAPI, PostgreSQL, and an optional Google Gemini enrichment layer. The deterministic analyzer remains available when Gemini is disabled or unavailable.

## Quick setup with Docker

Prerequisite: Docker Desktop, or Docker Engine with Compose.

```bash
docker compose up --build
```

Open:

- Application: `http://localhost:5173`
- FastAPI documentation: `http://localhost:8000/docs`
- Health endpoint: `http://localhost:8000/api/health`

The application works without an LLM key. To enable hybrid semantic analysis:

```bash
cp .env.example .env
```

Set the following in `.env`, then rebuild:

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash
LLM_ENABLED=true
```

```bash
docker compose up --build
```

The Gemini key is used only by FastAPI. It must never be added to frontend code or committed. `.env` is excluded by `.gitignore`.

Run the automated backend tests in the dependency-complete container:

```bash
docker compose run --rm --no-deps backend python -m unittest discover -s backend/tests -v
```

PostgreSQL data is retained in the `career_postgres` Docker volume. Stop the application without deleting its data using:

```bash
docker compose down
```

### Local development without Docker

Prerequisites: Python 3.12, Node.js 20+, and a running PostgreSQL instance.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

docker compose up -d postgres
cd frontend
npm install
npm run dev:full
```

For this workflow, configure the backend database connection and frontend API URL if they differ from the defaults:

```env
DATABASE_URL=postgresql+psycopg://career:career@localhost:5432/career
CORS_ORIGINS=http://localhost:5173
VITE_API_URL=http://localhost:8000/api
```

## Product workflow

1. Upload a PDF, DOCX, or TXT resume, up to 8 MB.
2. Add, edit, or delete job descriptions. Deletion requires confirmation and also removes the role's saved analysis.
3. Analyze one selected role or all roles together.
4. Review the score, required and additional qualification counts, strengths, gaps, and next steps.
5. Open Insights for individual qualification results and Preparation for tailored interview questions.
6. Ask grounded questions about fit, missing skills, strengths, or interview preparation.

Replacing the resume resets the analyses shown in the UI. Editing a job invalidates that job's stored analyses.

## Screenshots

![Northstar desktop dashboard](docs/screenshots/dashboard-desktop.png)

![Northstar mobile dashboard](docs/screenshots/dashboard-mobile.png)

## Architecture

```mermaid
flowchart LR
  Browser[React + TypeScript] -->|JSON / multipart| Nginx[Nginx]
  Nginx --> API[FastAPI]
  API --> Parser[PDF / DOCX / TXT parser]
  API --> Rules[Deterministic analyzer]
  Rules --> Hybrid[Hybrid scoring]
  Hybrid -. optional structured request .-> Gemini[Google Gemini]
  API --> DB[(PostgreSQL)]
  API --> Browser
```

- `frontend/src/main.tsx` implements the typed user workflow and API integration.
- `backend/main.py` provides validated API endpoints and persistence.
- `backend/parser.py` extracts resume data and cleans job adverts. It removes common boilerplate and separates required and preferred sections, including LinkedIn text where headings and bullets are concatenated.
- `backend/analyzer.py` performs explainable skill, qualification, experience, and role-family analysis.
- `backend/hybrid_analyzer.py` optionally adds Gemini semantic evidence and interview questions.
- `backend/database.py` defines the SQLAlchemy models stored in PostgreSQL.

Nginx serves the production frontend and proxies `/api` requests to FastAPI. Docker Compose starts the frontend, backend, and PostgreSQL with health checks. Uploaded files are parsed through temporary files and deleted immediately; extracted text and analysis results are stored in PostgreSQL.

## Matching approach and technical decisions

I started with a simple rule-based approach so the scoring would be transparent and the core app would still function even if Gemini wasn't available. Then, I layered Gemini on top because exact keyword matching often fails to catch related or transferable experience.

The rule-based analyzer works like this:
- It standardizes a list of technical and professional skills.
- It cleans the job descriptions, stripping out things like company marketing, compensation details, and equal-opportunity boilerplate.
- It separates the absolute "must-have" requirements from the "nice-to-have" ones.
- Required skills are weighted double compared to optional ones.
- It evaluates concrete qualifications like technologies, education, and years of experience by matching resume evidence with the job's responsibilities.
- Importantly, it checks if the role type itself is a match (e.g., just knowing Python shouldn't make a full-stack dev a perfect fit for an IT support role).

When objective details are present, the rule-based score breaks down into 35% skill alignment, 25% experience alignment, and 40% qualification coverage. A role only gets the "Job matches" badge if it scores over 50%.

When the Gemini integration is active, it steps in to find the nuanced, semantic evidence that strict rules might miss. The final score is then calculated using 70% rule-based analysis and 30% Gemini analysis. As before, required evidence carries twice the weight of preferred evidence, and the same role-type logic applies.

Ultimately, this score is just a helpful guide, not a definitive hiring decision. It relies strictly on the provided text and avoids guessing about undocumented experience or personal traits.

## RAG and LLM decisions

### Implemented now

- **LLM:** Google Gemini, defaulting to `gemini-2.5-flash`, through the `google-genai` Python SDK.
- **Embeddings:** none. The current dataset is one resume and a small number of job descriptions, so sending bounded cleaned text is simpler than building full retrieval infrastructure.
- **Vector database:** none. PostgreSQL currently stores relational records and JSON analysis results; pgvector is not installed.
- **Orchestration:** plain Python functions. The workflow is small enough that an orchestration framework would add complexity without a clear benefit.
- **Prompt and context management:** resume and cleaned job text are placed in separate XML-style delimiters and capped at 18,000 characters each. Job boilerplate is removed before the model call.
- **Structured output:** Gemini is constrained by Pydantic response schemas for evidence, missing required/preferred skills, summaries, and interview questions.
- **Guardrails:** document content is explicitly treated as untrusted data; the prompt prohibits following document instructions and inferring employers, qualifications, experience, or protected characteristics. Every model-provided resume quotation must occur verbatim in the uploaded resume or it is rejected.
- **Fallback:** a missing key, disabled LLM, provider failure, or invalid response returns the deterministic result rather than breaking the workflow. `analysisMode` and `llmStatus` make this visible in the API response.

The follow-up Q&A endpoint currently uses grounded, deterministic response templates over the analysis rather than a separate generative chat call. This keeps answers predictable but limits conversational flexibility.

### Production RAG direction

For a production version with many documents or long career histories, I would split documents into section-aware chunks, generate versioned embeddings, and store them in PostgreSQL with pgvector. PostgreSQL full-text search would retain exact technology matching. Hybrid retrieval would select and rerank relevant evidence before calling the model, and each claim would include a document identifier, section, and character offsets.

I would add an offline evaluation dataset covering explicit skills, synonyms, transferable experience, must-have versus preferred classification, unsupported claims, malformed documents, and score calibration. Retrieval recall, citation correctness, groundedness, latency, provider errors, token usage, and cost would become release and operational metrics.

## Productionising on AWS

I would deploy the built React assets to a private S3 bucket behind CloudFront. FastAPI would run as a non-root container on ECS Fargate behind an Application Load Balancer. RDS PostgreSQL would use encryption, automated backups, private subnets, and pgvector when retrieval is introduced.

Large documents would upload directly to a quarantined S3 bucket with pre-signed URLs. S3 events and SQS would trigger an asynchronous parsing, malware-scanning, and indexing worker. Cognito would provide authentication, Secrets Manager would store database and Gemini credentials, and AWS WAF would add edge protection and rate controls.

CloudWatch and OpenTelemetry would collect structured logs, metrics, traces, alarms, model latency, fallback rates, and cost metadata without recording raw resume content. Infrastructure would be defined with Terraform or AWS CDK and deployed through a staged CI/CD pipeline.

Before production release I would also add:

- Tenant ownership and authorization on every record.
- Alembic database migrations.
- Retention, deletion, and data-export workflows.
- Idempotency keys, retry policies, pagination, and background processing.
- Antivirus scanning and stronger file-content validation.
- Model safety evaluations and prompt/version tracking.
- Accessibility testing and a full privacy/security review.

## Engineering standards

Implemented standards include typed TypeScript models, Pydantic request and model-response validation, parameterised SQLAlchemy access, upload size and extension limits, temporary-file cleanup, configurable CORS, server-side secret handling, non-root backend containers, health checks, reproducible frontend installs with `npm ci`, and user-safe API errors.

The code is separated by responsibility across parsing, deterministic analysis, LLM enrichment, persistence, API routes, and presentation. The application degrades gracefully when Gemini is unavailable.

Automated unit tests cover LinkedIn-style job parsing, boilerplate removal, required/preferred qualification scoring, support-role safeguards, and deterministic fallback when no Gemini key is configured. Standards I did not complete within the take-home scope include API integration/browser tests, CI enforcement, Alembic migrations, authentication, full accessibility testing, dependency scanning, and production observability. I would prioritise API tests, browser tests, and migrations before adding more product features.

## AI-assisted development

I relied on an AI coding assistant while building this project. I used it to review the initial starter files, help wire up the React frontend to the FastAPI backend, and troubleshoot some build errors along the way. I made sure to review its suggestions before accepting them, and tested the analyzer with real-world examples rather than just taking its first pass at the logic.

The most valuable part of using the AI was when things didn't quite look right. For instance, I noticed a LinkedIn Python advert wasn't splitting bullet points correctly, and a support role highlighted that matching tech keywords doesn't necessarily equal matching job experience. I fed these examples back into the assistant to help refine the parsing for required vs. preferred qualifications, strip out more advert boilerplate, and implement the role-type safety checks.

## What I would do differently with more time

If I were to start this over, I would definitely create a small suite of expected resume and job outcomes before trying to tune the scoring algorithm. Doing this would make it much easier to spot scoring issues across the board and prevent me from over-optimizing for just one example.

With more time on my hands, I’d love to improve the PDF extraction process, pinpoint the exact sentence from the resume that generated a match, and cache the analysis results to speed up follow-up questions. I'd also focus on adding more comprehensive API and browser tests, setting up GitHub Actions for CI, adding proper database migrations, tracking analysis history, and allowing users to upload job files directly in the UI. Lastly, if the document collection grew significantly, I'd implement a proper RAG setup with pgvector retrieval.
