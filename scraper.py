import json
import os
import random
import re
import textwrap
import time

import cloudscraper
import dotenv
from bs4 import BeautifulSoup
from google import genai


def get_movies(scraper):
    url = "https://letterboxd.com/films/"
    req = scraper.get(url)
    if req.status_code != 200:
        raise RuntimeError(f"Failed to fetch popular films: HTTP {req.status_code}")

    soup = BeautifulSoup(req.text, "html.parser")
    movies = soup.select("div[data-target-link]")
    if not movies:
        raise RuntimeError(f"No films found on {url}.")

    return movies


def llm_filter_reviews(reviews_data, title, year):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or not genai:
        raise RuntimeError("GEMINI_API_KEY not set or genai not installed.")

    print(f"Using LLM to filter reviews for {title}...")
    client = genai.Client()

    reviews_input = []
    for i, (text, author) in enumerate(reviews_data):
        reviews_input.append(f"[{i}] Author: {author}\nReview: {text}")

    reviews_text = "\n\n".join(reviews_input)

    prompt = textwrap.dedent(f"""\
        I am building a trivia game where users have to guess the movie based on Letterboxd reviews.
        The movie is: {title} ({year})

        Below are {len(reviews_data)} popular reviews for this movie.
        I need you to pick exactly 10 reviews that make good puzzle clues.
        - They should be funny, insightful, or capture the vibe of the movie.
        - If a review directly names the movie title, a main character, or otherwise trivially gives away the answer, SKIP it entirely — do NOT include it and do NOT alter its text.
        - Do not modify or censor any of the review text. Use it exactly as written.
        - Order them from hardest to guess (first) to easiest to guess (last).

        Return a valid JSON array of exactly 10 objects. Each object must have:
        - "text": The review text, exactly as written (no modifications).
        - "author": The author of the review.

        Reviews:
        {reviews_text}
    """)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )

            raw_text = response.text
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, re.DOTALL)
            json_str = match.group(1) if match else raw_text

            filtered = json.loads(json_str)
            if not isinstance(filtered, list):
                if isinstance(filtered, dict) and "reviews" in filtered:
                    filtered = filtered["reviews"]
                else:
                    raise ValueError("LLM did not return a list")

            if len(filtered) < 10:
                raise ValueError(f"LLM returned too few reviews ({len(filtered)}/10)")

            return filtered[:10]
        except Exception as e:
            print(f"LLM attempt {attempt + 1} failed: {e!r}")
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                return None


def process_movie(scraper, movie_el, used_titles):
    """Fetch + LLM-filter reviews for one movie. Returns a dict or None."""
    target_link = movie_el.get("data-target-link")
    full_name = movie_el.get("data-item-full-display-name")

    match = re.match(r"(.*)\s+\((\d{4})\)$", full_name)
    title, year = match.groups() if match else (full_name, "Unknown")

    if title in used_titles:
        return None

    print(f"Processing: {title} ({year})")

    time.sleep(2)  # Rate-limiting
    movie_url = f"https://letterboxd.com{target_link}"
    req = scraper.get(movie_url)
    if req.status_code != 200:
        print(f"Warning: Movie page returned status {req.status_code}")
    soup = BeautifulSoup(req.text, "html.parser")

    # Get high-res poster from og:image
    og_img = soup.find("meta", property="og:image")
    poster_url = og_img.get("content", "") if og_img else ""
    if "default-share" in poster_url:
        short_poster = movie_el.get("data-poster-url")
        if short_poster:
            poster_url = f"https://letterboxd.com{short_poster}"

    # Collect reviews from the main page
    review_els = soup.select(".listitem, .review, li.review, .film-detail")
    reviews_data = []

    def extract_reviews(elements):
        for r in elements:
            author_tag = r.select_one(".displayname, .name, .owner strong, .author")
            text_div = r.select_one(".body-text, .review-body, .review-text, p")

            if author_tag and text_div:
                author = author_tag.get_text(strip=True)
                text = text_div.get_text(separator=" ", strip=True)

                # Check for spoilers and extract hidden text
                if "This review may contain spoilers" in text:
                    hidden_div = r.select_one(
                        ".js-review-body, .full-text, .review-body"
                    )
                    if hidden_div:
                        text = hidden_div.get_text(separator=" ", strip=True)
                    else:
                        continue

                # Only include reviews that are reasonably long
                if len(text) > 20:
                    reviews_data.append((text, author))

    extract_reviews(review_els)

    # If we don't have enough reviews, try the dedicated reviews page
    if len(reviews_data) < 10:
        print(
            f"Only {len(reviews_data)} reviews on main page, fetching reviews page...",
        )
        time.sleep(1)
        reviews_url = f"https://letterboxd.com{target_link}reviews/by/activity/"
        req_r = scraper.get(reviews_url)
        if req_r.status_code != 200:
            print(f"  Warning: Reviews page returned status {req_r.status_code}")
        soup_r = BeautifulSoup(req_r.text, "html.parser")
        more_els = soup_r.select(
            ".listitem .production-viewing, .film-detail, .review, li.review, .listitem"
        )
        extract_reviews(more_els)

    print(f"  {len(reviews_data)} reviews found")
    if len(reviews_data) < 10:
        return None

    final_reviews = llm_filter_reviews(reviews_data[:30], title, year)
    if not final_reviews:
        return None

    return {
        "title": title,
        "year": year,
        "link": f"https://letterboxd.com{target_link}",
        "poster": poster_url,
        "reviews": final_reviews,
    }


def main(num_movies=7):
    dotenv.load_dotenv()

    root_scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    print("Fetching popular movies...")
    movies = get_movies(root_scraper)

    if not movies:
        print("Failed to find any movies.")
        return

    # Shuffle so we get a fresh random selection each run
    movies_list = list(movies)
    random.shuffle(movies_list)

    collected = []
    used_titles: set = set()

    for movie_el in movies_list:
        if len(collected) >= num_movies:
            break

        # Create a fresh scraper for each movie to avoid session-based blocks
        movie_scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        movie_data = process_movie(movie_scraper, movie_el, used_titles)
        if movie_data:
            collected.append(movie_data)
            used_titles.add(movie_data["title"])
            print(f"Added ({len(collected)}/{num_movies})")
        else:
            time.sleep(5)

    if not collected:
        raise RuntimeError("Could not gather any movies with sufficient reviews.")

    out_data = {"movies": collected}
    with open("movie_data.json", "w") as f:
        json.dump(out_data, f, indent=2)

    print(f"\nSaved movie_data.json with {len(collected)} movies.")


if __name__ == "__main__":
    main()
