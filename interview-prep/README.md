# Interview Preparation Pack

This folder is based on the current repository implementation. It is intentionally honest: it explains what works, what is protected, and what is not implemented.

## Start here

- [Short answers](short-answers.md): fast revision and interview-safe wording.
- [Full technical report](full-technical-report.md): architecture, execution flow, file responsibilities, critical code, trade-offs, and weaknesses.
- [Failure and security review](failure-security-review.md): hostile test cases, severity, current behavior, and fixes.
- [Questions and walkthrough](questions-and-walkthrough.md): plugin questions, 80 repository-specific questions, live walkthrough, and "why this way?" answers.
- [Defense sheet](defense-sheet.md): strongest decisions, weakest areas, key files/functions/concepts, and claims to avoid.

## How to use this

1. Memorize the short answers.
2. Use the full report to understand the reasoning behind each answer.
3. Practice the live walkthrough aloud.
4. For weaknesses, say what the current code does first, then explain how you would improve it.

## Core positioning

This is a well-separated local analytics application with meaningful SQL and database safety controls. It is not a production multi-tenant service: authentication, authorization, rate limiting, durable chat state, bounded memory, and complete automated tests are not implemented.

## Repository scope

The preparation material covers:

- FastAPI routes and SSE chat streaming
- Agent loop and provider abstraction
- OpenAI tool calling
- Plugin discovery and registration
- Pydantic argument validation
- Query and chart plugins
- SQL AST validation
- PostgreSQL roles and schema
- Artifact references and pin replay
- Frontend rendering and frontend risks
- Configuration, Docker, loading, logging, and error handling
- Failure modes, security, trade-offs, and interview questions

No application source code was changed while creating this folder.
