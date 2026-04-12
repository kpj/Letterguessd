import functools
import json
import os
import threading
from datetime import date
from http.server import HTTPServer, SimpleHTTPRequestHandler

import pytest
from playwright.sync_api import Page, expect


from datetime import timedelta


@pytest.fixture(scope="module", autouse=True)
def dev_server(tmp_path_factory):
    # Create an isolated temporary directory for the web server
    tmp_dir = tmp_path_factory.mktemp("letterguessd_test_site")

    # Copy the necessary frontend files into the temp directory
    for filename in ["index.html", "app.js", "style.css"]:
        src_path = os.path.join(os.getcwd(), filename)
        dst_path = tmp_dir / filename
        with open(src_path, "rb") as src, open(dst_path, "wb") as dst:
            dst.write(src.read())

    # Setup: Create a dummy movie_data.json with Today and Tomorrow
    today_date = date.today()
    tomorrow_date = today_date + timedelta(days=1)

    today_name = today_date.strftime("%A").lower()
    tomorrow_name = tomorrow_date.strftime("%A").lower()

    today_movie = {
        "title": "Inception",
        "year": "2010",
        "genres": ["Action", "Sci-Fi"],
        "directors": ["Christopher Nolan"],
        "cast": ["Leo"],
        "poster": "",
        "reviews": [{"text": "A dream within a dream.", "author": "User 1"}],
    }

    tomorrow_movie = {
        "title": "The Matrix",
        "year": "1999",
        "genres": ["Action", "Sci-Fi"],
        "directors": ["The Wachowskis"],
        "cast": ["Keanu"],
        "poster": "",
        "reviews": [{"text": "There is no spoon.", "author": "User 2"}],
    }

    dummy_data = {
        "movies": {today_name: [today_movie], tomorrow_name: [tomorrow_movie]}
    }

    with open(tmp_dir / "movie_data.json", "w") as f:
        json.dump(dummy_data, f)

    # Setup: Create a dummy history.json with an archived game
    history_game = {
        "id": 0,
        "date": "2026-04-10",
        "title": "Interstellar",
        "year": "2014",
        "genres": ["Adventure", "Sci-Fi"],
        "directors": ["Christopher Nolan"],
        "cast": ["Matthew McConaughey"],
        "poster": "",
        "reviews": [{"text": "Stay.", "author": "Murph"}],
    }

    history_data = {"games": [history_game]}

    with open(tmp_dir / "history.json", "w") as f:
        json.dump(history_data, f)

    # Configure the handler to serve from the temp directory
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_dir))

    # Start a pure Python HTTP server in a separate thread
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]

    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    yield f"http://127.0.0.1:{port}"

    # Teardown
    httpd.shutdown()
    httpd.server_close()
    server_thread.join()


def test_basic_load(page: Page, dev_server):
    # Log browser console output to terminal for easier debugging
    page.on("console", lambda msg: print(f"Browser console: {msg.text}"))
    page.on("pageerror", lambda exc: print(f"Browser error: {exc}"))

    page.goto(dev_server)
    # Check header
    expect(page.locator("header h1")).to_have_text("Letterguessd")
    # Check stats bar
    expect(page.locator("#game-id-badge")).to_be_visible()


def test_multi_day_selection(page: Page, dev_server):
    # 1. Test "Today" selection (no ID in URL)
    page.goto(dev_server)
    # Based on fixture, Today is Inception (Review: A dream within a dream.)
    expect(page.locator(".review-text").first).to_have_text("A dream within a dream.")

    # 2. Test "Tomorrow" selection (ID in URL)
    EPOCH = date(2026, 4, 10)
    tomorrow_id = (date.today() + timedelta(days=1) - EPOCH).days

    page.goto(f"{dev_server}/?id={tomorrow_id}")
    # Tomorrow should be The Matrix (Review: There is no spoon.)
    expect(page.locator(".review-text").first).to_have_text("There is no spoon.")
    # Badge should show tomorrow's ID
    expect(page.locator("#game-id-badge")).to_have_text(f"Game #{tomorrow_id}")


def test_history_load(page: Page, dev_server):
    # Test loading Game #0 from history.json
    page.goto(f"{dev_server}/?id=0")

    # Should load Interstellar
    expect(page.locator(".review-text").first).to_have_text("Stay.")
    # Should show the replay notice
    expect(page.locator("#replay-notice")).to_be_visible()
    expect(page.locator("#replay-notice")).to_contain_text(
        "Replaying game from Apr 10, 2026"
    )
    # Badge should show Game #0
    expect(page.locator("#game-id-badge")).to_have_text("Game #0")


def test_guess_interaction(page: Page, dev_server):
    page.goto(dev_server)

    # Initially 10 guesses
    expect(page.locator("#guesses-remaining .highlight")).to_have_text("10")

    # Input a wrong guess
    page.fill("#guess-input", "The Dark Knight")
    page.click("#guess-button")

    # Verify guess card appears
    expect(page.locator(".guess-card.is-wrong")).to_be_visible()
    # Verify counter decrements
    expect(page.locator("#guesses-remaining .highlight")).to_have_text("9")


def test_skip_interaction(page: Page, dev_server):
    page.goto(dev_server)

    # Click Next review
    page.click("#skip-button")

    # Verify Skipped card appears
    expect(page.locator(".guess-card.is-skip")).to_be_visible()


def test_extra_hint_interaction(page: Page, dev_server):
    page.goto(dev_server)

    # Click Extra hint
    page.click("#hint-button")

    # Verify the "ritual": Status card + Content card
    expect(page.locator(".guess-card.is-hint")).to_be_visible()
    expect(page.locator(".review-card.hint-card")).to_be_visible()

    # Verify values (from dummy_data fixture)
    expect(page.locator(".review-card.hint-card")).to_contain_text("2010")
