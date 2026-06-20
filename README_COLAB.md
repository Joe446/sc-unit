# Colab Setup for Google Maps Lead Scraper

This folder contains files and a notebook to run the scraper in Google Colab.

Quick steps:

1. Open `Colab_Notebook.ipynb` in Google Colab.
2. Set `SUPABASE_URL` and `SUPABASE_KEY` using the provided cell or add them via `os.environ`.
3. Run installation cells to install dependencies and Playwright browsers.
4. Run the worker cell to start scraping.

Notes:
- Use `HEADLESS=true` in Colab.
- The notebook installs Chromium via `playwright install chromium`.
- If Playwright fails to launch Chromium in Colab, first install required Linux libraries:
  ```bash
  !apt-get update -y
  !apt-get install -y libatk1.0-0 libatk-bridge2.0-0 libcups2 libx11-xcb1 libxcomposite1 libxrandr2 libxdamage1 libxss1 libgconf-2-4 libnss3 libxkbfile1 libgbm-dev
  ```
- The worker writes data directly to Supabase; no local storage is required.
