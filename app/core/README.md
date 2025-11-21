# Configuration

This application requires several environment variables to be set in order to function properly.

## Setup

1. Copy the `.env.example` file to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit the `.env` file and replace the placeholder values with your actual API keys:
   - `GEMINI_API_KEY`: Your Google Gemini API key
   - `SERPER_API_KEY`: Your Serper API key for web search
   - `GROQ_API_KEY`: Your Groq API key
   - `OPENROUTER_API_KEY`: Your OpenRouter API key

3. Optional settings:
   - `DEBUG_MODE`: Set to `true` for debug output (default: `false`)
   - `REQUESTS_PER_MINUTE`: Rate limit for API requests (default: `10`)
   - `CREWAI_TELEMETRY_OPT_OUT`: Set to `true` to opt out of CrewAI telemetry (default: `false`)

## API Keys

### Gemini API Key

To get a Gemini API key:

1. Visit the [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create a new API key
3. Copy the key to your `.env` file

### Serper API Key

To get a Serper API key:

1. Visit the [Serper website](https://serper.dev/)
2. Sign up for an account
3. Get your API key from the dashboard
4. Copy the key to your `.env` file

### Groq API Key

To get a Groq API key:

1. Visit the [Groq website](https://groq.com/)
2. Sign up for an account
3. Get your API key from the dashboard
4. Copy the key to your `.env` file

### OpenRouter API Key

To get an OpenRouter API key:

1. Visit the [OpenRouter website](https://openrouter.ai/)
2. Sign up for an account
3. Get your API key from the dashboard
4. Copy the key to your `.env` file