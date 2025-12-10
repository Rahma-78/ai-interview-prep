document.addEventListener('DOMContentLoaded', () => {
    // --- 1. Centralized DOM Elements (Optimization) ---
    const elements = {
        dropArea: document.getElementById('drop-area'),
        fileInput: document.getElementById('resume-file'),
        fileInfo: document.getElementById('file-info'),
        filenameDisplay: document.getElementById('filename'),
        removeFileBtn: document.getElementById('remove-file'),
        analyzeBtn: document.getElementById('analyze-btn'),
        loadingSection: document.getElementById('loading-section'),
        resultsSection: document.getElementById('results-section'),
        questionsContainer: document.getElementById('questions-container'),
        loadingText: document.getElementById('loading-text'),
        steps: document.querySelectorAll('.step')
    };

    const stepTexts = [
        "Extracting Skills from Resume...",
        "Discovering Technical Sources...",
        "Generating Interview Questions..."
    ];

    let currentFile = null;
    let allResults = [];
    let totalBatches = 0;
    let completedBatches = 0;

    // Generate Client ID
    const clientId = 'client_' + Math.random().toString(36).substr(2, 9);

    // --- 2. Simplified WebSocket Handling (Refactor) ---
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/v1/ws/${clientId}`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
        const message = event.data;

        if (message.startsWith('step_')) {
            const step = parseInt(message.replace('step_', '').replace('_complete', ''));
            // Check if it's a valid number, otherwise it might be a status
            if (!isNaN(step)) {
                handleStepMessage(step, message.includes('_complete'));
            }
        } else if (elements.loadingText) {
            handleStatusMessage(message);
        }
    };

    function handleStepMessage(step, isComplete) {
        updateProgress(step);

        if (isComplete && step === 2) {
            elements.steps[1].classList.add('completed');
            elements.steps[1].classList.remove('active');
            completedBatches = 0; // Reset for step 3
        }
    }

    function handleStatusMessage(message) {
        // Extract batch info
        const batchMatch = message.match(/Batch (\d+)\/(\d+)/);
        if (batchMatch) {
            // totalBatches = parseInt(batchMatch[2]); // Update total if needed
            totalBatches = parseInt(batchMatch[2]);

            if (message.includes('Completed') || message.includes('Generated questions')) {
                updateBatchProgress();
            }
        }

        elements.loadingText.textContent = message;
        elements.loadingText.classList.remove('pulse');
        void elements.loadingText.offsetWidth; // trigger reflow
        elements.loadingText.classList.add('pulse');
    }

    function updateBatchProgress() {
        completedBatches = Math.min(completedBatches + 1, totalBatches);
        const progress = totalBatches > 0 ? Math.round((completedBatches / totalBatches) * 100) : 0;
        updateProgressPercentage(progress);
    }

    // --- Event Listeners ---

    // Drag & Drop
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        elements.dropArea.addEventListener(eventName, e => {
            e.preventDefault();
            e.stopPropagation();
        }, false);
    });

    ['dragenter', 'dragover'].forEach(() => elements.dropArea.classList.add('dragover'));
    ['dragleave', 'drop'].forEach(() => elements.dropArea.classList.remove('dragover'));

    elements.dropArea.addEventListener('drop', e => handleFiles(e.dataTransfer.files), false);
    elements.fileInput.addEventListener('change', e => handleFiles(e.target.files));

    elements.removeFileBtn.addEventListener('click', resetFileSelection);
    elements.analyzeBtn.addEventListener('click', startAnalysis);

    // --- Core Functions ---

    function handleFiles(files) {
        if (!files.length) return;
        const file = files[0];

        if (file.type !== 'application/pdf') {
            alert('Please upload a PDF file.');
            return;
        }

        currentFile = file;
        elements.filenameDisplay.textContent = file.name;
        toggleView('file-selected');
    }

    function resetFileSelection() {
        currentFile = null;
        elements.fileInput.value = '';
        toggleView('initial');
    }

    // --- 3. Efficient View & Progress Toggling (Refactor) ---
    function toggleView(state) {
        const viewStates = {
            'initial': { dropArea: false, fileInfo: false, analyzeBtn: false, loadingSection: true, resultsSection: true },
            'file-selected': { dropArea: true, fileInfo: false, analyzeBtn: false, loadingSection: true, resultsSection: true },
            'analyzing': { dropArea: true, fileInfo: true, analyzeBtn: true, loadingSection: false, resultsSection: true },
            'complete': { dropArea: true, fileInfo: true, analyzeBtn: false, loadingSection: true, resultsSection: false }
        };

        const visibility = viewStates[state] || viewStates['initial'];

        Object.entries(visibility).forEach(([elementKey, isHidden]) => {
            if (elements[elementKey]) {
                elements[elementKey].classList.toggle('hidden', isHidden);
            }
        });

        // Special case: Ensure results hidden on initial
        if (state === 'initial') {
            elements.resultsSection.classList.add('hidden');
        }
    }

    function updateProgress(step) {
        elements.steps.forEach((el, index) => {
            const isCompleted = index + 1 < step;
            const isActive = index + 1 === step;

            el.classList.toggle('completed', isCompleted);
            el.classList.toggle('active', isActive);
            if (!isCompleted && !isActive) {
                el.classList.remove('completed', 'active');
            }
        });

        if (step > 0) {
            elements.loadingText.textContent = stepTexts[step - 1];
        } else {
            elements.loadingText.textContent = "Starting analysis...";
        }
    }

    function updateProgressPercentage(percentage) {
        const step3 = elements.steps[2];
        if (step3 && percentage > 0) {
            let percentSpan = step3.querySelector('.progress-percent');
            if (!percentSpan) {
                percentSpan = document.createElement('span');
                percentSpan.className = 'progress-percent';
                percentSpan.style.marginLeft = '5px';
                step3.appendChild(percentSpan);
            }
            percentSpan.textContent = `(${percentage}%)`;
            step3.style.setProperty('--progress', `${percentage}%`);
        }
    }

    async function startAnalysis() {
        if (!currentFile) return;

        toggleView('analyzing');
        elements.questionsContainer.innerHTML = '';
        allResults = [];
        updateProgress(0);

        const formData = new FormData();
        formData.append('resume_file', currentFile);
        formData.append('client_id', clientId);

        try {
            const response = await fetch('/api/v1/generate-questions/', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) throw new Error('Analysis failed');

            await readStream(response.body.getReader());

            // Completion state
            updateProgress(3);
            setTimeout(() => {
                if (allResults.length > 0) {
                    createDownloadButton();
                }

                elements.analyzeBtn.innerHTML = '<i class="fa-solid fa-rotate-right"></i> Analyze Another Resume';
                elements.analyzeBtn.classList.remove('hidden');
                elements.loadingSection.classList.add('hidden');

                elements.analyzeBtn.removeEventListener('click', startAnalysis);
                elements.analyzeBtn.onclick = () => window.location.reload();
            }, 500);

        } catch (error) {
            console.error('Error:', error);
            alert('An error occurred. Please try again.');
            elements.loadingSection.classList.add('hidden');
            elements.analyzeBtn.classList.remove('hidden');
        }
    }

    // --- 4. Stream Processing (Refactor) ---
    async function readStream(reader) {
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Safe buffering: split lines, keep the last incomplete chunk
            const lines = buffer.split('\n');
            buffer = lines.pop();

            processLines(lines);
        }

        // Process any remaining buffer
        if (buffer && buffer.trim()) {
            processLines([buffer]);
        }
    }

    function processLines(lines) {
        for (const line of lines) {
            if (line.trim()) {
                try {
                    const data = JSON.parse(line);
                    appendResult(data);
                } catch (e) {
                    console.error('JSON Parse Error:', e);
                }
            }
        }
    }

    // --- 5. Result Handling & Errors (Refactor) ---
    function appendResult(item) {
        // Handle errors first
        if (isQuotaError(item)) {
            displayQuotaError(getQuotaErrorMessage(item));
            return;
        }

        // Skip empty results
        if (!item.questions || item.questions.length === 0) return;

        allResults.push(item);
        displayResult(item);
    }

    function displayResult(item) {
        // Create skill card structure that matches CSS
        const card = document.createElement('div');
        card.className = 'skill-card';
        card.style.animation = 'slideUp 0.5s ease backwards';

        const questionsHtml = item.questions.map((q, i) => `
            <li class="question-item">
                <span class="question-number">${i + 1}.</span>
                <span class="question-text">${q}</span>
            </li>
        `).join('');

        card.innerHTML = `
            <div class="skill-header">
                <span class="skill-name">
                    <i class="fa-solid fa-code"></i> ${item.skill}
                </span>
                <i class="fa-solid fa-chevron-down skill-toggle-icon"></i>
            </div>
            <div class="skill-content">
                <ul class="question-list">${questionsHtml}</ul>
            </div>
        `;

        // Add accordion toggle
        card.querySelector('.skill-header').addEventListener('click', () => {
            card.classList.toggle('active');
        });

        elements.questionsContainer.appendChild(card);

        // Show results section if it was hidden
        if (elements.resultsSection.classList.contains('hidden')) {
            elements.resultsSection.classList.remove('hidden');
        }
    }

    function isQuotaError(item) {
        return (
            item.type === 'quota_error' ||
            item.error_type === 'QuotaExhausted' ||
            item.error_type === 'quota_exhausted' ||
            (item.error && item.error.toLowerCase().includes('quota'))
        );
    }

    function getQuotaErrorMessage(item) {
        return item.error || 'Quota exceeded. Please try again later.';
    }

    function displayQuotaError(message) {
        // Prevent duplicate banners
        if (document.querySelector('.quota-error-banner')) return;

        const errorDiv = document.createElement('div');
        errorDiv.className = 'quota-error-banner';
        errorDiv.innerHTML = `
            <i class="fa-solid fa-triangle-exclamation"></i>
            <div class="quota-error-content">
                <strong>LLM API Limit Reached</strong>
                <p>${message}</p>
            </div>
        `;
        elements.questionsContainer.prepend(errorDiv);
        console.warn('Quota error displayed:', message);

        // Show results section if it was hidden
        if (elements.resultsSection.classList.contains('hidden')) {
            elements.resultsSection.classList.remove('hidden');
        }
    }

    function createDownloadButton() {
        const downloadBtn = document.createElement('button');
        downloadBtn.className = 'download-btn';
        downloadBtn.innerHTML = '<i class="fa-solid fa-download"></i> Download Results';
        downloadBtn.addEventListener('click', downloadResults);

        elements.resultsSection.appendChild(downloadBtn);
    }

    function downloadResults() {
        if (!allResults || allResults.length === 0) {
            alert('No results to download');
            return;
        }

        // Format the results properly with skill sections
        const resultsText = allResults.map(item => {
            const skillSection = `${'='.repeat(60)}\nSKILL: ${item.skill}\n${'='.repeat(60)}\n\n`;
            const questions = item.questions.map((q, i) =>
                `${i + 1}. ${q}`
            ).join('\n\n');
            return skillSection + questions + '\n\n';
        }).join('\n');

        const header = `AI INTERVIEW PREP - GENERATED QUESTIONS\n` +
            `Generated: ${new Date().toLocaleString()}\n` +
            `Total Skills: ${allResults.length}\n` +
            `${'='.repeat(60)}\n\n`;

        const fullText = header + resultsText;

        const blob = new Blob([fullText], { type: 'text/plain; charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `interview-questions-${new Date().toISOString().slice(0, 10)}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }
});