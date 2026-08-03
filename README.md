# Xtra + SSR (Based on 10KG)

A Streamlit app for Airblue Passenger List and CFP (flight plan) data extraction.

## What it does

- **Passenger List parsing** — paste (or upload) the SSR-ticked Passenger List copied
  straight from the Airblue system. The app extracts:
  - FC = EX (fare class) passenger count
  - SSR-based extra baggage units (XB10 = 1, XB20 = 2, XB30 = 3)
  - Report totals: Travel Load (USED), Allowance, Total Weight, Avg KG per Passenger
- **CFP parsing** — attach a CFP `.txt` flight plan file to pull:
  - EST TOGW, Payload, BLK FUEL, W/C, ALT STN (falls back to ALT STN 2 if ALT STN 1 is empty)
- **Final Summary** — a combined, copy-paste-ready row of all the above values in a
  fixed sequence, ready to paste into your downstream form/sheet.

## Files

- `xtra_ssr_app.py` — the Streamlit app
- `requirements.txt` — Python dependencies

## Deploying

### Option A: Streamlit Community Cloud (recommended, free)

1. Create a new GitHub repo and push these two files to it:
   ```bash
   git init
   git add xtra_ssr_app.py requirements.txt README.md
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git push -u origin main
   ```
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. Click **New app**, select your repo/branch, and set the main file path to
   `xtra_ssr_app.py`.
4. Click **Deploy**. Streamlit Cloud installs `requirements.txt` automatically and
   gives you a public URL. Every push to `main` auto-redeploys.

### Option B: Run locally

```bash
pip install -r requirements.txt
streamlit run xtra_ssr_app.py
```

## Notes

- GitHub itself (including GitHub Pages) can only serve static files — it cannot run
  a Python/Streamlit app on its own. GitHub is just where the code lives; Streamlit
  Community Cloud (or another Python host) is what actually runs it.
