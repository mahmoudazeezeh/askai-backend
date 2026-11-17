# ASKAI backend

Central API server for **ASKAI**, an 8086 Assembly AI assistant for DOSBox + TASM.
Python standard library only. Health check: `GET /v1/health`.

Provider API keys are **not** in this repository. They are set as environment secrets on
the host (`ASKAI_GEMINI_API_KEY`). Clients receive only their own device token.
