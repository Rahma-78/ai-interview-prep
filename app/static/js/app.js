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

    // Generate a random client ID
    const clientId = 'client_' + Math.random().toString(36).substr(2, 9);

    // Connect to WebSocket
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/v1/ws/${clientId}`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
        const message = event.data;
        if (message === 'step_1') {
            updateProgress(1);
        } else if (message === 'step_2') {
            updateProgress(2);
            updateProgress(2);
            // Keep loading section visible during search
            // We will switch to results when the first data chunk arrives
        } else if (message === 'step_3') {
            updateProgress(3);
        }
    };

    // Drag & Drop handlers
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        dropArea.addEventListener(eventName, highlight, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, unhighlight, false);
    });

    function highlight(e) {
        dropArea.classList.add('dragover');
    }

    function unhighlight(e) {
        dropArea.classList.remove('dragover');
    }

    dropArea.addEventListener('drop', handleDrop, false);

    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles(files);
    }

    fileInput.addEventListener('change', function () {
        handleFiles(this.files);
    });

    function handleFiles(files) {
        if (files.length > 0) {
            const file = files[0];
            if (file.type === 'application/pdf') {
                currentFile = file;
                showFileInfo(file.name);
            } else {
                alert('Please upload a PDF file.');
            }
        }
    }

    function showFileInfo(name) {
        filenameDisplay.textContent = name;
        dropArea.classList.add('hidden');
        fileInfo.classList.remove('hidden');
        analyzeBtn.classList.remove('hidden');
    }

    removeFileBtn.addEventListener('click', () => {
        currentFile = null;
        fileInput.value = '';
        fileInfo.classList.add('hidden');
        analyzeBtn.classList.add('hidden');
        dropArea.classList.remove('hidden');
        resultsSection.classList.add('hidden');
    });

    analyzeBtn.addEventListener('click', async () => {
        if (!currentFile) return;

        // UI State: Loading
        analyzeBtn.classList.add('hidden');
        loadingSection.classList.remove('hidden');
        resultsSection.classList.add('hidden');
        questionsContainer.innerHTML = '';

        // Initial state
        updateProgress(0);

        const formData = new FormData();
        formData.append('resume_file', currentFile);
        formData.append('client_id', clientId);

        try {
            // Start the actual request
            const response = await fetch('/api/v1/generate-questions/', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error('Analysis failed');
            }

            // Handle NDJSON streaming response
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();

                if (done) break;

                // Decode chunk and add to buffer
                buffer += decoder.decode(value, { stream: true });

                // Process complete lines (NDJSON - one JSON object per line)
                const lines = buffer.split('\n');
                buffer = lines.pop(); // Keep incomplete line in buffer

                for (const line of lines) {
                    if (line.trim()) {
                        // Robust parsing for potentially concatenated JSON objects (e.g., {...}{...})
                        let remaining = line.trim();
                        while (remaining) {
                            try {
                                // Try parsing the whole thing first
                                const data = JSON.parse(remaining);
                                appendResult(data);
                                remaining = ''; // Done
                            } catch (e) {
                                // If it fails, it might be multiple objects concatenated
                                // Try to find the first valid JSON object
                                let found = false;
                                for (let i = 1; i < remaining.length; i++) {
                                    if (remaining[i] === '}') {
                                        const potential = remaining.substring(0, i + 1);
                                        try {
                                            const data = JSON.parse(potential);
                                            appendResult(data);
                                            remaining = remaining.substring(i + 1).trim();
                                            found = true;
                                            break;
                                        } catch (err) {
                                            // Not a valid object yet, continue
                                        }
                                    }
                                }
                                if (!found) {
                                    console.error('Failed to parse line segment:', remaining);
                                    console.warn('Full buffer content:', JSON.stringify(buffer));
                                    remaining = ''; // Stop infinite loop
                                }
                            }
                        }
                    }
                }
            }

            // Stream completed successfully
            updateProgress(3);
            setTimeout(() => {
                loadingSection.classList.add('hidden');
                resultsSection.classList.remove('hidden');
                analyzeBtn.classList.remove('hidden');
                analyzeBtn.innerHTML = '<i class="fa-solid fa-rotate-right"></i> Analyze Another Resume';

                // Clear current file so the main click listener returns early
                currentFile = null;

                analyzeBtn.onclick = () => {
                    window.location.reload();
                }
            }, 500);

        } catch (error) {
            console.error('Error:', error);
            alert('An error occurred while processing your resume. Please try again.');
            loadingSection.classList.add('hidden');
            analyzeBtn.classList.remove('hidden');
        }
    });

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

    function appendResult(item) {
        // Show results section when the first data arrives
        if (resultsSection.classList.contains('hidden')) {
            loadingSection.classList.add('hidden');
            resultsSection.classList.remove('hidden');
            analyzeBtn.classList.remove('hidden');
        }

        // Check if already exists (optional, but good for safety)

        const card = document.createElement('div');
        card.className = 'skill-card';
        card.style.animation = 'slideUp 0.5s ease';

        const questionsHtml = item.questions.map((q, i) => `
            <li class="question-item">
                <span class="question-number">${i + 1}.</span>
                <span class="question-text">${q}</span>
            </li>
        `).join('');

        card.innerHTML = `
            <div class="skill-header">
                <span class="skill-name"><i class="fa-solid fa-code"></i> ${item.skill}</span>
            </div>
            <ul class="question-list">
                ${questionsHtml}
            </ul>
        `;

        questionsContainer.appendChild(card);
    }
});
