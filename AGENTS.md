# Agent Guidelines

- Keep changes focused on the requested task.
- Do not run automated tests unless the user explicitly asks you to.
- Do not start, restart, or stop a development server unless the user explicitly asks you to.
- Before considering starting a server, check whether the app is already available on port 8000. The user normally runs a local server there; use that existing server when appropriate.
- Do not regenerate, replay, or otherwise rewrite all past races unless the user explicitly asks you to.


When doing UX work
- Avoid using H2s with generated text, a single H1 reflective of prompt instruction is perfect