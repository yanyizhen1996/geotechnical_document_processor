# Document Processor workspace guidance

- [x] Project requirements: Windows-local Python desktop application using PySide6 and SQLite. Microsoft Foundry is the primary provider; OpenAI is optional and policy-gated.
- [x] Project scaffold: use a `src/` Python package layout and `pyproject.toml`.
- [x] Customize the project: initial GUI shell, domain contracts, provider interface, and local SQLite scaffold are in scope.
- [x] Install required extensions: no additional extension is required by this project.
- [x] Compile and validate: dependencies installed and focused tests passed.
- [x] Create and run task: not required for the initial Python package.
- [ ] Launch the project: wait for an explicit launch request before starting the GUI.
- [x] Documentation: README describes setup and Microsoft Foundry API prerequisites.

## Implementation rules

- Do not persist identity tokens, API keys, document content, or raw provider responses in logs by default.
- Implement Microsoft Foundry through approved key-based API integration. Never automate a chat UI or use undocumented endpoints.
- Keep OpenAI separate, explicitly selected, and disabled by policy until enabled.
- Keep each model request limited to one document or a document-local consolidation flow.
