# Master Resume - Source of Truth
# Applicant: Alex Rivera

NAME: Alex Rivera
TITLE: Senior Quantitative Systems & Machine Learning Engineer
EMAIL: alex.rivera.dev@example.com
PHONE: +1-555-0199
LINKEDIN: https://www.linkedin.com/in/alexrivera-dev
GITHUB: https://github.com/alexrivera-dev
PORTFOLIO: https://alexrivera.dev

## EDUCATION
- **University of California, Berkeley** (2024)
  B.S. in Computer Science & Applied Mathematics | GPA: 3.91 / 4.00
- **Relevant Coursework**: Distributed Systems, Operating Systems, High-Performance Computing, Machine Learning, Stochastic Processes, Low-Latency System Design

## TECHNICAL SKILLS
- **Programming Languages**: Modern C++ (C++17/20), Python, SQL (PostgreSQL, TimescaleDB), Rust, Bash
- **High-Performance & Low-Latency**: Numba (JIT `@njit`), SIMD Vectorization, Lock-free SPSC/MPMC Ring Buffers, Linux Kernel Tuning, Multithreading (std::thread, pthread), ZeroMQ, Socket Programming
- **Quantitative & Broker APIs**: MetaTrader 5 (MT5 Python API), FlatTrade Broker API, Interactive Brokers API, FIX Protocol, WebSocket Market Feeds, Order Management Systems (OMS)
- **Data & Numerical Computing**: NumPy, Pandas, SciPy, PyTorch, Scikit-learn, Ray, Polars
- **Cloud & DevOps**: Linux/Unix, Docker, Kubernetes, Git, CMake, GCC/Clang, CI/CD, AWS

## PROFESSIONAL EXPERIENCE
- **AlphaPulse Quantitative Capital | Quantitative Systems Engineer** (2024 – Present)
  - Architected an ultra-low-latency C++20 order routing and execution engine achieving sub-50 microsecond tick-to-trade dispatch latency.
  - Implemented lock-free circular memory buffers and cache-conscious data structures to eliminate thread contention.
  - Built automated failover mechanisms across redundant broker gateways, handling millions of daily market transactions.

- **Vertex AI Research Labs | Machine Learning Engineering Intern** (2023 – 2024)
  - Developed deep learning Computer Vision and temporal sequence models for real-time anomaly detection.
  - Optimized neural network inference latency by 4x using TensorRT and custom CUDA / C++ extensions.
  - Scaled distributed data ingestion pipelines across multi-GPU clusters using PyTorch and Ray.

## KEY PROJECTS
- **Low-Latency C++ Execution Engine**
  *Tech Stack*: Modern C++ (C++20), POSIX Sockets, Lock-Free Queues, Linux, CMake
  - Designed and deployed a modular multi-venue execution engine with deterministic latency profiles.
  - Integrated custom binary protocol parsers and automated order lifecycle state machines (New, Ack, Fill, Cancel).

- **Numba-Accelerated Quantitative Strategy Engine**
  *Tech Stack*: Python, Numba JIT, NumPy, SciPy, PostgreSQL
  - Engineered high-throughput signal generation pipeline utilizing Numba `@njit` kernels for parallel tick processing.
  - Accelerated vectorized backtesting and Monte Carlo risk simulations over multi-gigabyte L2/L3 order book datasets.

- **Unified Multi-Broker API Gateway (MetaTrader 5 & FlatTrade)**
  *Tech Stack*: Python, MetaTrader 5 API, FlatTrade API, WebSockets, Asyncio, Redis
  - Built unified asynchronous trading gateway interfacing with MetaTrader 5 and FlatTrade.
  - Automated dynamic position sizing, continuous trailing-stop algorithms, and real-time portfolio margin monitors.

## CERTIFICATIONS & ACHIEVEMENTS
- Certified Kubernetes Application Developer (CKAD)
- AWS Certified Solutions Architect
- Top 1% Competitive Programming Rank (LeetCode & Codeforces)
