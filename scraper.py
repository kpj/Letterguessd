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


def get_movie_slugs(url):
    """Fetch unique movie slugs from any Letterboxd list URL with pagination."""
    slugs, current_url = set(), url

    while current_url:
        print(f"Fetching slugs from {current_url}...")
        try:
            dom = Scraper.get_page(current_url)
            # Standard Letterboxd movies are in div[data-target-link]
            poster_divs = dom.select("div[data-target-link]")
            for div in poster_divs:
                target = div.get("data-target-link", "")
                if "film/" in target:
                    # Extract just the slug (e.g., /film/slug/ -> slug)
                    slug = target.strip("/").split("/")[-1]
                    slugs.add(slug)

            print(f"  Found {len(poster_divs)} movies on this page.")
            next_link = dom.select_one(".pagination a.next")
            current_url = (
                f"https://letterboxd.com{next_link.get('href')}" if next_link else None
            )
            if current_url:
                time.sleep(1)
        except Exception as e:
            print(f"Warning: Failed to fetch {current_url}: {e}")
            break

    if not slugs:
        raise RuntimeError(f"No films found at {url}.")
    return list(slugs)


def llm_filter_reviews(reviews_data, title, year):
    """Use Gemini AI to select the best 10 puzzle clues from the review pool."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set.")

    print(f"Using LLM to filter reviews for {title}...")
    client = genai.Client()
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
            response = client.models.generate_content(
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


def fetch_more_reviews(movie_slug):
    """Fetch 3 pages of all-time popular reviews using specialized pagination."""
    reviews_data, seen_texts = [], set()

    for page in range(1, 4):
        url = (
            f"https://letterboxd.com/film/{movie_slug}/reviews/by/activity/page/{page}/"
        )
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

                # Better spoiler detection: combine all p tags inside the body
                text = " ".join([p.get_text(strip=True) for p in body.find_all("p")])

                if 20 <= len(text) <= 500 and text not in seen_texts:
                    reviews_data.append((text, author))
                    seen_texts.add(text)

            if len(articles) < 12:
                break
            time.sleep(1.5)
        except Exception as e:
            print(f"    Error: {e}")
            break
    return reviews_data


def process_movie(slug, bypass_llm=False):
    """Fetch metadata and curate reviews for a single movie via its slug."""
    time.sleep(1)  # Initial delay
    try:
        m = Movie(slug)
        title, year = m.title, m.year
        print(f"Processing: {title} ({year})")
        reviews_data = fetch_more_reviews(slug)
        print(f"  Collected {len(reviews_data)} valid reviews.")

        if len(reviews_data) < 10:
            print(f"  Skipping {title}: insufficient reviews.")
            return None

        if bypass_llm:
            final_reviews = [{"text": t, "author": a} for t, a in reviews_data[:10]]
        else:
            final_reviews = llm_filter_reviews(reviews_data[:30], title, year)

        return (
            {
                "title": title,
                "year": year,
                "link": f"https://letterboxd.com/film/{slug}/",
                "poster": m.poster or "",
                "reviews": final_reviews,
            }
            if final_reviews
            else None
        )
    except Exception as e:
        print(f"  Error processing {slug}: {e}")
        return None


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
    slugs = get_movie_slugs(args.url)
    random.shuffle(slugs)

    collected, used_slugs = [], set()

    for slug in slugs:
        if len(collected) >= args.count:
            break

        if slug in used_slugs:
            continue

        data = process_movie(slug, args.no_llm)
        if data:
            collected.append(data)
            used_slugs.add(slug)
            print(f"Added ({len(collected)}/{args.count})")
        else:
            time.sleep(2)

    if not collected:
        raise RuntimeError("No movies gathered.")

    with open("movie_data.json", "w") as f:
        json.dump({"movies": collected}, f, indent=2)
    print(f"\nSuccess: Saved {len(collected)} movies to movie_data.json.")


if __name__ == "__main__":
    main()
