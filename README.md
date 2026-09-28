# Discord Analytics Agent

A professional AI-powered analytics experience for Discord community data. This project combines a conversational agent, SQL-safe query execution, chart generation, and dashboard pinning to help users explore synthetic Discord activity data in plain English.

## Demo

### Video walkthrough

<video controls width="100%" poster="demo/Screenshot%202026-09-28%20132410.png">
  <source src="demo/Discord-Project.mp4" type="video/mp4" />
  Your browser does not support the embedded video tag.
</video>

### Dashboard preview

![Discord Analytics dashboard preview](demo/Screenshot%202026-09-28%20132410.png)

---

## Overview

Discord Analytics Agent is a full-stack analytics application built to let users ask questions about Discord activity without writing SQL. The system uses a natural-language agent, a controlled Postgres data layer, and a plugin-based orchestration model to turn user intent into safe, query-backed insights.

Users can:

- Ask questions in plain English
- Retrieve analytical results from a Discord dataset
- Generate charts from SQL results
- Reuse saved insights through pinned dashboard items
- Explore synthetic data for server, channel, member, and message analytics

---

## Key Features

- AI-powered analytics chat interface
- Read-only database access for safe SQL execution
- Plugin-based agent architecture
- Chart generation from query results
- Session-aware chaining of intermediate results
- Dashboard pinning for reusable insights
- Dockerized deployment for local use
- Synthetic Discord dataset with realistic community metrics

---

## Tech Stack

- Backend: Python, FastAPI
- Database: PostgreSQL
- AI orchestration: OpenAI-compatible LLM integration
- Frontend: HTML, JavaScript, Chart.js
- Containerization: Docker Compose
- Data layer: CSV-based ingestion into Postgres

---

## Architecture

The application follows a simple and extensible pattern:

1. The user submits a question through the frontend.
2. The backend agent interprets the request and identifies the required plugin.
3. The query plugin validates and executes SQL against a read-only database role.
4. If needed, a chart plugin transforms results into a visual representation.
5. The generated insight can be displayed in the UI or pinned to the dashboard.

This design keeps the analytics logic modular and supports future plugin extensions without changing the core orchestration flow.

---

## Project Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── agent/
│   │   ├── api/
│   │   ├── data_access/
│   │   ├── models/
│   │   ├── plugins/
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── errors.py
│   │   ├── logging_mw.py
│   │   └── main.py
│   ├── scripts/
│   ├── tests/
│   └── requirements.txt
├── data/
├── demo/
│   ├── Discord-Project.mp4
│   └── Screenshot 2026-09-28 132410.png
├── frontend/
├── docker-compose.yml
├── README.md
├── .env.example
└── .gitignore
```

---

## Prerequisites

Before running the project, make sure you have:

- Docker installed
- Docker Compose available
- An OpenAI API key

---

## Run Locally

### 1) Configure environment

Create the environment file and add your OpenAI key:

```bash
cp .env.example .env
```

Then set:

```env
OPENAI_API_KEY=your_api_key_here
```

### 2) Start the application

```bash
docker compose up --build
```

### 3) Access the app

Once the containers are healthy, open:

- Frontend: http://localhost:8080
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### 4) Reset or reload data

To rerun the migration/data load step:

```bash
docker compose run --rm migrate
```

To perform a full clean reset:

```bash
docker compose down -v
docker compose up --build
```

---

## Security and Safety

The project includes practical safeguards suitable for a demo and development environment:

- Read-only database role for agent-driven queries
- SQL validation before execution
- Row limits to prevent oversized result sets
- Session locking to avoid overlapping chat turns
- Sanitized frontend rendering for generated output

These measures improve safety without sacrificing the flexibility needed for AI-driven analytics demos.

---

## Dataset

The project uses a synthetic Discord dataset containing:

- server metadata
- channel information
- member activity and profile data
- daily aggregate statistics
- message samples and community activity trends

This allows realistic analytics scenarios without using private user data.

---

## Use Cases

This application is well suited for:

- community analytics dashboards
- Discord engagement reporting
- activity trend analysis
- AI-assisted business intelligence demos
- data exploration with natural-language interfaces

---

## License

This project is intended for demonstration and evaluation use. Review the repository and data terms before using it in public or commercial contexts.

---

## Summary

Discord Analytics Agent delivers a polished AI analytics workflow: natural-language requests, controlled database access, generated charts, and saved dashboard insights. The included demo video and screenshot highlight the real user experience and demonstrate the value of the platform.
