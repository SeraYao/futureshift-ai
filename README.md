# FutureShift AI
### Navigate Change. Shape Your Future.

**Team:** Fishtail  
**Competition:** SDC Hackathon 2026  
**Domain:** A

## Project Overview

FutureShift AI is an AI-assisted career exploration and personalised reskilling platform designed to help students and early-career individuals navigate changes in the future workforce.

The platform combines user profiling, career recommendations, skill-gap exploration, Sustainable Development Goals (SDGs) mapping, and personalised learning plans.

It is designed as a decision-support prototype rather than a recruitment prediction or professional qualification system.

## Live Demo

https://futureshift-ai.replit.app

## Key Features

- Personalised user profiling through an interactive questionnaire.
- Career recommendations based on a predefined occupational dataset.
- Skill-gap exploration and career development guidance.
- SDG-related career exploration.
- Personalised learning plans.
- Optional AI-assisted CV information extraction.

## Technology Stack

- Python
- Streamlit
- GitHub
- Replit
- Optional AI API integration

## How to Run

1. Clone this repository.
2. Install Python 3.11 or newer.
3. Install dependencies:

   pip install -r requirements.txt

4. Start the application:

   python3 -m streamlit run app.py

5. Open the local Streamlit URL.

## Project Structure

- `app.py` — Main application entry point.
- `src/` — Core application modules.
- `docs/` — Technical documentation.
- `tests/` — Automated tests.
- `submission/` — Hackathon submission materials.
- `requirements.txt` — Python dependencies.
- `.replit` — Replit runtime and deployment configuration.

## Replit and RunPod

### Replit

Replit was used to configure, run, test, and publish the Streamlit application.

The application is publicly accessible through the live demo URL above.

### RunPod

The project includes an optional AI-assisted CV extraction workflow designed to communicate with a configurable external AI endpoint.

The core questionnaire, career recommendations, SDG mapping, and learning plans do not require AI credentials.

RunPod integration and deployment details are documented separately where applicable. This README does not claim that a RunPod deployment has been completed or verified.

## Submission Materials

Supporting project documentation is available in the `submission/` directory.

## License

Apache License 2.0.
