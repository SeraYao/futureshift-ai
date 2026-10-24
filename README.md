# futureshift-ai
AI-powered future workforce intelligence and personalised reskilling platform for SDC Hackathon 2026.

## Run on Replit

Import this GitHub repository into Replit and run the app. `.replit` starts Streamlit on `0.0.0.0:8501` and maps the web port. The pinned packages require Python 3.11 or newer; Replit should use a compatible Python runtime and install `requirements.txt`.

The questionnaire, official career recommendations, local SDG mappings, and learning plans work without AI credentials. Optional CV extraction requires these Replit Secrets: `AI_BASE_URL`, `AI_MODEL`, and `AI_API_KEY`. `AI_TIMEOUT_SECONDS` is optional and measured in seconds (default 300; accepted range 1–3600). Never commit Secrets or place them in source files.

Deployment steps, privacy boundaries, and current limitations are in [submission/README.md](submission/README.md).
