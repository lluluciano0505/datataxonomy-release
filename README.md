# DataTaxonomy

DataTaxonomy is a local desktop application for classifying architectural and urban-design project files. It scans a folder containing PDFs, drawings, spreadsheets, models, images, and documents, then produces a structured CSV catalogue and a local review dashboard.

This source release includes the application, tests and a clearly labelled synthetic demonstration archive. Real project files, experimental outputs, logs, saved profiles and development history are excluded.

## What is included

- Local four-layer processing pipeline
- Configuration wizard
- Local dashboard and review queue
- Generic taxonomy template
- Windows installer script
- Automated tests and offline Review reproduction script
- Synthetic demonstration files and a portable demo configuration

## What is not included

- Real client project files
- Experimental CSV results or run reports
- Previous processing logs
- Saved project profiles
- API keys
- Earlier development history or private development settings

## Requirements

- Windows 10 or Windows 11 for the one-click launcher; a Python environment for manual use on other platforms
- Python 3.10 or newer
- Internet access for package installation and the configured LLM provider
- An OpenRouter API key for the default configuration

## Installation and one-click startup

For a Windows user who has never used Python:

1. Extract this package to a local folder. Do not extract it into a client project folder or a cloud-synced folder while it is running.
2. Double-click `start_dashboard.bat`.
3. Wait while the installer finds or installs Python, creates a private virtual environment, and installs the packages. The first installation can take several minutes.
4. Enter the user's own API key when the setup dialog appears. The key is saved only in the local `.env` file.
5. The browser opens the setup page automatically. No terminal commands are required.
6. On later days, double-click `start_dashboard.bat` again. It reuses the installation and opens the Dashboard.

The installer creates a local `.env` and `config.yaml`. Both files are user-specific and must never be copied back into a release package.

Useful shortcuts:

- `start_dashboard.bat` — install if needed, start the local services, and open the correct browser page.
- `stop_dashboard.bat` — stop the local services before restarting or moving the package.
- Configuration page — `http://localhost:5173` (default).
- Dashboard — `http://localhost:5174` (default).

## First-time setup

The browser setup page walks through the process in order:

1. Choose an AI provider and model, paste the user's own API key, and click **Verify connection**.
2. Enter the project name, location, and date range. The URL autofill option is optional.
3. Click **Choose Folder…** to select the folder containing the project files. On Windows this opens the native folder picker.
4. Choose a small sample size for the first test, or leave it set to all files for a complete run.
5. Select or edit the taxonomy, review the summary, and save the project.
6. Start the pipeline from the project page. The results dashboard opens when processing is complete.

The application supports PDF, DOCX, PPTX, XLSX, TXT, PNG, JPG, DWG, IFC, and other formats listed in the setup page. Text PDFs and ordinary Office files work without extra system software. Tesseract OCR improves scanned/image-only PDF extraction; missing OCR is a warning, not an installation failure.

## Resuming an interrupted run

Full runs save a local checkpoint beside the configured output CSV. If processing is stopped or the application closes unexpectedly, reopen the Configuration page and choose **Resume** to continue the same project. Completed CSV rows are retained; cached extraction work is reused; files not yet fully classified are continued. Resume checks the saved file inventory, file size/modification signatures, project settings, selected model, and taxonomy. If those no longer match, restore the original inputs/settings or start a fresh run rather than mixing results.

Resume checkpoints contain extracted classification context and local file paths, but no API key. They are generated user data and must not be shared without review. A new full run replaces the current output; use Resume after interruption, and use Incremental only when intentionally adding new files to an existing output.

The command-line equivalent is:

```text
.venv\\Scripts\\python.exe main.py --resume
```

## Manual startup (troubleshooting only)

If the one-click launcher cannot be used, open a terminal in the package folder and run:

```text
.venv\Scripts\python.exe main.py --dashboard-only
```

Then open `http://localhost:5173`. Stop the services with `stop_dashboard.bat` or close the Python processes.

For a small first run, use the sample option in the wizard or run:

```text
.venv\Scripts\python.exe main.py --sample 20
```

## Command-line usage

```text
.venv\Scripts\python.exe main.py
.venv\Scripts\python.exe main.py --sample 20
.venv\Scripts\python.exe main.py --incremental
.venv\Scripts\python.exe main.py --rerun certainty=Low
.venv\Scripts\python.exe main.py --no-dashboard
```

## Tests and synthetic demonstration

Install the packages in `requirements.txt`, then run `python -m pytest -q` from the project root. The tests use temporary files and mocked API responses; they do not make paid model requests.

See [the demo instructions](demo_data/README.md) for the synthetic archive. It is not experimental client data or a substitute for the paper's project archives. The optional reference CSV is a previous synthetic demonstration result; model-generated outputs can vary between runs.

For manual setup on macOS or Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.yaml config.yaml
cp .env.example .env
python main.py --dashboard-only
```

## Review reproduction

The pipeline and dashboard use `evaluate_review()` in `core/review_rules.py` as the shared Review implementation. The checks record rule triggers and suggested human follow-up; they do not establish that a classification or summary is correct. See [the Review rules](docs/review_rules.rst) for the checked evidence and limitations.

The offline command reads existing CSVs and their configuration, checkpoint and review sidecars:

```sh
python scripts/recompute_review.py outputs/archive_a.csv outputs/archive_b.csv outputs/archive_c.csv --output outputs/review
```

It writes separate review results and summaries, records input hashes and leaves original CSVs unchanged. The real experimental inputs and private sidecars are not distributed in this source release. Reproducing experimental counts requires those inputs; running the synthetic demo demonstrates the workflow only.


## Local files created after installation

These files are generated on the user's computer and are not part of this package:

```text
.env
config.yaml
outputs/
logs/
saved_configs.json
.reviewed_files.json
```

They may contain project names, file names, local paths, classification results, review edits, and processing diagnostics. Treat them as project data. Do not send them to the package maintainer unless the user has reviewed and approved their contents.

## Data and privacy boundary

The application servers bind to `127.0.0.1` and are intended for one local computer. The dashboard is not an authenticated multi-user service and should not be exposed to a LAN or the public internet.

File discovery and output writing happen locally. The configured LLM provider may receive information needed for classification, including:

- file names and folder context;
- extracted text and OCR text;
- table or metadata previews;
- project context entered in the wizard;
- visual previews of drawings, PDFs, and images when visual analysis is required.

Therefore this is a local application, but it is not an offline processing system. Before using it with confidential project material, confirm that the selected provider and account satisfy the user's data-processing requirements. For fully offline processing, a local text/vision model integration is required; this package does not provide that mode by default.

## Releasing a clean copy

Before sharing a new package, build it from an allowlist. Include only:

```text
core/
server/
static/
scripts/
tests/
docs/
demo_data/
taxonomies/default.yaml
taxonomies/bijlmermeer_demo.yaml
taxonomy.yaml
main.py
requirements.txt
install.bat
start_dashboard.bat
stop_dashboard.bat
config.example.yaml
.env.example
.gitignore
LICENSE
README.md
```

Do not include:

```text
.git/
.claude/
.venv/
__pycache__/
.DS_Store
config.yaml
.env
outputs/
logs/
saved_configs.json
.reviewed_files.json
experimental CSV files outside demo_data/
*.bak
research notes, thesis files, or private project configurations
```

If an API key has ever appeared in a repository, settings file, command, or log, revoke it and create a new key before distributing any package. Removing the visible file does not remove the key from Git history or backups.

Build a source directory and ZIP from the current working files with:

```sh
python scripts/build_release.py --output release/data-taxonomy-1.0.0 --zip
```

The destination must be empty. The builder uses the generic default taxonomy, includes a SHA-256 file manifest and excludes local settings, results and Git history. Initialize a new Git repository inside the exported directory when preparing a standalone public release.

## Troubleshooting

- If the input path is invalid, reopen the configuration page and select the folder again.
- If scanned PDFs have no readable text, install Tesseract OCR and run the pipeline again.
- If the dashboard is unavailable, close stale Python processes and start `main.py --dashboard-only` again.
- If a provider rejects the selected model, choose a model supported by the configured base URL in the wizard or `config.yaml`.

## License and support

The software is distributed under the [MIT License](LICENSE), copyright 2026 Jingqi Lu. Real client archives and private experimental outputs are not included in the release. Separately installed dependencies and external services retain their own license and service terms.

## AI API connections

Open **Configuration → AI Connection** and choose **OpenRouter**, **Gemini API**,
**Claude API**, **Codex (OpenAI API)**, or **OpenAI API**. Each option shows links to
its official API-key console and documentation. Enter your own API key, select a
suggested model or click **Load available models**, then click **Verify connection**
and save the project. Verification sends a short request and may incur a small charge.
Image analysis requires a model with vision support.

| Option | API key | Official documentation |
| --- | --- | --- |
| OpenRouter | `OPENROUTER_API_KEY` | [OpenRouter API](https://openrouter.ai/docs/quickstart) |
| Gemini | `GEMINI_API_KEY` | [Gemini compatibility API](https://ai.google.dev/gemini-api/docs/openai) |
| Claude | `ANTHROPIC_API_KEY` | [Claude compatibility API](https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk) |
| Codex | `OPENAI_API_KEY` | [Codex Responses API](https://developers.openai.com/api/docs/models/gpt-5.1-codex) |
| OpenAI | `OPENAI_API_KEY` | [OpenAI API](https://developers.openai.com/api/docs/quickstart) |

Keys are stored separately in `.env`. Codex and OpenAI share the same official
OpenAI API key; all other options use their own keys. Use a workspace-scoped key
for Claude. Pipeline runs, dashboard reruns and URL autofill share the configured
connection. Codex requests use the Responses API, including image inputs and tool
calls; other options use Chat Completions. Suggested models still need verification
with your own account; the list does not imply a successful live API test.

```yaml
processing:
  provider: openrouter
  base_url: https://openrouter.ai/api/v1
  model: google/gemini-2.5-flash
  api_timeout: 60
```

Base URLs ending in `/chat/completions` or `/responses` are normalized.
Existing configurations infer their provider from the endpoint until saved. A non-empty
`MODEL` environment variable overrides the CLI model; leave it blank for UI selection.
Restart the configuration and dashboard servers after upgrading.
`configuration.port` selects the project manager port; `dashboard.port` selects the results port.
Navigation between them uses these settings, so multiple checkouts can use different ports.

## Project workflow

- New projects start with blank project information and reuse the current AI connection.
- Save writes project settings and taxonomy together; Save & Run returns to the manager and starts processing.
- Existing projects allow direct section navigation and Save & Return.
- Running jobs use a configuration snapshot and remain visible after refreshing the page.
- Each result stores its run configuration, taxonomy, and file-path-based review records separately.
- Dashboard exports include saved review edits. Historical results without a configuration snapshot must be rerun from their project before AI reruns are available.
- Connection-loading failures disable setup instead of leaving editable default settings.
