document.addEventListener('DOMContentLoaded', () => {
    const reviewsContainer = document.getElementById('reviews-container');
    const guessForm = document.getElementById('guess-form');
    const guessInput = document.getElementById('guess-input');
    const skipButton = document.getElementById('skip-button');
    const guessesRemainingEl = document.querySelector('#guesses-remaining .highlight');
    const feedbackMessage = document.getElementById('feedback-message');
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

    // Help Modal elements
    const helpButton = document.getElementById('help-button');
    const helpModal = document.getElementById('help-modal');
    const closeHelpBtn = document.getElementById('close-help-btn');
    const closeModalX = document.querySelector('.close-modal');

    const MAX_GUESSES = 10;

    let gameData = null;       // the selected movie object
    let currentReviewIndex = 0;
    let guessesMade = 0;
    let guessHistory = [];     // 'correct', 'wrong', 'skip'
    let isGameOver = false;
    let hasWon = false;

    // Get the current day name
    function getCurrentDayName() {
        return new Date().toLocaleDateString('en-US', { weekday: 'long' }).toLowerCase();
    }

    // Load data
    const isLocal = ['localhost', '127.0.0.1', '[::]', ''].includes(window.location.hostname);
    const DATA_URL = isLocal
        ? 'movie_data.json'
        : 'https://raw.githubusercontent.com/kpj/Letterguessd/data/movie_data.json';

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
            gameData = gameDataList[weekNum % gameDataList.length];

            if (!gameData) {
                throw new Error(`No movies found for this day: ${dayName}.`);
            }

            // We expect 10 reviews from the scraper
            initGame();
        })
        .catch(err => {
            console.error('Failed to load movie data:', err);
            feedbackMessage.textContent = 'Error loading game data. Please try again later.';
            feedbackMessage.className = 'feedback-error';
        });

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

            // Scroll to the new card smoothly
            setTimeout(() => card.scrollIntoView({ behavior: 'smooth', block: 'end' }), 50);

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

        if (guessesMade >= MAX_GUESSES) {
            endGame(false);
            return;
        }

        // Wrong/skip — show feedback and reveal next review
        feedbackMessage.textContent = isSkip ? 'Next hint revealed.' : `"${guess}" is incorrect.`;
        feedbackMessage.className = 'feedback-error';
        setTimeout(() => feedbackMessage.classList.add('hidden'), 2000);

        if (currentReviewIndex < gameData.reviews.length) {
            revealNextReview();
        }
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
    }

    function buildSquares() {
        const squares = [];
        for (let i = 0; i < MAX_GUESSES; i++) {
            const h = guessHistory[i];
            if (h) {
                if (h.type === 'correct') squares.push('🟩');
                else if (h.type === 'wrong' || h.type === 'skip') squares.push('🟥');
            } else {
                squares.push('⬜');
            }
        }
        return squares.join('');
    }

    function generateShareText() {
        const score = hasWon ? guessesMade : 'X';
        return `Letterguessd ${score}/${MAX_GUESSES}\n${buildSquares()}\n${window.location.href}`;
    }

    guessForm.addEventListener('submit', e => {
        e.preventDefault();
        handleGuess(false);
    });

    skipButton.addEventListener('click', e => {
        e.preventDefault();
        handleGuess(true);
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
