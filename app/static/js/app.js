document.addEventListener('DOMContentLoaded', () => {
    const dropArea = document.getElementById('drop-area');
    const fileInput = document.getElementById('resume-file');
    const fileInfo = document.getElementById('file-info');
    const filenameDisplay = document.getElementById('filename');
    const removeFileBtn = document.getElementById('remove-file');
    const analyzeBtn = document.getElementById('analyze-btn');
    const loadingSection = document.getElementById('loading-section');
    const resultsSection = document.getElementById('results-section');
    const questionsContainer = document.getElementById('questions-container');
    const loadingText = document.getElementById('loading-text');

    let currentFile = null;
    let allResults = []; // Store all results for download

    // Generate a random client ID
    const clientId = 'client_' + Math.random().toString(36).substr(2, 9);

    // Connect to WebSocket
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/v1/ws/${clientId}`;
    const ws = new WebSocket(wsUrl);

    // Track progress state
    let totalBatches = 0;
    let completedBatches = 0;

    ws.onmessage = (event) => {
        const message = event.data;

        // Handle standard step transitions
        if (message === 'step_1') {
            updateProgress(1);
        } else if (message === 'step_2') {
            updateProgress(2);
        } else if (message === 'step_2_complete') {
            // Mark step 2 as completed (green) when sources are actually found
            document.querySelectorAll('.step')[1].classList.add('completed');
            document.querySelectorAll('.step')[1].classList.remove('active');
        } else if (message === 'step_3') {
            updateProgress(3);
            // Reset batch tracking
            completedBatches = 0;
        } else {
            // Handle granular status updates
            if (loadingText) {
                // Extract batch info if present (format: "Processing Batch X/Y...")
                const batchMatch = message.match(/Batch (\d+)\/(\d+)/);
                if (batchMatch) {
                    const currentBatch = parseInt(batchMatch[1]);
                    totalBatches = parseInt(batchMatch[2]);

                    // Update progress bar based on batch completion
                    if (message.includes('Completed') || message.includes('Generated questions')) {
                        completedBatches = Math.min(completedBatches + 1, totalBatches);
                        const progress = Math.round((completedBatches / totalBatches) * 100);
                        updateProgressPercentage(progress);
                    }
                }

                loadingText.textContent = message;
                loadingText.classList.remove('pulse');
                void loadingText.offsetWidth; // trigger reflow
                loadingText.classList.add('pulse');
            }
        }
    };

    // --- Event Listeners ---

    // Drag & Drop
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, e => {
            e.preventDefault();
            e.stopPropagation();
        }, false);
    });

    ['dragenter', 'dragover'].forEach(() => dropArea.classList.add('dragover'));
    ['dragleave', 'drop'].forEach(() => dropArea.classList.remove('dragover'));

    dropArea.addEventListener('drop', e => handleFiles(e.dataTransfer.files), false);
    fileInput.addEventListener('change', e => handleFiles(e.target.files));

    // File Management
    removeFileBtn.addEventListener('click', resetFileSelection);

    // Analysis
    analyzeBtn.addEventListener('click', startAnalysis);

    // --- Core Functions ---

    function handleFiles(files) {
        if (!files.length) return;
        const file = files[0];

        if (file.type !== 'application/pdf') {
            alert('Please upload a PDF file.');
            return;
        }

        currentFile = file;
        filenameDisplay.textContent = file.name;
        toggleView('file-selected');
    }

    function resetFileSelection() {
        currentFile = null;
        fileInput.value = '';
        toggleView('initial');
    }

    function toggleView(state) {
        const isSelected = state === 'file-selected';
        const isAnalyzing = state === 'analyzing';
        const isComplete = state === 'complete';

        // Elements visibility toggling
        dropArea.classList.toggle('hidden', isSelected || isAnalyzing || isComplete);
        fileInfo.classList.toggle('hidden', !isSelected && !isAnalyzing && !isComplete);
        analyzeBtn.classList.toggle('hidden', !isSelected && !isComplete);
        loadingSection.classList.toggle('hidden', !isAnalyzing);
        resultsSection.classList.toggle('hidden', !isComplete && !resultsSection.classList.contains('hidden')); // Keep visible if we appended results

        if (state === 'initial') {
            resultsSection.classList.add('hidden');
        }
    }

    async function startAnalysis() {
        if (!currentFile) return;

        toggleView('analyzing');
        questionsContainer.innerHTML = '';
        allResults = []; // Reset results for new analysis
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
                // Show download button if we have results
                if (allResults.length > 0) {
                    createDownloadButton();
                }

                analyzeBtn.innerHTML = '<i class="fa-solid fa-rotate-right"></i> Analyze Another Resume';
                analyzeBtn.classList.remove('hidden');
                loadingSection.classList.add('hidden');

                // Fix: Properly handle button reset
                // Remove the old 'click' listener to prevent re-submitting immediately if clicked
                analyzeBtn.removeEventListener('click', startAnalysis);

                // Add new listener for reload
                analyzeBtn.onclick = () => window.location.reload();
            }, 500);

        } catch (error) {
            console.error('Error:', error);
            alert('An error occurred. Please try again.');
            loadingSection.classList.add('hidden');
            analyzeBtn.classList.remove('hidden');
        }
    }

    async function readStream(reader) {
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Keep incomplete line

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
    }

    function updateProgress(step) {
        document.querySelectorAll('.step').forEach((el, index) => {
            if (index + 1 < step) {
                el.classList.add('completed');
                el.classList.remove('active');
            } else if (index + 1 === step) {
                el.classList.add('active');
                el.classList.remove('completed');
            } else {
                el.classList.remove('active', 'completed');
            }
        });

        const texts = [
            "Extracting Skills from Resume...",
            "Discovering Technical Sources...",
            "Generating Interview Questions..."
        ];
        if (step > 0) {
            loadingText.textContent = texts[step - 1];
        } else {
            loadingText.textContent = "Starting analysis...";
        }
    }

    function updateProgressPercentage(percentage) {
        // Update step 3 indicator with percentage
        const step3 = document.querySelectorAll('.step')[2];
        if (step3 && percentage > 0) {
            // Preserve the icon and text, just append/update percentage
            // We assume the original HTML is something like <i class="..."></i> Generating Questions
            // We want: <i class="..."></i> Generating Questions (50%)

            // Check if we already added a percentage span
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

    function appendResult(item) {
        // Show results section when the first data arrives
        if (resultsSection.classList.contains('hidden')) {
            loadingSection.classList.add('hidden');
            resultsSection.classList.remove('hidden');
            analyzeBtn.classList.remove('hidden');
        }

        // Fix: Only render card if there are valid questions
        if (!item.questions || item.questions.length === 0) {
            console.warn(`Skipping display for skill '${item.skill}': No questions generated.`);
            return;
        }

        // Store result for download
        allResults.push({
            skill: item.skill,
            questions: item.questions
        });

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
                <ul class="question-list">
                    ${questionsHtml}
                </ul>
            </div>
        `;

        // Add accordion toggle functionality
        const header = card.querySelector('.skill-header');
        header.addEventListener('click', () => {
            card.classList.toggle('active');
        });

        questionsContainer.appendChild(card);

        // Auto-open the first result to show user what's happening
        if (questionsContainer.children.length === 1) {
            setTimeout(() => card.classList.add('active'), 100);
        }
    }

    function createDownloadButton() {
        // Check if button already exists
        if (document.getElementById('download-btn')) return;

        const downloadBtn = document.createElement('button');
        downloadBtn.id = 'download-btn';
        downloadBtn.className = 'btn btn-secondary';
        downloadBtn.innerHTML = '<i class="fa-solid fa-download"></i> Download Results (TXT)';
        downloadBtn.style.marginLeft = '10px';

        downloadBtn.addEventListener('click', async () => {
            try {
                const filename = currentFile ? currentFile.name.replace('.pdf', '') : 'resume';

                const response = await fetch('/api/v1/download-results', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        results: allResults,
                        filename: filename
                    })
                });

                if (!response.ok) throw new Error('Download failed');

                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;

                // Get filename from Content-Disposition header or generate one
                const contentDisposition = response.headers.get('Content-Disposition');
                let downloadFilename = `${filename}_results.txt`;

                if (contentDisposition) {
                    const filenameMatch = contentDisposition.match(/filename="(.+)"/i);
                    if (filenameMatch) {
                        downloadFilename = filenameMatch[1];
                    }
                }

                a.download = downloadFilename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);

                console.log('Download complete:', downloadFilename);
            } catch (error) {
                console.error('Download error:', error);
                alert('Failed to download results. Please try again.');
            }
        });

        // Insert button next to the analyze button
        analyzeBtn.parentNode.insertBefore(downloadBtn, analyzeBtn.nextSibling);
    }
});
