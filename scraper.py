import argparse
import json
import os
import random
import re
import textwrap
import time

import dotenv
from google import genai
from letterboxdpy.core.scraper import Scraper
from letterboxdpy.movie import Movie


class ReviewCurator:
    """Handles interaction with Gemini AI to select and rank movie review clues."""

    def __init__(self, api_key: str):
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set.")
        self.client = genai.Client(api_key=api_key)

    def curate_reviews(self, title, year, reviews_data):
        """Use Gemini AI to select the best 10 puzzle clues from the review pool."""
        print(f"Using LLM to filter reviews for '{title}'...")

        reviews_input = [
            f"[{i}] Author: {a}\nReview: {t}" for i, (t, a) in enumerate(reviews_data)
        ]

        prompt = textwrap.dedent(f"""\
            I am building a trivia game where users guess a movie based on Letterboxd reviews.
            Movie: {title} ({year})

            Select exactly 10 reviews as puzzle clues:
            - Funny, insightful, or capturing the 'vibe'.
            - NO SPOILERS: If a review names the title or main characters, skip it entirely.
            - Do NOT modify the text; use it exactly as written.
            - Rank from hardest (1) to easiest (10).

            Return a JSON array of 10 objects: {{"text": "...", "author": "..."}}

            Reviews:
            {"\n\n".join(reviews_input)}
        """)

        for attempt in range(3):
            try:
                response = self.client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config={"response_mime_type": "application/json"},
                )
                raw_text = response.text
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, re.DOTALL)
                filtered = json.loads(match.group(1) if match else raw_text)

                if isinstance(filtered, dict) and "reviews" in filtered:
                    filtered = filtered["reviews"]

                if isinstance(filtered, list) and len(filtered) >= 10:
                    return filtered[:10]
                raise ValueError("Invalid LLM response format or count")
            except Exception as e:
                print(f"LLM attempt {attempt + 1} failed: {e}")
                time.sleep(2)
        return None


class MovieProvider:
    """Handles low-level Letterboxd fetching and high-level movie data orchestration."""

    @staticmethod
    def get_list_slugs(url):
        """Fetch unique movie slugs from any Letterboxd list URL with pagination."""
        slugs, current_url = set(), url

        while current_url:
            print(f"Fetching slugs from {current_url}...")
            try:
                dom = Scraper.get_page(current_url)
                poster_divs = dom.select("div[data-target-link]")
                for div in poster_divs:
                    target = div.get("data-target-link", "")
                    if "film/" in target:
                        slug = target.strip("/").split("/")[-1]
                        slugs.add(slug)

                print(f"  Found {len(poster_divs)} movies on this page.")
                next_link = dom.select_one(".pagination a.next")
                current_url = (
                    f"https://letterboxd.com{next_link.get('href')}"
                    if next_link
                    else None
                )
                if current_url:
                    time.sleep(1)
            except Exception as e:
                print(f"Warning: Failed to fetch {current_url}: {e}")
                break

        if not slugs:
            raise RuntimeError(f"No films found at {url}.")
        return list(slugs)

    @staticmethod
    def fetch_paginated_reviews(movie_slug, max_pages=3):
        """Fetch multiple pages of all-time popular reviews."""
        reviews_data = []

        for page in range(1, max_pages + 1):
            url = f"https://letterboxd.com/film/{movie_slug}/reviews/by/activity/page/{page}/"
            print(f"  Fetching reviews page {page}...")
            try:
                dom = Scraper.get_page(url)
                articles = dom.select("article.production-viewing")

                for art in articles:
                    author = art.get("data-person") or (
                        art.select_one(".displayname").get_text(strip=True)
                        if art.select_one(".displayname")
                        else "Unknown"
                    )
                    body = art.select_one(".body-text")
                    if not body:
                        continue

                    text = " ".join(
                        [p.get_text(strip=True) for p in body.find_all("p")]
                    )

                    if 20 <= len(text) <= 500 and not any(
                        r[0] == text for r in reviews_data
                    ):
                        reviews_data.append((text, author))

                if len(articles) < 12:
                    break
                time.sleep(1.5)
            except Exception as e:
                print(f"    Error: {e}")
                break
        return reviews_data

    def provide_movie_data(self, slug, curator: ReviewCurator = None):
        """High-level orchestrator that returns final game data for a given movie slug."""
        time.sleep(1)  # Initial delay
        try:
            m = Movie(slug)
            title, year = m.title, m.year
            print(f"Processing: {title} ({year})")

            reviews = self.fetch_paginated_reviews(slug)
            print(f"  Collected {len(reviews)} valid reviews.")

            if len(reviews) < 10:
                print(f"  Skipping {title}: insufficient reviews.")
                return None

            if not curator:
                print("  Bypassing LLM (fallback to first 10 reviews).")
                final_reviews = [{"text": t, "author": a} for t, a in reviews[:10]]
            else:
                final_reviews = curator.curate_reviews(title, year, reviews[:30])

            if not final_reviews:
                return None

            return {
                "title": title,
                "year": year,
                "link": f"https://letterboxd.com/film/{slug}/",
                "poster": m.poster or "",
                "reviews": final_reviews,
            }
        except Exception as e:
            print(f"  Error processing {slug}: {e}")
            return None


class ScraperApp:
    """The main application that coordinates the scraping process."""

    def __init__(self, url, count, no_llm=False):
        self.url = url
        self.count = count

        self.provider = MovieProvider()
        self.curator = (
            ReviewCurator(os.environ.get("GEMINI_API_KEY")) if not no_llm else None
        )

    def run(self):
        """Execute the full scraping run."""
        slugs = self.provider.get_list_slugs(self.url)
        random.shuffle(slugs)

        collected, used_slugs = [], set()

        for slug in slugs:
            if len(collected) >= self.count:
                break

            if slug in used_slugs:
                continue

            data = self.provider.provide_movie_data(slug, self.curator)
            if data:
                collected.append(data)
                used_slugs.add(slug)
                print(f"Added ({len(collected)}/{self.count})")
            else:
                time.sleep(2)

        if not collected:
            raise RuntimeError("No movies gathered.")

        self._save_results(collected)
        print(f"\nSuccess: Saved {len(collected)} movies to movie_data.json.")

    @staticmethod
    def _save_results(collected):
        with open("movie_data.json", "w") as f:
            json.dump({"movies": collected}, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Letterboxd scraper.")
    parser.add_argument(
        "--url",
        default="https://letterboxd.com/films/",
        help="Letterboxd URL to scrape (list or popular films)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=7,
        help="Number of movies to collect",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Bypass Gemini LLM and use first 10 reviews as fallback",
    )
    args = parser.parse_args()

    dotenv.load_dotenv()

    app = ScraperApp(args.url, args.count, args.no_llm)
    app.run()


if __name__ == "__main__":
    main()
