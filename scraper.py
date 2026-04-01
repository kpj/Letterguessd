import argparse
import json
import os
import random
import re
import textwrap
import time

import dotenv
import yaml
from google import genai
from letterboxdpy.core.scraper import Scraper
from letterboxdpy.movie import Movie
from loguru import logger


class ReviewCurator:
    """Handles interaction with Gemini AI to select and rank movie review clues."""

    def __init__(self, api_key: str):
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set.")
        self.client = genai.Client(api_key=api_key)

    @staticmethod
    def _is_valid_review(text, author, title, original_texts=None):
        """Pure validation for a single review. original_texts is for POST-LLM checks."""
        if not text or not isinstance(text, str):
            return False
        if not author or not isinstance(author, str):
            return False

        t_lower = title.lower()
        t_no_year = re.sub(r"\s*\(\d{4}\)\s*$", "", t_lower).strip()
        review_lower = text.lower()

        # Reject if title is mentioned
        if t_lower in review_lower or t_no_year in review_lower:
            return False

        # If original_texts provided, reject if LLM modified the text
        if original_texts is not None and text not in original_texts:
            return False

        return True

    def _pre_filter_reviews(self, reviews_data, title):
        """Strip out obviously bad reviews before LLM call to save tokens."""
        valid = []
        for text, author in reviews_data:
            if self._is_valid_review(text, author, title):
                valid.append((text, author))
        return valid

    def _post_llm_checks(self, filtered, title, original_texts):
        """Run post-LLM validation checks on a batch of reviews."""
        valid = []
        failed_texts = set()
        for r in filtered:
            text, author = r.get("text"), r.get("author")
            if self._is_valid_review(text, author, title, original_texts):
                valid.append({"text": text, "author": author})
            else:
                if text:
                    failed_texts.add(text)
        return valid, failed_texts

    def curate_reviews(self, title, year, reviews_data):
        """Use Gemini AI to select the best 10 puzzle clues from the review pool."""
        # Pre-filter to save tokens
        working_pool = self._pre_filter_reviews(reviews_data, title)
        logger.debug(
            f"Pre-filtered pool: {len(working_pool)} reviews (was {len(reviews_data)})"
        )

        if len(working_pool) < 10:
            logger.warning(
                f"Skipping {title}: insufficient valid reviews after pre-filtering."
            )
            return None

        # Limit to top ~50 reviews to stay token-efficient but catch good reviews
        working_pool = working_pool[:50]
        original_texts = {text for text, _ in working_pool}

        for attempt in range(3):
            # Format input for LLM
            reviews_input = [
                f"[{i}] Author: {a}\nReview: {t}"
                for i, (t, a) in enumerate(working_pool)
            ]

            prompt = textwrap.dedent(f"""\
                I am building a trivia game where users guess a movie based on its Letterboxd reviews.
                Movie: {title} ({year})

                Select exactly 10 reviews from the list below to serve as puzzle clues.

                CRITICAL CONSTRAINTS:
                - ENGLISH ONLY: Only select reviews that are written in English.
                - NO MOVIE TITLE: Skip any review that mentions the title (partial or full).
                - NO SPOILERS: Skip any review that reveals major plot twists.
                - NO MODIFICATION: Do NOT change the text at all. Keep emojis, punctuation, and style exactly as provided.
                - CHARACTER NAMES: Avoid character names in the first 7 clues. They are okay in clues 8-10.
                - ACTORS/DIRECTORS: Only allowed in clues 8, 9, and 10 (Easiest clues).

                RANKING (1 = Hardest, 10 = Easiest):
                - Clues 1-4 (Hard): Focus on "vibes," cinematography style, abstract feelings, or funny observational humor that doesn't name specifics.
                - Clues 5-7 (Medium): Focus on genre tropes, specific themes, or technical praise (music, editing).
                - Clues 8-10 (Easy): Iconic quotes, mentions of the director's unique style, or notable actors (if you must).

                Return a JSON array of exactly 10 objects: {{"text": "...", "author": "..."}}

                Reviews to choose from:
                {"\n\n".join(reviews_input)}
            """)

            try:
                response = self.client.models.generate_content(
                    model="gemini-3-flash-preview",
                    contents=prompt,
                    config={"response_mime_type": "application/json"},
                )

                # Check for empty response or safety filters
                if not response.text:
                    raise ValueError(
                        "Empty response from LLM (possibly safety filter)."
                    )

                raw_text = response.text
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, re.DOTALL)
                filtered = json.loads(match.group(1) if match else raw_text)

                if isinstance(filtered, dict) and "reviews" in filtered:
                    filtered = filtered["reviews"]

                if not isinstance(filtered, list):
                    raise ValueError(f"LLM returned non-list: {type(filtered)}")

                # Post-LLM checks
                valid, failed_texts = self._post_llm_checks(
                    filtered, title, original_texts
                )

                if len(valid) >= 10:
                    return valid[:10]

                # If count < 10, remove the failed ones from our pool and retry
                if failed_texts:
                    logger.warning(
                        f"Attempt {attempt + 1} rejected {len(failed_texts)} reviews. Retrying..."
                    )
                    working_pool = [r for r in working_pool if r[0] not in failed_texts]
                else:
                    logger.warning(
                        f"Attempt {attempt + 1} only returned {len(valid)} reviews (expected 10). Retrying..."
                    )

                if len(working_pool) < 10:
                    logger.warning("Working pool exhausted below 10 reviews.")
                    break

            except Exception as e:
                logger.error(f"LLM attempt {attempt + 1} failed: {e}")
                time.sleep(2)

        return None


class MovieProvider:
    """Handles low-level Letterboxd fetching and high-level movie data orchestration."""

    @staticmethod
    def get_list_slugs(base_url):
        """Fetch unique movie slugs from a random page and up to 5 subsequent pages."""
        slugs = set()
        logger.info(f"Finding max pages for {base_url}...")

        try:
            dom = Scraper.get_page(base_url)
        except Exception as e:
            logger.error(f"Failed to load base URL {base_url}: {e}")
            return []

        # Find max page
        max_page = 1
        pagination_links = dom.select(".paginate-pages a")
        if pagination_links:
            try:
                # The last element usually points to the highest page number
                last_page_text = pagination_links[-1].get_text(strip=True)
                max_page = int(last_page_text.replace(',', ''))
            except ValueError:
                pass

        start_page = random.randint(1, max_page)
        
        pages_to_fetch = min(6, max_page - start_page + 1)
        if pages_to_fetch < 6 and max_page >= 6:
            start_page = max(1, max_page - 5)
            pages_to_fetch = 6

        logger.info(f"Max page is {max_page}. Selected start_page {start_page}, will fetch {pages_to_fetch} page(s).")

        base_url_cleaned = base_url.rstrip("/")
        for i in range(pages_to_fetch):
            page_num = start_page + i
            url = f"{base_url_cleaned}/page/{page_num}/" if page_num > 1 else f"{base_url_cleaned}/"

            logger.info(f"Fetching slugs from {url}...")
            try:
                page_dom = Scraper.get_page(url)
                poster_divs = page_dom.select("div[data-target-link]")
                page_slugs = 0
                for div in poster_divs:
                    target = div.get("data-target-link", "")
                    if "film/" in target:
                        slug = target.strip("/").split("/")[-1]
                        slugs.add(slug)
                        page_slugs += 1

                logger.info(f"Found {page_slugs} movies on this page.")
                if page_slugs == 0:
                    break
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Failed to fetch {url}: {e}")
                break

        return list(slugs)

    @staticmethod
    def fetch_paginated_reviews(movie_slug, max_pages=3):
        """Fetch multiple pages of all-time popular reviews."""
        reviews_data = []

        for page in range(1, max_pages + 1):
            url = f"https://letterboxd.com/film/{movie_slug}/reviews/by/activity/page/{page}/"
            logger.info(f"Fetching reviews page {page}...")
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
                logger.error(f"Error: {e}")
                break
        return reviews_data

    def provide_movie_data(self, slug, curator: ReviewCurator = None):
        """High-level orchestrator that returns final game data for a given movie slug."""
        time.sleep(1)  # Initial delay
        try:
            m = Movie(slug)
            title, year = m.title, m.year
            logger.info(f"Processing: {title} ({year})")

            reviews = self.fetch_paginated_reviews(slug)
            logger.info(f"Collected {len(reviews)} valid reviews.")

            if len(reviews) < 10:
                logger.warning(f"Skipping {title}: insufficient reviews.")
                return None

            if not curator:
                logger.info("Bypassing LLM (fallback to first 10 reviews).")
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
            logger.error(f"Error processing {slug}: {e}")
            return None


class ScraperApp:
    """The main application that coordinates the scraping process."""
    
    def __init__(self, count, no_llm=False, config_file="schedule.yml"):
        self.count = count
        self.provider = MovieProvider()
        self.curator = (
            ReviewCurator(os.environ.get("GEMINI_API_KEY")) if not no_llm else None
        )
        self.history_file = "history.json"
        self.history = self._load_history()
        self.days_mapping = self._load_config(config_file)

    def _load_config(self, config_file):
        try:
            with open(config_file, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load schedule from {config_file}: {e}")
            return {}

    def _load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load {self.history_file}: {e}")
        return []

    def _save_history(self):
        # Keep last 100 history items to prevent endless growth
        self.history = self.history[-100:]
        try:
            with open(self.history_file, "w") as f:
                json.dump(self.history, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save {self.history_file}: {e}")

    def run(self):
        """Execute the full scraping run."""
        movies_by_day = {}
        used_slugs_this_run = set()

        for day_name, list_url in self.days_mapping.items():
            logger.info(f"=== Processing for {day_name.capitalize()} ===")
            slugs = self.provider.get_list_slugs(list_url)
            random.shuffle(slugs)

            collected_for_day = []
            for slug in slugs:
                if len(collected_for_day) >= self.count:
                    break

                if slug in self.history or slug in used_slugs_this_run:
                    logger.debug(f"Skipping {slug} (already in history or used this run).")
                    continue

                data = self.provider.provide_movie_data(slug, self.curator)
                if data:
                    collected_for_day.append(data)
                    used_slugs_this_run.add(slug)
                    self.history.append(slug)
                    logger.success(f"Added ({len(collected_for_day)}/{self.count}) for {day_name}.")
                else:
                    time.sleep(2)

            if not collected_for_day:
                logger.error(f"Failed to find any viable movie for {day_name}.")
            else:
                movies_by_day[day_name] = collected_for_day

        if not movies_by_day:
            raise RuntimeError("No movies gathered.")

        self._save_results(movies_by_day)
        self._save_history()
        logger.success("Saved schedule to movie_data.json.")

    @staticmethod
    def _save_results(movies_by_day):
        with open("movie_data.json", "w") as f:
            json.dump({"movies": movies_by_day}, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Letterboxd scraper.")
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of movies to collect per day",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="schedule.yml",
        help="Path to the schedule YAML file",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Bypass Gemini LLM and use first 10 reviews as fallback",
    )
    args = parser.parse_args()

    dotenv.load_dotenv()

    app = ScraperApp(args.count, args.no_llm, args.config)
    app.run()


if __name__ == "__main__":
    main()
