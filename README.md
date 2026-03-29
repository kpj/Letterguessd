# Letterguessd

A Letterboxd-inspired movie guessing game. Guess the movie based on popular reviews!

**Play now: [https://kpj.github.io/Letterguessd/](https://kpj.github.io/Letterguessd/)**

## Gameplay

1. You are presented with one review at a time.
2. Guess the movie title in the input box.
3. If your guess is wrong or you skip, the next review is revealed.
4. You have **10 guesses** total.
5. Win by guessing the movie correctly!

## How to Run

### Setup

Create a `.env` file in the root directory and add your Gemini API key:
```env
GEMINI_API_KEY=<key>
```

### Generate Movie Data

Run the scraper to fetch the latest popular movies and curate reviews using Gemini:
```bash
uv run scraper.py --count 7 --url https://letterboxd.com/films/
```
You can also bypass Gemini AI and use a simple fallback selection (useful for testing):
```bash
uv run scraper.py --no-llm
```
This will generate or update `movie_data.json` with 7 fresh movies.

### Start the Game

Since this is a static site, you can host it using any local web server. The simplest way is using Python's built-in server:
```bash
python3 -m http.server 8000
````
Then, open your browser and navigate to:
**[http://localhost:8000](http://localhost:8000)**

## Deployment

### 1. Configure Automated Updates

The repository includes a GitHub Action (`.github/workflows/scrape.yml`) that automatically scrapes new data and deploys the entire site to the `gh-pages` branch.

To enable this, you must add your Gemini API key to GitHub:
1. Go to **Settings > Secrets and variables > Actions**.
2. Create a **New repository secret**.
3. Name: `GEMINI_API_KEY`
4. Value: Paste your Gemini API key.

### 2. Configure Workflow Permissions

GitHub Actions need explicit write permissions to deploy to GitHub Pages:
1. In your repository, go to **Settings > Actions > General**.
2. Under **Workflow permissions**, select **Read and write permissions**.
3. Click **Save**.

### 3. Enable GitHub Pages

Once the first action run completes, a `gh-pages` branch will be created automatically.
1. In your GitHub repository, go to **Settings > Pages**.
2. Set the **Source** to "Deploy from a branch".
3. Select **Branch: `gh-pages`** and **Folder: `/ (root)`**.

Once configured, the game will be live and will update itself with new movies automatically.

## Code Formatting

```bash
uv run ruff check --select I --fix scraper.py
uv run ruff format scraper.py
```
