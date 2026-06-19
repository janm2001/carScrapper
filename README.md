# EV Deal Scout

A local web app for finding used electric car listings in a 5,000-12,000 EUR budget range, ranking them by price and kilometers, and estimating a negotiation opening.

The scraper adapters are deliberately polite: they fetch public pages/APIs, detect CAPTCHA or rejected requests, and report that status instead of trying to bypass protection.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000`.

## Notes

- Njuškalo and Index Oglasi can block server-side scraping. When that happens the app shows the source status and keeps working with cached/manual data.
- Scores are comparative within the current result set. Battery health, service history, import status, registration, and warranty still matter before negotiating.
