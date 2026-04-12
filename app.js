document.addEventListener('DOMContentLoaded', () => {
    const reviewsContainer = document.getElementById('reviews-container');
    const guessForm = document.getElementById('guess-form');
    const guessInput = document.getElementById('guess-input');
    const skipButton = document.getElementById('skip-button');
    const guessesRemainingEl = document.querySelector('#guesses-remaining .highlight');

    const endScreen = document.getElementById('end-screen');
    const endTitle = document.getElementById('end-title');
    const movieTitleLink = document.getElementById('movie-title-link');
    const movieTitleName = document.getElementById('movie-title');
    const moviePoster = document.getElementById('movie-poster');
    const guessArea = document.getElementById('guess-area');
    const shareButton = document.getElementById('share-button');
    const shareToast = document.getElementById('share-toast');
    const sharePreview = document.getElementById('share-preview');
    const endStats = document.getElementById('end-stats');
    const timerCountdownEl = document.getElementById('timer-countdown');
    const gameIdBadge = document.getElementById('game-id-badge');
    const replayNotice = document.getElementById('replay-notice');

    // Help Modal elements
    const helpButton = document.getElementById('help-button');
    const helpModal = document.getElementById('help-modal');
    const closeHelpBtn = document.getElementById('close-help-btn');
    const closeModalX = document.querySelector('.close-modal');
    const hintButton = document.getElementById('hint-button');

    const MAX_GUESSES = 10;

    // Game ID system — epoch = 2026-04-10, so ID 1 = April 11 2026
    const EPOCH = new Date(Date.UTC(2026, 3, 10)); // month is 0-indexed
    function getGameId(forDate) {
        const d = Date.UTC(forDate.getFullYear(), forDate.getMonth(), forDate.getDate());
        return Math.floor((d - EPOCH) / 86400000);
    }

    let gameData = null;       // the selected movie object
    let currentReviewIndex = 0;
    let guessesMade = 0;
    let guessHistory = [];     // 'correct', 'wrong', 'skip'
    let isGameOver = false;
    let hasWon = false;
    let hintRevealed = false;
    let activeGameId = null;   // the game ID currently being played

    // Get the current day name
    function getCurrentDayName() {
        return new Date().toLocaleDateString('en-US', { weekday: 'long' }).toLowerCase();
    }

    // Data URLs
    const isLocal = ['localhost', '127.0.0.1', '[::]', ''].includes(window.location.hostname);
    const DATA_URL = isLocal
        ? 'movie_data.json'
        : 'https://raw.githubusercontent.com/kpj/Letterguessd/data/movie_data.json';
    const HISTORY_URL = isLocal
        ? 'history.json'
        : 'https://raw.githubusercontent.com/kpj/Letterguessd/data/history.json';

    // Parse requested game ID from URL (?id=N), falling back to today
    const todayId = getGameId(new Date());
    const urlParams = new URLSearchParams(window.location.search);
    const requestedId = urlParams.has('id') ? parseInt(urlParams.get('id'), 10) : todayId;
    const isToday = requestedId === todayId;

    function setGameIdBadge(id) {
        if (gameIdBadge) gameIdBadge.textContent = `Game #${id}`;
    }

    function setReplayNotice(gameEntry) {
        if (!replayNotice) return;
        const d = new Date(gameEntry.date + 'T00:00:00Z');
        const label = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
        replayNotice.innerHTML = `
            <span>Replaying game from ${label}</span>
            <a href="${window.location.pathname}" class="today-link">Play Today</a>
        `;
        replayNotice.classList.remove('hidden');
    }

    function initFromData(entry) {
        gameData = entry;
        activeGameId = entry.id ?? requestedId;
        setGameIdBadge(activeGameId);
        initGame();
    }

    function showLoadError(msg) {
        console.error('Game Load Error:', msg);
    }

    // Two-phase data lookup:
    // 1. Today's game → fast path via movie_data.json
    // 2. Past game    → look up in history.json by ID
    if (isToday) {
        fetch(DATA_URL)
            .then(res => res.json())
            .then(data => {
                if (!data.movies || Object.keys(data.movies).length === 0) {
                    throw new Error('No movies found in data.');
                }
                const dayName = getCurrentDayName();
                const gameDataList = data.movies[dayName];

                // Determine the week number
                const now = new Date();
                const start = new Date(now.getFullYear(), 0, 0);
                const diff = now - start;
                const weekNum = Math.floor(diff / (1000 * 60 * 60 * 24 * 7));
                const entry = gameDataList[weekNum % gameDataList.length];

                if (!entry) {
                    throw new Error(`No movies found for today (${dayName}).`);
                }
                // Inject the ID so downstream code can reference it
                entry.id = todayId;
                initFromData(entry);
            })
            .catch(err => {
                console.error('Failed to load movie data:', err);
                showLoadError('Error loading game data. Please try again later.');
            });
    } else {
        // Past game — look up by ID in history.json
        setGameIdBadge(requestedId);
        fetch(HISTORY_URL)
            .then(res => res.json())
            .then(data => {
                const games = data.games || [];
                const entry = games.find(g => g.id === requestedId);
                if (!entry) {
                    throw new Error(`Game #${requestedId} not found.`);
                }
                setReplayNotice(entry);
                initFromData(entry);
            })
            .catch(err => {
                console.error('Failed to load history:', err);
                showLoadError(`Game #${requestedId} not found. Past games are added to the archive after they have been played.`);
            });
    }

    function startTimer() {
        function updateTimer() {
            const now = new Date();
            // Next midnight in local time
            const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
            const diff = tomorrow - now;

            if (diff <= 0) {
                timerCountdownEl.textContent = '00:00:00';
                return;
            }

            const h = Math.floor(diff / (1000 * 60 * 60));
            const m = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
            const s = Math.floor((diff % (1000 * 60)) / 1000);

            const display = [h, m, s].map(v => v.toString().padStart(2, '0')).join(':');
            if (timerCountdownEl) {
                timerCountdownEl.textContent = display;
            }
        }

        updateTimer();
        setInterval(updateTimer, 1000);
    }

    startTimer();

    function scrollToBottom(el) {
        if (!el) return;
        // We use a slight timeout to ensure the DOM has updated and style reflows are done
        setTimeout(() => {
            el.scrollIntoView({
                behavior: 'smooth',
                block: 'end'
            });
        }, 50);
    }

    function initGame() {
        updateGuessesDisplay();
        revealNextReview();
    }

    function revealNextReview() {
        if (currentReviewIndex < gameData.reviews.length) {
            const review = gameData.reviews[currentReviewIndex];

            const card = document.createElement('div');
            card.className = 'review-card';

            const textEl = document.createElement('div');
            textEl.className = 'review-text';
            textEl.innerHTML = review.text;

            const authorEl = document.createElement('div');
            authorEl.className = 'review-author';
            authorEl.textContent = review.author;

            card.appendChild(textEl);
            card.appendChild(authorEl);
            reviewsContainer.appendChild(card);

            scrollToBottom(card);

            currentReviewIndex++;
        }
    }

    function normalizeTitle(title) {
        if (!title) return '';
        return title
            .toLowerCase()
            .replace(/[^\w\s\d]/gi, '')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function handleGuess(isSkip = false) {
        if (isGameOver) return;

        const guess = guessInput.value.trim();
        if (!guess && !isSkip) return; // ignore empty submit

        guessesMade++;
        guessInput.value = '';

        const targetTitle = normalizeTitle(gameData.title);
        const guessedTitle = normalizeTitle(guess);

        let correct = false;
        if (!isSkip) {
            // Prioritize absolute matches and valid substrings
            if (guessedTitle === targetTitle || (guessedTitle.length > 5 && targetTitle.includes(guessedTitle))) {
                correct = true;
            } else if (typeof Fuse !== 'undefined') {
                // Typo tolerance via Fuse.js
                const fuse = new Fuse([targetTitle], {
                    includeScore: true,
                    threshold: 0.3, // 0.0 is perfect match, 1.0 is anything
                    ignoreLocation: true
                });
                const result = fuse.search(guessedTitle);
                if (result.length > 0) {
                    correct = true;
                }
            }
        }

        guessHistory.push({
            type: correct ? 'correct' : isSkip ? 'skip' : 'wrong',
            title: isSkip ? 'Skipped' : guess
        });
        updateGuessesDisplay();

        if (correct) {
            endGame(true);
            return;
        }

        // Add a guess card to the board (if not correct)
        const guessCard = document.createElement('div');
        guessCard.className = `guess-card is-${isSkip ? 'skip' : 'wrong'}`;

        const statusIcon = document.createElement('span');
        statusIcon.className = 'guess-status';
        statusIcon.textContent = isSkip ? '⏭️' : '❌';

        const guessText = document.createElement('span');
        guessText.textContent = isSkip ? 'Skipped' : guess;

        guessCard.appendChild(statusIcon);
        guessCard.appendChild(guessText);
        reviewsContainer.appendChild(guessCard);

        scrollToBottom(guessCard);

        if (guessesMade >= MAX_GUESSES) {
            endGame(false);
            return;
        }



        if (currentReviewIndex < gameData.reviews.length) {
            revealNextReview();
        }

        // Show hints after the first interaction
        if (hintsContainer) hintsContainer.classList.remove('hidden');
    }

    function handleHint() {
        if (isGameOver || hintRevealed || guessesMade >= MAX_GUESSES - 1) return;

        guessesMade++;
        hintRevealed = true;
        updateGuessesDisplay();

        guessHistory.push({
            type: 'hint',
            title: 'Extra Hint'
        });

        const genres = gameData.genres.slice(0, 3).join(', ') || 'N/A';
        const year = gameData.year || 'N/A';

        // 1. Action Card (Small pill)
        const statusCard = document.createElement('div');
        statusCard.className = 'guess-card is-hint';
        statusCard.innerHTML = `
            <span class="guess-status">💡</span>
            <span>Extra Hint</span>
        `;
        reviewsContainer.appendChild(statusCard);

        // 2. Content Card (Main boxed layout)
        const contentCard = document.createElement('div');
        contentCard.className = 'review-card hint-card';
        contentCard.innerHTML = `
            <div class="hint-display">
                <div class="hint-item">
                    <span class="hint-label">Release Year</span>
                    <span class="hint-value">${year}</span>
                </div>
                <div class="hint-item">
                    <span class="hint-label">Genres</span>
                    <span class="hint-value">${genres}</span>
                </div>
            </div>
        `;
        reviewsContainer.appendChild(contentCard);

        hintButton.classList.add('hidden'); // Only one hint allowed

        scrollToBottom(contentCard);

        // If we ran out of guesses via hint
        if (guessesMade >= MAX_GUESSES) {
            endGame(false);
        }

        // Feedback

    }

    function updateGuessesDisplay() {
        guessesRemainingEl.textContent = MAX_GUESSES - guessesMade;
    }

    function endGame(won) {
        isGameOver = true;
        hasWon = won;
        guessArea.classList.add('hidden');
        endScreen.classList.remove('hidden');

        if (won) {
            endTitle.textContent = 'Excellent!';
            endTitle.style.color = 'var(--lb-green)';
        } else {
            endTitle.textContent = 'Game Over';
            endTitle.style.color = 'var(--error-color)';
        }

        movieTitleName.textContent = `${gameData.title} (${gameData.year})`;
        movieTitleLink.href = gameData.link;

        // Show movie poster if available
        if (gameData.poster) {
            moviePoster.src = gameData.poster;
            moviePoster.classList.remove('hidden');
        }

        const guessWord = guessesMade === 1 ? 'guess' : 'guesses';
        endStats.innerHTML = `<p>You used ${guessesMade} ${guessWord} out of ${MAX_GUESSES}.</p>`;

        // Render the emoji grid inline in the end screen
        sharePreview.textContent = buildSquares();

        // Scroll so the top of the result is visible
        setTimeout(() => {
            endScreen.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }, 100);
    }

    function buildSquares() {
        const squares = [];
        for (let i = 0; i < MAX_GUESSES; i++) {
            const h = guessHistory[i];
            if (h) {
                if (h.type === 'correct') squares.push('🟩');
                else if (h.type === 'hint') squares.push('🔍');
                else if (h.type === 'wrong' || h.type === 'skip') squares.push('🟥');
            } else {
                squares.push('⬜');
            }
        }
        return squares.join('');
    }

    function generateShareText() {
        const score = hasWon ? guessesMade : 'X';
        const id = activeGameId ?? requestedId;
        const base = window.location.origin + window.location.pathname;
        const shareUrl = `${base}?id=${id}`;
        return `Letterguessd #${id}: ${score}/${MAX_GUESSES}\n${buildSquares()}\n${shareUrl}`;
    }

    guessForm.addEventListener('submit', e => {
        e.preventDefault();
        handleGuess(false);
    });

    skipButton.addEventListener('click', e => {
        e.preventDefault();
        handleGuess(true);
    });

    hintButton.addEventListener('click', e => {
        e.preventDefault();
        handleHint();
    });

    shareButton.addEventListener('click', () => {
        const text = generateShareText();
        navigator.clipboard.writeText(text).then(() => {
            shareToast.classList.remove('hidden');
            setTimeout(() => shareToast.classList.add('hidden'), 2500);
        });
    });

    // Help Modal Logic
    if (helpButton && helpModal) {
        helpButton.addEventListener('click', () => {
            helpModal.classList.remove('hidden');
        });
    }

    const closeHelp = () => {
        if (helpModal) helpModal.classList.add('hidden');
    };
    closeHelpBtn.addEventListener('click', closeHelp);
    closeModalX.addEventListener('click', closeHelp);
    window.addEventListener('click', (e) => {
        if (e.target === helpModal) closeHelp();
    });
});
