# AutoContest

**Automated Sweepstakes & Contest Entry Tool**

*by Adam Rivers — A product of Hello Security LLC Research Labs*

![AutoContest Screenshot](screenshots/screenshot1.jpg)

AutoContest is a Python-based tool that automates the process of finding and entering online sweepstakes and contests. It scrapes contest URLs from a curated list of aggregator sites, automatically fills out entry forms, and handles both POST and GET submissions, with support for CAPTCHA solving. The tool provides live progress updates and a user-friendly interface using the `rich` library.

## Features

- **Concurrent Automation**: Scraping and form submission run fully asynchronously over a shared `aiohttp` session with a configurable concurrency limit, so a run completes in a fraction of the time a sequential pass would take.
- **Automated Contest Discovery**: Scrapes contest URLs from a large built-in list of 100+ aggregator sites (dedicated sweepstakes directories, roundup blogs, international aggregators, and brand/media hubs) and can grow the list by scanning curated hub sites for new aggregators (with a safety cap so discovery never turns into an unbounded crawl).
- **Form Submission**: Supports both POST and GET form submissions, with robust field mapping for user details (name, email, address, etc.) and handling of inputs, selects, textareas, checkboxes, and radio buttons. It only submits forms that actually look like entry forms (those with identity fields), skipping search boxes, login/registration forms, and other page chrome, and preserves hidden fields (e.g. CSRF tokens).
- **Smart Link Filtering**: When scraping, it drops links that are not individual entry pages — social share/profile links, link shorteners, and navigation/account/legal/category/tag pages — and collapses URL fragments so the same page isn't entered many times.
- **Honest Reporting**: Results distinguish **Confirmed** entries (the response contained an explicit confirmation) from **Submitted (unconfirmed)** (the form posted and returned OK, but no confirmation was detected), so the summary reflects what actually happened rather than counting every HTTP 200 as a win.
- **Dry-Run Mode**: Parse and fill every form *without submitting anything* — ideal for testing your configuration or previewing what would be entered.
- **CAPTCHA Support**: Detects and solves reCAPTCHA and hCAPTCHA using 2Captcha (requires API key and library installation).
- **Command-Line & Menu Interfaces**: Run interactively via a menu, or non-interactively with flags (`--run`, `--dry-run`, `--update-aggregators`, …) for scripting and cron jobs.
- **Live Output**: Displays real-time progress bars (with counts and elapsed time) for scraping and form submission using the `rich` library.
- **User Details Management**: Allows users to input and save personal details (e.g., name, email, address) to `config.json` for reuse. A safety guard warns before submitting real entries while the details are still the example placeholder.
- **Error Handling**: Retries transient failures with exponential backoff, uses `urljoin` for accurate URLs, sends a realistic browser User-Agent, and inspects response text for success/error indicators instead of trusting the HTTP status alone.
- **Menu-Driven Interface**: Offers options to run automation, dry-run, view results, enter user details, update aggregator URLs, or exit.
- **Standalone Executable**: Can be packaged into a single-file executable (`AutoContest.exe` on Windows) with PyInstaller — no Python install required to run it. Pre-built binaries are produced automatically by a GitHub Actions workflow.
- **Logging**: Saves detailed logs to `automation.log` for debugging and tracking.

## Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/AdamRiversCEO/AutoContest.git
   cd AutoContest
   ```

2. **Install Dependencies**:
   Ensure you have Python 3.8+ installed, then install the required packages:
   ```bash
   pip install -r requirements.txt
   ```
   For CAPTCHA support, install the optional 2Captcha library:
   ```bash
   pip install 2captcha-python
   ```

3. **Set Up Configuration**:
   - The script creates a `config.json` file on first run with default settings.
   - Optionally, add a 2Captcha API key to `config.json` for CAPTCHA solving:
     ```json
     "twocaptcha_api_key": "your-api-key-here"
     ```

## Standalone Executable (no Python required)

If you'd rather run AutoContest without installing Python, you can use a
single-file executable (`AutoContest.exe` on Windows).

**Download a pre-built binary (easiest):**
The [`Build executables`](../../actions/workflows/build-exe.yml) GitHub Actions
workflow builds executables for Windows, macOS, and Linux on every push and can
be run manually from the **Actions** tab. Open the latest run and download the
`AutoContest-windows` artifact (or `-macos` / `-linux`). Pushing a version tag
such as `v1.0.0` also attaches the binaries to a GitHub Release.

**Build it yourself:**
PyInstaller does not cross-compile, so build on the OS you want the executable
for (e.g. run this on Windows to get `AutoContest.exe`):
```bash
pip install -r requirements.txt pyinstaller 2captcha-python
pyinstaller AutoContest.spec
```
The executable is written to the `dist/` folder. Run it just like the script —
double-click for the menu, or from a terminal with flags:
```bash
AutoContest.exe --dry-run
```

## Usage

1. **Interactive Mode** — run with no arguments to open the menu:
   ```bash
   python AutoContest.py
   ```

   **Main Menu Options**:
   - **[1] Run Automation (live)**: Scrapes contest URLs and submits entry forms.
   - **[2] Dry Run**: Fills every form but submits nothing — great for testing.
   - **[3] View Last Results**: Displays results from the last run (`contest-results.json`).
   - **[4] Enter User Details**: Prompts for personal details (including birthdate, `YYYY-MM-DD`) and saves them to `config.json`.
   - **[5] Update Aggregator URLs**: Scans hub sites to find and add new aggregator URLs.
   - **[6] Exit**: Closes the program.

2. **Command-Line Mode** — for scripting and cron jobs:
   ```bash
   python AutoContest.py --run                 # scrape + submit entries
   python AutoContest.py --dry-run             # fill forms but do NOT submit
   python AutoContest.py --update-aggregators  # discover new aggregators only
   python AutoContest.py --run --concurrency 20 --limit 200 --yes
   ```

   Useful flags: `--config PATH`, `--results PATH`, `--concurrency N`,
   `--max-retries N`, `--limit N` (cap contest URLs, `0` = no cap), and
   `-y/--yes` (skip confirmation prompts). Run `python AutoContest.py --help`
   for the full list.

3. **Example Workflow**:
   - Select `[4]` to enter your details (saved for future runs).
   - Select `[2]` to do a dry run and confirm forms are detected and filled correctly.
   - Select `[5]` to refresh the aggregator list (optional).
   - Select `[1]` to scrape contests and submit entries, with live progress updates.
   - View results with `[3]` to see success/failure details.

![Usage Screenshot](screenshots/screenshot2.jpg)

## Configuration

> **Note:** `config.json` holds your personal details, so it is listed in
> `.gitignore` and should never be committed. The script creates it locally on
> first save.

The `config.json` file stores:
- **aggregator_urls**: A list of contest aggregator sites (e.g., SweepstakesFanatics, HGTV). Updated via the `[5]` menu option or `--update-aggregators`.
- **field_mappings**: Maps form field names to user data fields.
- **user_data**: Stores user details (name, email, address, phone, and **birthdate** in `YYYY-MM-DD` format) for form filling. The birthdate is used to fill age-verification fields, including forms that split it into separate month/day/year inputs.
- **max_retries**: Number of retry attempts for form submissions (default: 3).
- **concurrency**: Maximum number of concurrent HTTP requests (default: 10).
- **request_timeout**: Per-request timeout in seconds (default: 20).
- **twocaptcha_api_key**: API key for 2Captcha (optional, for CAPTCHA solving).

Any key you omit from `config.json` is automatically backfilled with its
default, and a malformed file falls back to defaults instead of crashing.

Example `config.json`:
```json
{
  "aggregator_urls": [
    "https://www.sweepstakesfanatics.com/",
    "https://www.contestgirl.com/",
    ...
  ],
  "field_mappings": {
    "first_name": "first_name",
    "last_name": "last_name",
    "email": "email",
    ...
  },
  "user_data": {
    "first_name": "John",
    "last_name": "Doe",
    "email": "example@email.com",
    "birthdate": "1990-01-01",
    ...
  },
  "max_retries": 3,
  "twocaptcha_api_key": ""
}
```

## Important Notes

- **Test with a Dry Run First**: Use `--dry-run` (or menu option `[2]`) to confirm forms are detected and filled correctly before submitting anything live.
- **CAPTCHA Handling**: Without a 2Captcha API key, the script skips forms with CAPTCHAs. Obtain a key from [2Captcha](https://2captcha.com/) and add it to `config.json`.
- **JavaScript Limitations**: The script uses `BeautifulSoup` for scraping and form submission, which doesn't handle JavaScript-heavy forms. For such cases, consider integrating Selenium (not included).
- **Performance**: Work runs concurrently; tune `--concurrency` (default 10) to balance speed against politeness, and use `--limit` to cap how many contest URLs are processed in one run.
- **Data Privacy**: `config.json`, `contest-results.json`, and `automation.log` may contain your personal details and are excluded from version control via `.gitignore`.
- **Error Handling**: The script retries transient failures with exponential backoff, uses `urljoin` for accurate URLs, and classifies each result as confirmed / submitted-unconfirmed / skipped / failed based on the response text rather than trusting the HTTP status alone. Check `automation.log` for detailed error reports.
- **Interpreting Results**: Treat **Submitted (unconfirmed)** as "posted but unverified", not a guaranteed entry — many JavaScript-driven or multi-step entry forms can't be completed by a plain HTTP client. **Confirmed** is the count to trust.
- **Maintenance**: Aggregator and hub site URLs may change. Periodically run `[5]` (or `--update-aggregators`) to refresh the aggregator list.

## Legal and Ethical Considerations

- **Compliance**: Ensure that automating entries complies with the terms of service of each contest site. Some sites prohibit automated submissions.
- **Responsible Use**: Use the tool responsibly to avoid overwhelming servers or violating rules. The authors are not responsible for misuse.
- **Data Privacy**: Only enter personal details you are comfortable sharing with contest sites.

## Contributing

Contributions are welcome! Please:
1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/your-feature`).
3. Commit changes (`git commit -m 'Add your feature'`).
4. Push to the branch (`git push origin feature/your-feature`).
5. Open a pull request.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contact

For questions or feedback, contact Adam Rivers at Hello Security LLC Research Labs via [officialadamrivers@gmail.com](mailto:officialadamrivers@gmail.com).

