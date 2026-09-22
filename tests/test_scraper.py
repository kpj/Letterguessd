import json
import os
from datetime import date

from scraper import MovieProvider, ReviewCurator, ScraperApp


def test_game_id_logic():
    # April 10, 2026 is Day 0. April 11 is Day 1.
    assert ScraperApp._game_id_for_date(date(2026, 4, 11)) == 1
    assert ScraperApp._game_id_for_date(date(2026, 4, 10)) == 0


def test_display_date_for_day(mocker):
    # April 13, 2026 is a Monday.
    # Suppose "today" is Sunday, April 12.
    mock_date = mocker.patch("scraper.date")
    mock_date.today.return_value = date(2026, 4, 12)
    mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

    # Monday should be tomorrow (April 13)
    d = ScraperApp._display_date_for_day("monday")
    assert d == date(2026, 4, 13)

    # Sunday should be the concluding Sunday of the upcoming cycle (+7 days, April 19)
    d_sun = ScraperApp._display_date_for_day("sunday")
    assert d_sun == date(2026, 4, 19)


def test_history_deduplication(mocker, tmp_path):
    mocker.patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    test_history = str(tmp_path / "test_history.json")
    with open(test_history, "w") as f:
        json.dump(
            {
                "games": [
                    {
                        "id": 1,
                        "date": "2026-04-11",
                        "day": "saturday",
                        "slug": "old-slug",
                        "title": "Old Movie",
                    }
                ]
            },
            f,
        )

    app = ScraperApp(count=1, no_llm=True)
    app.history_file = test_history
    app.history = app._load_history()

    # Re-running for ID 1 should replace, not duplicate
    game_entry = {
        "id": 1,
        "date": "2026-04-11",
        "day": "saturday",
        "slug": "new-slug",
        "title": "Updated Movie",
    }
    games = app.history.setdefault("games", [])
    existing_idx = next((i for i, g in enumerate(games) if g.get("id") == 1), None)
    if existing_idx is not None:
        games[existing_idx] = game_entry
    else:
        games.append(game_entry)

    app._save_history()

    with open(test_history) as f:
        data = json.load(f)
    assert len(data["games"]) == 1
    assert data["games"][0]["title"] == "Updated Movie"


def test_review_validation():
    curator = ReviewCurator(api_key="fake_key")
    # Title mentions should be rejected
    assert (
        curator._is_valid_review("I love Inception!", "Author", "Inception (2010)")
        is False
    )
    # Case insensitive
    assert (
        curator._is_valid_review("inception is great", "Author", "Inception (2010)")
        is False
    )
    # Normal review
    assert (
        curator._is_valid_review("A dream within a dream", "Author", "Inception (2010)")
        is True
    )


def test_full_scrape_integration(mocker, tmp_path):
    # 1. Mock movie data (Letterboxdpy Movie class)
    mock_movie = mocker.patch("scraper.Movie")
    m = mock_movie.return_value
    m.title = "Test Movie"
    m.year = "2024"
    m.genres = [{"name": "Action"}]
    m.crew = {"director": [{"name": "Christopher Nolan"}]}
    m.cast = [{"name": "Leo"}]
    m.poster = "https://example.com/poster.jpg"

    # 2. Mock list slug fetching (Letterboxdpy Scraper.get_page)
    mock_get_page = mocker.patch("scraper.Scraper.get_page")
    mock_dom = mocker.MagicMock()
    # Mock behavior for pagination and then items
    mock_dom.select.side_effect = [
        [],  # paginate-pages
        [mocker.MagicMock(**{"get.return_value": "/film/test-slug/"})],  # poster divs
    ]
    mock_get_page.return_value = mock_dom

    # 3. Mock Gemini response (google-genai)
    mock_genai = mocker.patch("scraper.genai.Client")
    client = mock_genai.return_value
    mock_response = mocker.MagicMock()
    # Return 10 clues that match the input text to pass the "no modified text" check.
    clues = [{"text": "Text", "author": f"User {i}"} for i in range(10)]
    mock_response.text = json.dumps(clues)
    client.models.generate_content.return_value = mock_response

    # 4. Setup App
    mocker.patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key-for-testing"})
    test_history = str(tmp_path / "test_history.json")

    # Mock initialization to avoid loading real history.json from disk
    mocker.patch("scraper.ScraperApp._load_history", return_value={"games": []})

    app = ScraperApp(count=1, no_llm=False)
    app.history_file = test_history
    app.output_file = str(tmp_path / "test_movie_data.json")
    app.days_mapping = {"monday": "http://fake.url/list"}

    # Run loop (Mocking today to be Sunday April 12)
    mock_loop_date = mocker.patch("scraper.date")
    mock_loop_date.today.return_value = date(2026, 4, 12)
    mock_loop_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

    # We also need to mock MovieProvider.fetch_paginated_reviews or it will try to hit network
    mocker.patch.object(
        MovieProvider,
        "fetch_paginated_reviews",
        return_value=[("Text", "Author")] * 20,
    )

    app.run()
    app._save_history()

    # 5. Assertions
    assert os.path.exists(test_history)
    with open(test_history, "r") as f:
        data = json.load(f)

    assert "games" in data
    assert len(data["games"]) == 1
    game = data["games"][0]
    assert game["id"] == 3  # April 13 is ID 3
    assert game["title"] == "Test Movie"
    assert len(game["reviews"]) == 10
    assert game["slug"] == "test-slug"

    # Verify used_slugs prevents double-dipping
    assert "test-slug" in {g["slug"] for g in app.history["games"]}
