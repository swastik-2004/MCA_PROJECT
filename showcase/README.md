# Showcase run

`llm_run/report.html` is a saved run in which the LLM (GPT-OSS-120B via Groq) designed a level from
the player reviews and the LLM agents optimised it. CI has no API key, so the website build
(`scripts/build_site.py`) uses this saved run for level 3 of the game ("AI-DESIGNED").

To refresh it: run `python run_demo.py --out outputs_llm` with your key in `.env`, then copy
`outputs_llm/report.html` to `showcase/llm_run/report.html`.
