import functools
import json
import os
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler

import pytest
from playwright.sync_api import Page, expect


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

    # Setup: Create a dummy movie_data.json in the temp directory
    # app.js expects: { "movies": { "monday": [...], ... } }
    day_name = time.strftime("%A").lower()

    movie_entry = {
        "id": 1,
        "title": "Inception",
        "year": "2010",
        "genres": ["Action", "Sci-Fi"],
        "directors": ["Christopher Nolan"],
        "cast": ["Leo"],
        "poster": "",
        "reviews": [
            {"text": "A dream within a dream.", "author": "User 1"},
            {"text": "Mind-bending visuals.", "author": "User 2"},
        ],
    }

    dummy_data = {"movies": {day_name: [movie_entry]}}

    with open(tmp_dir / "movie_data.json", "w") as f:
        json.dump(dummy_data, f)

    # Configure the handler to serve from the temp directory
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_dir))

    # Start a pure Python HTTP server in a separate thread
    # Using port 0 allows the OS to pick an available port automatically
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]

    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    yield f"http://127.0.0.1:{port}"

    # Teardown: Stop the server cleanly
    httpd.shutdown()
    httpd.server_close()
    server_thread.join()


def test_basic_load(page: Page, dev_server):
    # Log browser console output to terminal for easier debugging
    page.on("console", lambda msg: print(f"Browser console: {msg.text}"))
    page.on("pageerror", lambda exc: print(f"Browser error: {exc}"))

    page.goto(f"{dev_server}/?id=1")
    # Check header
    expect(page.locator("header h1")).to_have_text("Letterguessd")
    # Check stats bar
    expect(page.locator("#game-id-badge")).to_be_visible()
    expect(page.locator("#guesses-remaining")).to_contain_text("Guesses left:")


def test_guess_interaction(page: Page, dev_server):
    page.goto(f"{dev_server}/?id=1")

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
    page.goto(f"{dev_server}/?id=1")

    # Click Next review
    page.click("#skip-button")

    # Verify Skipped card appears
    expect(page.locator(".guess-card.is-skip")).to_be_visible()
    # Verify second review card is revealed
    expect(page.locator(".review-card")).to_have_count(2)


def test_extra_hint_interaction(page: Page, dev_server):
    page.goto(f"{dev_server}/?id=1")

    # Click Extra hint
    page.click("#hint-button")

    # Verify the "ritual": Status card + Content card
    expect(page.locator(".guess-card.is-hint")).to_be_visible()
    expect(page.locator(".review-card.hint-card")).to_be_visible()

    # Verify values (from dummy_data fixture)
    expect(page.locator(".review-card.hint-card")).to_contain_text("2010")
    expect(page.locator(".review-card.hint-card")).to_contain_text("Action")
