---
name: 'General Engineering Standards & Core Behavior'
description: 'Coding conventions and strict behavioral guidelines for full-stack software development'
applyTo: '**'
---

# stridelog conventions

- Follow `docs/PLAN.md`; get approval for each phase's implementation plan.
- Python 3.14+, `src/stridelog` layout, uv and the committed lockfile.
- Keep CLI, API and notebooks thin; put reusable behavior in the package.
- Store SI units and UTC plus the local offset/date. Convert only at boundaries.
- Never log keys, bearer tokens, health data or location data.
- Never commit FIT, ZIP, database, GPX, TCX, exports, credentials or notebook outputs.
- Use synthetic test inputs only; tests must not contact Garmin.
- Default data storage is outside the repository. No ingestion before Phase 1 validation.
- Do not add future-phase dependencies or accept provisional ADRs prematurely.
- Use Ruff, strict Pyright, pytest and the configured privacy hooks.

# 1. Think Before Coding
- **Don't assume; don't hide confusion:** State assumptions explicitly. If requirements are ambiguous or multiple interpretations exist, stop and present them. Don't pick a path silently.
- **When in doubt, ask:** Always ask for clarification before making assumptions about implementation details or requirements.
- **Surface tradeoffs & push back:** If a simpler approach exists, say so. Push back on complex requests when a simpler solution exists.

# 2. Simplicity First
- **Minimum code required:** Implement only what solves the problem. No speculative features, no abstractions for single-use code, and no unrequested "flexibility."
- **The Senior Engineer Test:** Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify. If you write 200 lines and it could be 50, rewrite it.
- **Clean Architecture:** Follow SOLID, DRY, and KISS principles. Keep functions concise (preferably under ~50 lines) and adhere to the single responsibility principle. Avoid deep nesting.

# 3. Surgical Changes (Scope & Safety)
- **Touch only what you must:** Do not modify files outside the `@workspace` folder unless explicitly instructed. Every changed line must trace directly to the user's request.
- **Clean up your own mess only:** Remove imports, variables, CSS classes, or functions that *your* changes made unused. Do not remove pre-existing dead code, and do not "improve" adjacent formatting or comments unless asked.
- **Match existing style:** Preserve existing functionality, interfaces, UI patterns, and code styles, even if you would personally write them differently. Avoid breaking changes.
- **No new dependencies:** Avoid adding new packages or third-party libraries (npm, pip, cargo, etc.) without explicit instruction.
- **Security & Performance:** Validate all user inputs and API parameters. Do not log or hardcode sensitive data (PII, tokens, passwords, secrets). Flag any security issues detected. Avoid deprecated APIs, methods, or components.

# 4. Goal-Driven Execution & Default Agent Behavior
- **Define success criteria:** Transform tasks into verifiable goals (e.g., "Fix the bug" → "Write a test that reproduces it, then make it pass").
- **Generate comprehensive tests:** Cover edge cases, error handling, component states, and expected behavior.
- **Plan multi-step tasks:** For complex changes, state a brief plan with verifiable checks before executing. Always ask for plan approval before executing multi-file changes.
- **Report before fixing:** Report potential bugs or edge cases before suggesting fixes. For refactoring, do not change underlying behavior unless approved.

# 5. Language & Code Quality Standards
- **Idiomatic Style:** Follow the idiomatic style, conventions, and linting standards of the active language and framework (e.g., standard indentation, formatting rules, project lint rules).
- **Typing:** Use explicit, strict type annotations wherever supported by the language (e.g., TypeScript, Python, Rust, Go). Avoid using `any` or ambiguous types without explicit instruction.
- **Documentation:** Write concise, clear documentation (JSDoc, docstrings, API notes) for public functions and complex logic. Minimize token usage by avoiding verbose explanations in the code itself unless requested.
- **Async & Error Handling:** Handle asynchronous operations properly (promises, async/await, status codes, network errors). Ensure consistent error boundaries and fallback states. Do not write error handling for impossible scenarios.
- **No Emojis:** Do not add emojis to any documentation, text, code comments, or commit suggestions you write.
