# Energy News Tracker — India Large Consumers

Tracks daily news on tariffs, open access/renewable procurement, regulatory
changes, and grid reliability affecting large power consumers in India.
Runs automatically every day via GitHub Actions, writes a Markdown digest
into `digests/`, and (optionally) emails it to you.

## How it works

1. `config.json` defines your **topics**, each with a list of search terms
   and a weight. This is the only file you'll usually need to edit.
2. `energy_news_tracker.py` pulls recent articles per term from Google News
   RSS, drops duplicates and anything you've already seen in the last 14
   days, groups everything by topic, and writes `digests/YYYY-MM-DD.md`.
3. A GitHub Actions workflow (`.github/workflows/daily-digest.yml`) runs
   the script every day at 7:00 AM IST, commits the new digest to the repo,
   and sends it by email if you've configured SMTP secrets.

## One-time setup (about 10 minutes)

1. **Create a GitHub repo.** Go to github.com → New repository → name it
   something like `energy-news-tracker` → keep it private if you prefer.
2. **Upload these files** to the repo, preserving the folder structure
   (the `.github/workflows/` folder must stay exactly as-is).
3. **(Optional but recommended) Set up email delivery:**
   - If using Gmail: turn on 2-Step Verification, then create an
     [App Password](https://myaccount.google.com/apppasswords).
   - In your repo, go to **Settings → Secrets and variables → Actions →
     New repository secret**, and add three secrets:
     - `SMTP_USER` — your Gmail address
     - `SMTP_PASS` — the 16-character app password (not your normal password)
     - `EMAIL_TO` — the address you want the digest sent to
   - If you skip this step, the workflow will still run and save digest
     files to the repo — it just won't email you.
4. **Enable Actions.** Go to the **Actions** tab in your repo and enable
   workflows if prompted.
5. **Test it immediately** rather than waiting for 7 AM: Actions tab →
   "Daily Energy News Digest" → **Run workflow**. Check `digests/` for the
   new file, and check your inbox if you set up email.

## How to "polish" the targeting over time

Everything you'll want to tune lives in `config.json` — you don't need to
touch the Python script:

- **Too much noise in a topic?** Add the offending word/phrase to
  `exclude_terms`.
- **Missing a specific angle** (e.g. a state you care about, a sector like
  steel or data centers)? Add a new search term under the relevant topic,
  or add a whole new topic block.
- **Want a topic to rank higher / show more results?** Raise its `weight`
  or `max_articles_per_topic`... note: `max_articles_per_topic` is currently
  global; move it into a topic block if you want per-topic limits later.
- **Getting stale/duplicate stories day to day?** That's handled
  automatically — `seen.json` remembers article titles for 14 days so
  the same story won't repeat once it's been in a digest.

After editing `config.json`, just commit and push — the next scheduled
run (or a manual "Run workflow") will use the new settings.

## Running it locally (to test before relying on the cloud schedule)

```bash
pip install -r requirements.txt
python energy_news_tracker.py
```

This will fetch live articles and write to `digests/`, using today's date.
Set `SMTP_USER` / `SMTP_PASS` / `EMAIL_TO` as environment variables first
if you want to test email locally too.

## Known limitations / next steps to consider

- Uses Google News RSS as the source, which aggregates most Indian energy
  publications (Mercom India, Power Line, ET Energyworld, Business
  Standard, etc.) but isn't exhaustive. If you find a specific source that
  matters to you and has its own RSS feed, it's easy to add a dedicated
  fetch for it alongside the keyword search — ask if you want this added.
- No AI-based relevance scoring yet — filtering is keyword-based. A
  natural next step, once you've used this for a couple of weeks, is
  adding a scoring pass (e.g. via the Claude API) to rank articles by
  actual relevance rather than just keyword hits.
- Digest is grouped by topic but not deduplicated *across* topics beyond
  the current run (an article matching two topics' keywords will only
  appear once, under whichever topic fetched it first).
