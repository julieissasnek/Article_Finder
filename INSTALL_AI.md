AI Setup (choose one)

Option A — Gemini API (recommended if you already have a key)
- Export the key in your shell:
    export GEMINI_API_KEY=YOUR_KEY
- Re-run the app or installer.

Option B — OpenAI API
- Export the key in your shell:
    export OPENAI_API_KEY=YOUR_KEY
- Re-run the app or installer.

Option C — Local Ollama (no cloud keys)
- Install Ollama
- Run:
    ollama pull mistral
    ollama serve

Notes
- Installers do not force any provider.
- If no AI is configured, extraction may produce "no_findings" but the app will still run.
