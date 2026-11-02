# Raj Yadav
**Python Backend & Applied AI Engineer**

rajydv141@gmail.com | Mumbai, India | [Portfolio](https://privateraj18110.github.io/) | [GitHub](https://github.com/PrivateRaj18110)

MBA Tech (Finance) and Computer Engineering graduate from NMIMS Mumbai. I build end-to-end Python systems: FastAPI services, LLM-powered automation, event-driven platforms on Docker and Kubernetes, and rigorous quantitative research pipelines. Internships at Tata Capital and NTPC taught me the business side that the code serves. I build with AI coding agents (Claude Code, Codex) and own the design, review and verification of everything I ship.

## How I Build
I build with AI coding agents. I decide what to build and how it should work, the agents write most of the code, and nothing ships until I have reviewed it and tests, evaluations or audits back it up.
*Tools: Claude Code, Codex, Ollama*

## Technical Skills
- **AI & Automation**: LLM APIs, RAG, Open-source LLMs (Ollama), AI coding agents, Prompt Engineering, Playwright, Machine Learning
- **Backend & Data**: Python, FastAPI, SQL, PostgreSQL, Redis, pandas, DuckDB
- **Cloud & DevOps**: Docker, Kubernetes, AWS, Google Cloud, GitHub Actions, Git & GitHub, Prometheus & Grafana, Linux
- **Systems & Frontend**: C++20, CMake, React, TypeScript
- **Finance & Business**: Advanced Excel & Pivot Tables, Power BI, ERP (Oracle Fusion, SAP), Power Apps & Power Automate, Budgeting & Forecasting, Market Research

## Key Projects

### Algo Matrics Platform
*Tech Stack: Python, FastAPI, PostgreSQL, Redis, Docker, Kubernetes, AWS, Google Cloud, Prometheus & Grafana, GitHub Actions, React, TypeScript, LLM APIs, AI coding agents*
Live: [https://algomatrics.in](https://algomatrics.in)
- Multi-tenant algorithmic trading platform: strategies, brokers, risk controls, billing, real-time P&L and a full operations stack in one console.
- SaaS core: plans and billing through Razorpay / Stripe with GST, broker connections (Zerodha, Angel One, Flattrade, paper trading), risk limits and kill switches.
- Strategy SDK with sandboxed uploads, semantic versioning, an approval workflow, and backtesting with bar replay, Monte Carlo and walk-forward.
- Clean Architecture / DDD monorepo with 152 commits, deployable with one Docker Compose command or on Kubernetes.

### Research Copilot (RAG + open-source LLM)
*Tech Stack: RAG, Open-source LLMs (Ollama), Python, Prompt Engineering, Qwen2.5, nomic-embed-text, BM25, NumPy, FastAPI, AI coding agents*
- Retrieval-augmented generation over 299 of my own project documents, answered by Qwen2.5 running locally with Ollama, with every answer sentence checked against its source.
- Hybrid retrieval (BM25 + 768-dimensional dense embeddings, fused with reciprocal rank fusion) over 5,126 heading-aware chunks.
- Measured on a labelled question set: retrieval hit@5 100%, MRR 0.708, and 2/2 out-of-scope questions correctly refused.
- Grounding check: each answer sentence is cited to the passage it came from, and sentences no passage supports are flagged; on average 92% of an answer's sentences were grounded, and both sentences it flagged in the evaluation were genuinely unsupported.
- Runs fully offline on a 4-core laptop CPU: no data leaves the machine, and secrets are redacted before indexing.

### StudyPilot
*Tech Stack: React, TypeScript, PostgreSQL, Supabase, Vite, Tailwind CSS, PWA, AI coding agents*
Live: [https://studypilot-biw.pages.dev](https://studypilot-biw.pages.dev)
- Learning website for Class 7 students: short lessons, practice with hints, unit tests and timed practice papers. Live as a prototype.
- Follows 9 school textbooks across 7 subjects: 256 topics, 219 lessons and 1,232 practice questions, all marked as drafts until a teacher reviews them.
- Timed practice papers that save every answer, resume after a refresh and submit exactly once at the deadline.
- Offline-first PWA: finished work goes into a durable IndexedDB outbox with idempotency keys.

### NIFTY / SENSEX Intraday Research Lab
*Tech Stack: Python, pandas, Machine Learning, Linux, AI coding agents*
- Research workspace for intraday NIFTY / SENSEX trading: candle engines, feature and event discovery, walk-forward model tests and a paper-trading runtime.
- Confidence-driven entry / exit research with walk-forward out-of-sample reporting, random baselines and cost sweeps.
- Feature, event and edge discovery engines with FDR and Holm multiple-testing control.
- Paper-trading runtime on a Linux server with a safety preflight before broker login.

### LLS: Low-Latency Trading Infrastructure
*Tech Stack: C++20, CMake, Python, Machine Learning, AI coding agents*
- C++20 platform for market-data ingestion, incremental feature computation, ML inference and risk / execution infrastructure.
- Lock-free SPSC ring-buffer pipeline from feed to a preallocated market-state engine with zero-copy snapshots.
- C++ ML stack: purged walk-forward splits, leakage detection, tree ensembles, TCN / CNN1D models, calibration and a zero-allocation inference engine.
- Differential oracle proving the C++ port reproduces a legacy Python strategy exactly; 214 C++ source files and 98 test files.

### RQIE: Quant Intelligence Engine
*Tech Stack: Python, pandas, DuckDB, Machine Learning, AI coding agents*
- Offline research engine with pre-registered experiments and a verified data store for NSE stock and option captures.
- Pre-registered experiments on option-quote imbalance across 27 sessions, reporting a consistent but economically negligible effect honestly.
- Gated data build with per-session verification and an independent DuckDB store audit.
- Execution-economics attribution with a versioned cost model and delay stress tests; read-only by design with no broker capability.

### Audio / Visual Summarization
- Summarizes audio and video content to make information retrieval faster.
- Won third place at the Saavishankar competition, 2024.

## Experience
- **Tata Capital Housing Finance (TCHFL) | Management Intern** (May 2024 – Jul 2024)
  - Automated MIS reports and built dashboards for senior management.
  - Audited P&L statements from GL files in Excel and analyzed key financial performance metrics and trends.
  - Benchmarked data against competitors and helped develop a CAPAD calculator to estimate total money saved on loans over the loan period.
- **NTPC Ltd. | Technical Intern** (May 2023 – Jul 2023)
  - Analyzed energy trade patterns in Power BI and SAP to evaluate a potential demerger of the renewable and coal businesses.
  - Contributed to the team's final report, after which the demerger idea was dropped.

## Education
- **MPSTME, NMIMS Mumbai** (2025)
  MBA Tech: B.Tech Computer Engineering + MBA (Finance major, Business Intelligence & Analytics minor) | CGPA 2.65 / 4

## Certifications & Achievements
- Trading Algorithms, Indian School of Business (Coursera)
- Advanced Trading Algorithms, Indian School of Business (Coursera)
- Investment and Portfolio Management, Rice University
- Crash Course on Python, Google
- Learn Python 3, Codecademy
- Winner, Smart India Hackathon 2022
- Finalist, Startup India: India's Social Impact Champion 2023
- Third place, audio/video summarization, Saavishankar competition 2024

## Personal
- Date of birth: 08/04/2002
- Interests: Chess, Reading, Cycling
