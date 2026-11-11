# MezmurFaith Daily Verse Bot

Every day at **7:00 AM Chicago time** this bot:

1. Picks the next verse from `verses.json`.
2. Has OpenAI draw a charcoal/pencil illustration (no text in the drawing).
3. Adds the Tigrinya verse (first, larger), the English verse, both references and the logo, using real fonts.
4. Posts it to Instagram with the caption: Tigrinya → English → hashtags.
5. Saves the day's verse to `docs/api/today.json` (and `history.json`) for the MezmurFaith app.

It runs on GitHub Actions. Your computer can be off.

---

## The Tigrinya rule

- Tigrinya text comes **only** from `verses.json`, typed or copied from a verified Tigrinya Bible.
- The bot never generates, translates or "fixes" Tigrinya. It copies it exactly.
- A verse with missing Tigrinya, or Tigrinya that contains no Ge'ez letters, is **skipped**, never posted.
- Tigrinya references use the Tigrinya book names and the ፥ separator, e.g. `ዳዊት 23፥1`.

---

## Adding verses

Open `verses.json` (on GitHub: click the file, then the ✏️ pencil icon). Copy an entry, paste it after the last one, add a comma between entries, and change the values:

```json
  {
    "id": "john-3-16",
    "english_text": "For God so loved the world, that he gave his only begotten Son…",
    "english_ref": "John 3:16",
    "tigrinya_text": "PASTE THE VERIFIED TIGRINYA HERE",
    "tigrinya_ref": "PASTE THE TIGRINYA REFERENCE HERE",
    "scene_prompt": "a short description of the drawing, e.g. the cross on a hill at dawn",
    "posted": false,
    "posted_date": null
  }
```

- `id`: lowercase English letters, numbers and dashes only. Must be unique.
- `scene_prompt`: describe the scene only. Don't ask for any words or text in the drawing.
- `posted`: keep it `false`. The bot sets it to `true` after posting.
- Verses are posted in the order they appear in the file.

When you save (commit) on GitHub, the **Check verses** workflow runs automatically. If you made a mistake (missing comma, duplicate id, missing Tigrinya), you'll get an email saying it failed. Open it to see which verse has the problem.

---

## Settings (`config.json`)

| Setting | What it does |
|---|---|
| `hashtags` | Hashtags at the end of every caption (Instagram allows at most 30) |
| `post_time` | Earliest posting time each day, Chicago time (`"07:00"`) |
| `require_approval` | `true` = only post posters you approved with **Preview week**. `false` = post automatically |
| `label_ai_generated` | `true` = tell Instagram the image was made with AI (shows an "AI info" label) |

If you change `post_time`, also update the two `cron` lines in `.github/workflows/daily.yml`.

---

## Using it day to day

All of this happens in your repository on GitHub, under the **Actions** tab.

- **Test without posting**: Actions → *Daily verse* → **Run workflow**. Leave "Test only" ticked, tick "Run even if it's before 7:00 AM", then click **Run workflow**. When it finishes, download the poster from the **Artifacts** section at the bottom of the run page.
- **Approve a week in advance**: Actions → *Preview week* → **Run workflow**. You'll get a pull request showing each poster and caption. **Merge** it to approve. To reject one day, delete that day's `.jpg` and `.json` files in the pull request first.
- **When something goes wrong**, the bot opens an **Issue** on your repository and GitHub emails you. Nothing broken is ever posted: if the drawing fails twice, that day is skipped.

---

## One-time setup

These are the same steps Claude walks you through one at a time.

### 1. Make your Instagram a professional account
In the Instagram app: **Profile → ☰ menu → Account type and tools → Switch to professional account** (Creator or Business). The account must be **public**.

### 2. Create the Meta app and get a token
1. Go to <https://developers.facebook.com>, log in, and accept the developer terms if asked.
2. **My Apps → Create App.** Choose the use case for managing Instagram content (the docs call it **Other**), choose app type **Business**, name it (e.g. *MezmurFaith Verse Bot*), then **Create app**.
3. On the app dashboard, find **Instagram** and click **Set up**.
4. Go to **Instagram → API setup with Instagram login**. Under **Generate access tokens**, click **Add account**, log in to your MezmurFaith Instagram and allow access.
5. Click **Generate token** next to the account. Copy the token. This is your `IG_ACCESS_TOKEN` (valid 60 days; the bot refreshes it every week).
6. Copy the number shown next to the account. That's your `IG_USER_ID`.

You don't need App Review, because the bot only posts to your own account.

### 3. Create the OpenAI key
At <https://platform.openai.com>: add a little credit under **Billing**, then **API keys → Create new secret key**. That's your `OPENAI_API_KEY`.

### 4. Create a GitHub token for the bot (`GH_PAT`)
The bot needs this to save the refreshed Instagram token and to open approval pull requests.
GitHub → your photo → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**:
- Repository access: **Only select repositories** → this repository
- Permissions: **Secrets: Read and write**, **Contents: Read and write**, **Pull requests: Read and write**
- Expiration: up to 1 year. Put a reminder in your calendar to renew it.

### 5. Add the secrets to GitHub
Repository → **Settings → Secrets and variables → Actions → New repository secret**. Add each one:

| Name | Value |
|---|---|
| `OPENAI_API_KEY` | from step 3 |
| `IG_ACCESS_TOKEN` | from step 2 |
| `IG_USER_ID` | from step 2 |
| `GH_PAT` | from step 4 |

Secrets are encrypted. They never appear in the code or the logs.

### 6. Test
Run **Daily verse** with "Test only" ticked (see above) and check the poster. When you're happy, the 7:00 AM schedule takes over.

### Get a new Instagram token (if it ever expires)
Repeat step 2.4–2.5 and paste the new token into the `IG_ACCESS_TOKEN` secret (**Update**).

---

## For the app

After each post, these public files are updated:

- `docs/api/today.json`: today's verse
- `docs/api/history.json`: every posted verse, newest first

Each record has `date`, `id`, `english_text`, `english_ref`, `tigrinya_text`, `tigrinya_ref`, `image_url` and `instagram_url`.
The app can read them from `https://raw.githubusercontent.com/<your-github-name>/<repo-name>/main/docs/api/today.json`.

---

## For developers

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest                              # safety tests
.venv/bin/python -m bot.main validate                   # check verses.json
.venv/bin/python -m bot.main render --placeholder       # test poster, no API key needed
OPENAI_API_KEY=... .venv/bin/python -m bot.main render  # test poster with real AI drawing
.venv/bin/python scripts/make_logo.py                   # rebuild logo (needs requirements-logo.txt)
```

Fonts: EB Garamond and Noto Serif Ethiopic, both SIL Open Font License (see `fonts/`).
