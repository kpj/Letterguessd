# Letterguessd
![Tests Status](https://github.com/kpj/Letterguessd/actions/workflows/test.yml/badge.svg)

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


### Game Data

A GitHub Action (`.github/workflows/scrape.yml`) runs on a schedule to:
-   Fetch new movies.
-   Curate reviews using an LLM.
-   Store the results in a dedicated **`data` branch**.

The hosted app automatically detects its environment and pulls from this branch.

### Source Code

The source code from the **`main` branch** is automatically deployed to GitHub Pages.

1.  In your repository, go to **Settings > Pages**.
2.  Set **Build and deployment > Branch** to **`main`**.
3.  Click **Save**.

Once configured, any code you push to `main` will go live immediately, while the data will update itself in the background when the Github Actions workflow runs.

### Repository Configuration

To enable automated data updates:
1.  Go to **Settings > Secrets and variables > Actions**.
2.  Create a secret named `GEMINI_API_KEY` with your Gemini key.
3.  Ensure **Settings > Actions > General > Workflow permissions** is set to **Read and write permissions**.

## Code Formatting

```bash
uv run ruff check --select I --fix scraper.py
uv run ruff format scraper.py
```
