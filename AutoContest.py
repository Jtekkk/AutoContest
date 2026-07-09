#!/usr/bin/env python3
"""
AutoContest
Automated Sweepstakes & Contest Entry Tool

by Adam Rivers — A product of Hello Security LLC Research Labs

Usage
-----
Interactive menu:
    python AutoContest.py

Non-interactive (scriptable / cron-friendly):
    python AutoContest.py --run                 # scrape + submit entries
    python AutoContest.py --dry-run             # parse & fill forms but do NOT submit
    python AutoContest.py --update-aggregators  # discover new aggregator sites
    python AutoContest.py --run --concurrency 20 --limit 200

Run ``python AutoContest.py --help`` for the full list of options.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Optional
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table

# ========== Init ==========
console = Console()

DEFAULT_CONFIG_FILE = "config.json"
DEFAULT_RESULT_FILE = "contest-results.json"
LOG_FILE = "automation.log"

# A realistic browser User-Agent avoids trivial bot blocks that reject the
# default ``python-requests``/``aiohttp`` agent outright.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CONTEST_KEYWORDS = ("sweep", "contest", "giveaway")
SUCCESS_INDICATORS = (
    "thank",
    "success",
    "entered",
    "submitted",
    "congrat",
    "confirmation",
    "you're in",
    "you are in",
)
ERROR_INDICATORS = (
    "invalid",
    "required field",
    "please enter",
    "please correct",
    "try again",
    "was not",
    "error occurred",
)

PLACEHOLDER_USER_DATA = {
    "first_name": "John",
    "last_name": "Doe",
    "email": "example@email.com",
    "address": "123 Main St",
    "city": "Sampletown",
    "state": "CA",
    "zip": "12345",
    "phone": "1234567890",
    "birthdate": "1990-01-01",
}

DEFAULT_AGGREGATOR_URLS = [
    "https://www.sweepstakesfanatics.com/",
    "https://www.contestgirl.com/",
    "https://www.sweepsadvantage.com/",
    "https://www.winprizesonline.com/",
    "https://www.sweepstakestoday.com/",
    "https://online-sweepstakes.com/",
    "https://www.contestbee.com/",
    "https://thefreebieguy.com/current-sweepstakes-and-giveaways/",
    "https://www.pch.com/sweepstakes",
    "https://www.hgtv.com/sweepstakes",
    "https://people.com/sweepstakes",
    "https://www.realsimple.com/sweepstakes",
    "https://www.womansday.com/sweepstakes/",
    "https://www.bhg.com/sweepstakes/",
    "https://www.goodhousekeeping.com/sweepstakes/",
    "https://www.ellentube.com/sweepstakes.html",
    "https://www.travelchannel.com/sweepstakes",
    "https://www.foodnetwork.com/sponsored/sweepstakes",
    "https://www.oprah.com/sweepstakes",
    "https://www.parents.com/sweepstakes/",
    "https://www.instyle.com/sweepstakes",
    "https://www.countryliving.com/sweepstakes/",
    "https://www.redbookmag.com/sweepstakes/",
    "https://www.shape.com/sweepstakes",
    "https://www.southernliving.com/sweepstakes",
    "https://www.marthastewart.com/sweepstakes",
    "https://www.diynetwork.com/sweepstakes",
    "https://www.womansworld.com/sweepstakes",
    "https://www.rachaelraymag.com/sweepstakes",
    "https://www.leitesculinaria.com/sweepstakes",
    "https://www.tasteofhome.com/sweepstakes/",
    "https://www.usatoday.com/sweepstakes/",
    "https://www.luckysweeps.com/",
    "https://www.giveawayfrenzy.com/",
    "https://www.sweepon.com/",
    "https://www.gleam.io/discover/sweepstakes",
    "https://www.contestcorner.com/",
    "https://www.sweetiessweeps.com/",
    "https://www.infinitesweeps.com/",
    "https://www.giveawaypromote.com/",
    "https://www.sweepscheck.com/",
    "https://www.contestchest.com/",
    "https://www.sweepstakeslovers.com/",
    "https://www.giveawaymonkey.com/",
    "https://www.thebalanceeveryday.com/sweepstakes-and-contests-4685789",
    "https://www.siriusxm.com/sweepstakes",
    "https://www.iheart.com/sweepstakes/",
    "https://www.marieclaire.com/sweepstakes/",
    "https://www.cosmopolitan.com/sweepstakes/",
    "https://www.americanfamily.com/sweepstakes/",
    "https://www.anheuser-busch.com/sweepstakes",
    "https://www.coca-cola.com/en/offerings/sweepstakes",
    "https://www.pepsi.com/en-us/sweepstakes/",
    "https://www.toyota.com/usa/sweepstakes.html",
    "https://www.ford.com/sweepstakes/",
    "https://www.chevrolet.com/sweepstakes",
    "https://www.nissanusa.com/sweepstakes.html",
    "https://www.dell.com/en-us/giveaways",
    "https://www.intel.com/content/www/us/en/gaming/sweepstakes.html",
    "https://www.microsoft.com/en-us/store/b/sweepstakes",
    "https://www.amazon.com/b?node=14365911011",
    "https://ultracontest.com/",
    "https://www.sweepsatlas.com/",
    "https://prizegrab.com/",
    "https://giveawaylisting.com/",
    "https://www.bloggiveawaydirectory.com/",
    "https://contestwatchers.com/",
    "https://www.liveabout.com/sweepstakes-4163146",
    "https://www.ilovegiveaways.com/",
    "https://1sweepstakes.com/",
    # --- Additional directories & roundup blogs ---
    "https://www.juliesfreebies.com/online-sweepstakes/",
    "https://hey-its-free.com/sweepstakes/",
    "https://www.freestufffinder.com/category/sweepstakes/",
    "https://freebies4mom.com/category/giveaways/",
    "https://www.freeflys.com/sweepstakes/",
    "https://www.freebieshark.com/category/sweepstakes/",
    "https://sweetfreestuff.com/category/sweepstakes/",
    "https://www.mojosavings.com/category/giveaways/",
    "https://moneysavingmom.com/category/giveaways/",
    "https://www.giveawaybandit.com/",
    "https://sweepsheet.com/",
    "https://www.sweepstakesninja.com/",
    # --- International aggregators (UK / AU / CA) ---
    "https://www.theprizefinder.com/",
    "https://www.loquax.co.uk/",
    "https://www.magicfreebies.co.uk/competitions",
    "https://www.moneymagpie.com/competitions",
    "https://superlucky.me/",
    "https://www.australiancompetitions.com/",
    "https://www.contesthound.com/",
    "https://contestcanada.net/",
    "https://www.canadianfreestuff.com/",
    # --- Brand / media sweepstakes hubs ---
    "https://www.elle.com/sweepstakes/",
    "https://www.delish.com/sweepstakes/",
    "https://www.housebeautiful.com/sweepstakes/",
    "https://www.popularmechanics.com/sweepstakes/",
    "https://www.menshealth.com/sweepstakes/",
    "https://www.womenshealthmag.com/sweepstakes/",
    "https://www.prevention.com/sweepstakes/",
    "https://www.townandcountrymag.com/sweepstakes/",
    "https://www.harpersbazaar.com/sweepstakes/",
    "https://www.esquire.com/sweepstakes/",
    "https://www.thepioneerwoman.com/sweepstakes/",
    "https://www.allrecipes.com/sweepstakes/",
    "https://www.travelandleisure.com/sweepstakes",
    "https://www.foodandwine.com/sweepstakes",
    "https://www.eatingwell.com/sweepstakes",
    "https://www.bravotv.com/sweepstakes",
    "https://www.nbc.com/nbc-sweepstakes",
    "https://www.cookingchanneltv.com/sweepstakes",
]

# Curated hub sites that list sweepstakes aggregators (no API needed).
HUB_SITES = [
    "https://www.liveabout.com/best-sweepstakes-websites-4163145",
    "https://www.thebalanceeveryday.com/top-sweepstakes-directories-896784",
    "https://www.sweepstakeslovers.com/resources/",
    "https://www.contestgirl.com/links/",
]

# Safety caps so a run can never turn into an unbounded crawl.
MAX_AGGREGATOR_CANDIDATES = 250
AGGREGATOR_LINK_THRESHOLD = 3


def default_config() -> dict[str, Any]:
    """Return a fresh copy of the default configuration."""
    return {
        "aggregator_urls": list(DEFAULT_AGGREGATOR_URLS),
        "field_mappings": {
            "first_name": "first_name",
            "last_name": "last_name",
            "email": "email",
            "address": "address",
            "city": "city",
            "state": "state",
            "zip": "zip",
            "phone": "phone",
            "birthdate": "birthdate",
        },
        "user_data": dict(PLACEHOLDER_USER_DATA),
        "max_retries": 3,
        "concurrency": 10,
        "request_timeout": 20,
        "twocaptcha_api_key": "",
    }


# ========== Config ==========
def load_config(path: str = DEFAULT_CONFIG_FILE) -> dict[str, Any]:
    """Load config from *path*, backfilling any missing keys with defaults."""
    config = default_config()
    p = Path(path)
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            console.print(f"[red]Could not read {path}: {exc}[/]")
            console.print("[yellow]Falling back to default configuration.[/]")
            return config
        if isinstance(saved, dict):
            config.update(saved)
        # Ensure user_data always has every expected key.
        merged_user = dict(PLACEHOLDER_USER_DATA)
        merged_user.update(config.get("user_data") or {})
        config["user_data"] = merged_user
    return config


def save_config(config: dict[str, Any], path: str = DEFAULT_CONFIG_FILE) -> None:
    """Persist *config* to *path* as pretty-printed JSON."""
    Path(path).write_text(json.dumps(config, indent=4), encoding="utf-8")


def get_user_data(config: dict[str, Any]) -> dict[str, str]:
    """Return the saved user details, backfilled with placeholders."""
    user_data = dict(PLACEHOLDER_USER_DATA)
    user_data.update(config.get("user_data") or {})
    return user_data


def is_placeholder_data(user_data: dict[str, str]) -> bool:
    """Detect the untouched example details, so we never spam real contests."""
    email = (user_data.get("email") or "").strip().lower()
    if email in ("", PLACEHOLDER_USER_DATA["email"]):
        return True
    return (
        user_data.get("first_name") == PLACEHOLDER_USER_DATA["first_name"]
        and user_data.get("last_name") == PLACEHOLDER_USER_DATA["last_name"]
    )


def _prompt_birthdate() -> str:
    """Prompt for an ISO (YYYY-MM-DD) birthdate, re-asking on bad input."""
    default = PLACEHOLDER_USER_DATA["birthdate"]
    value = default
    for _ in range(3):
        value = Prompt.ask("Birthdate (YYYY-MM-DD)", default=default).strip()
        if not value:
            return default
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            console.print("[yellow]Please use the format YYYY-MM-DD (e.g., 1990-01-01).[/]")
    console.print("[yellow]Keeping the last value entered.[/]")
    return value


def input_user_data() -> dict[str, str]:
    """Prompt interactively for the user's contest-entry details."""
    console.print(Panel.fit("[bold cyan]Enter Your Details[/]", border_style="cyan"))
    fields = [
        ("first_name", "First Name"),
        ("last_name", "Last Name"),
        ("email", "Email"),
        ("address", "Address"),
        ("city", "City"),
        ("state", "State (e.g., CA)"),
        ("zip", "Zip Code"),
        ("phone", "Phone Number"),
    ]
    user_data = {key: Prompt.ask(label, default=PLACEHOLDER_USER_DATA[key]) for key, label in fields}
    user_data["birthdate"] = _prompt_birthdate()
    return user_data


def init_logging() -> None:
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def confirm(question: str, *, default: bool = False) -> bool:
    """Ask a yes/no question, degrading to *default* with no TTY / on EOF."""
    if not sys.stdin or not sys.stdin.isatty():
        return default
    try:
        return Confirm.ask(question, default=default)
    except EOFError:
        return default


# ========== HTTP helpers ==========
async def fetch(
    session: aiohttp.ClientSession,
    url: str,
    *,
    method: str = "get",
    **kwargs: Any,
) -> Optional[tuple[int, str]]:
    """Fetch *url* and return ``(status, text)``, or ``None`` on any error."""
    try:
        async with session.request(method, url, **kwargs) as resp:
            text = await resp.text(errors="replace")
            return resp.status, text
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # network, TLS, decode, timeout, ...
        logging.warning("Fetch failed for %s: %s", url, exc)
        return None


async def backoff(attempt: int) -> None:
    """Sleep with exponential backoff and jitter between retries."""
    delay = min(2 ** attempt, 30) + random.uniform(0, 0.5)
    await asyncio.sleep(delay)


async def gather_with_progress(
    coros: list[Awaitable[Any]],
    description: str,
    *,
    quiet: bool = False,
) -> list[Any]:
    """Await *coros* concurrently, showing a live rich progress bar."""
    if not coros:
        return []
    if quiet:
        return await asyncio.gather(*coros)

    results: list[Any] = []
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(description, total=len(coros))
        for future in asyncio.as_completed(coros):
            results.append(await future)
            progress.advance(task)
    return results


# ========== Scraping ==========
def extract_contest_links(base_url: str, html: str) -> list[str]:
    """Return absolute contest-like links found in *html*."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        link = urljoin(base_url, a["href"])
        low = link.lower()
        if link.startswith("http") and any(k in low for k in CONTEST_KEYWORDS):
            links.append(link)
    return links


async def scrape_aggregator(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    url: str,
) -> list[str]:
    """Scrape a single aggregator page for contest URLs."""
    async with sem:
        fetched = await fetch(session, url)
    if not fetched:
        return []
    status, html = fetched
    if status >= 400:
        logging.warning("Aggregator %s returned HTTP %s", url, status)
        return []
    return extract_contest_links(url, html)


async def scrape_contest_urls(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    aggregator_urls: list[str],
    *,
    quiet: bool = False,
) -> list[str]:
    """Scrape all aggregators concurrently and return deduplicated URLs."""
    coros = [scrape_aggregator(session, sem, agg) for agg in aggregator_urls]
    results = await gather_with_progress(coros, "[cyan]Scraping contest URLs...", quiet=quiet)
    urls: set[str] = set()
    for links in results:
        urls.update(links)
    return sorted(urls)


async def _count_contest_links(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    url: str,
) -> tuple[str, int]:
    """Return ``(url, number_of_contest_links)`` for aggregator verification."""
    async with sem:
        fetched = await fetch(session, url)
    if not fetched:
        return url, 0
    status, html = fetched
    if status >= 400:
        return url, 0
    return url, len(extract_contest_links(url, html))


async def discover_aggregators(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    config: dict[str, Any],
    *,
    quiet: bool = False,
) -> int:
    """Scan hub sites for new aggregators and add verified ones to *config*."""
    console.print(
        Panel.fit(
            "[bold cyan]Automatically Updating Aggregator URLs[/]", border_style="cyan"
        )
    )
    known = set(config["aggregator_urls"])

    # Stage 1: collect candidate links from the hub sites.
    hub_coros = [scrape_aggregator(session, sem, hub) for hub in HUB_SITES]
    hub_results = await gather_with_progress(
        hub_coros, "[cyan]Scanning hub sites...", quiet=quiet
    )
    candidates: set[str] = set()
    for links in hub_results:
        for link in links:
            if link.startswith("http") and link not in known:
                candidates.add(link)

    capped = sorted(candidates)[:MAX_AGGREGATOR_CANDIDATES]
    if len(candidates) > len(capped):
        console.print(
            f"[yellow]Found {len(candidates)} candidates; verifying the first "
            f"{len(capped)} (cap).[/]"
        )

    # Stage 2: verify each candidate looks like a real aggregator.
    verify_coros = [_count_contest_links(session, sem, link) for link in capped]
    verified = await gather_with_progress(
        verify_coros, "[cyan]Verifying candidates...", quiet=quiet
    )

    added = 0
    for link, count in verified:
        if count > AGGREGATOR_LINK_THRESHOLD and link not in known:
            config["aggregator_urls"].append(link)
            known.add(link)
            added += 1
            console.print(f"[green]Found new aggregator: {link}[/]")

    console.print(f"[green]Added {added} new aggregator URL(s) to the list.[/]")
    return added


# ========== CAPTCHA ==========
class CaptchaError(Exception):
    """Raised when a CAPTCHA is present but cannot be solved."""


def detect_captcha(soup: BeautifulSoup) -> Optional[tuple[str, Optional[str]]]:
    """Return ``(kind, sitekey)`` if a supported CAPTCHA is present."""
    for css_class, kind, field in (
        ("g-recaptcha", "recaptcha", "g-recaptcha-response"),
        ("h-captcha", "hcaptcha", "h-captcha-response"),
    ):
        div = soup.find("div", class_=css_class)
        if div:
            return kind, div.get("data-sitekey")
    return None


async def solve_captcha(kind: str, sitekey: str, url: str, api_key: str) -> str:
    """Solve a CAPTCHA via 2Captcha and return the response token."""
    try:
        from twocaptcha import TwoCaptcha
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise CaptchaError("2captcha library not installed") from exc

    solver = TwoCaptcha(api_key)
    method = solver.recaptcha if kind == "recaptcha" else solver.hcaptcha
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, lambda: method(sitekey=sitekey, url=url)
    )
    return result["code"]


# ========== Form handling ==========
def _birthdate_part(birthdate: str, part: str) -> str:
    """Return the month/day/year component of an ISO (YYYY-MM-DD) birthdate.

    Falls back to the raw string if it isn't a valid date.
    """
    try:
        dt = datetime.strptime(birthdate, "%Y-%m-%d")
    except (ValueError, TypeError):
        return birthdate
    if part == "month":
        return f"{dt.month:02d}"
    if part == "day":
        return f"{dt.day:02d}"
    if part == "year":
        return f"{dt.year:04d}"
    return birthdate


def match_field(name: str, user_data: dict[str, str], field_mappings: dict[str, str]) -> str:
    """Map a form field *name* to the best-matching user value."""
    if name in field_mappings:
        return user_data.get(field_mappings[name], "")
    low = name.lower()

    # Birthdate: whole-date fields plus split month/day/year parts. Strip the
    # birth indicator first so "birthday"/"bday" don't self-match the "day" part.
    if any(ind in low for ind in ("birth", "dob", "bday")):
        birthdate = user_data.get("birthdate", "")
        remainder = low
        for ind in ("birthdate", "birthday", "birth", "bday", "dob"):
            remainder = remainder.replace(ind, " ")
        if "month" in remainder or "mm" in remainder:
            return _birthdate_part(birthdate, "month")
        if "year" in remainder or "yyyy" in remainder or "yy" in remainder or "yr" in remainder:
            return _birthdate_part(birthdate, "year")
        if "day" in remainder or "dd" in remainder:
            return _birthdate_part(birthdate, "day")
        return birthdate

    for keyword, field in (
        ("email", "email"),
        ("first", "first_name"),
        ("last", "last_name"),
        ("phone", "phone"),
        ("address", "address"),
        ("city", "city"),
        ("state", "state"),
        ("zip", "zip"),
    ):
        if keyword in low:
            return user_data.get(field, "")
    if "name" in low:
        return f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip()
    return ""


def choose_form(forms: list[Any]) -> Any:
    """Pick the form most likely to be a contest-entry form."""
    def score(form: Any) -> int:
        blob = " ".join(
            f"{i.get('name', '')} {i.get('type', '')}" for i in form.find_all("input")
        ).lower()
        return sum(k in blob for k in ("email", "first", "last", "name", "address", "zip", "phone"))

    return max(forms, key=score)


def build_form_data(
    form: Any,
    user_data: dict[str, str],
    field_mappings: dict[str, str],
) -> dict[str, str]:
    """Build the POST/GET payload for *form* from the user's details."""
    form_data: dict[str, str] = {}
    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name:
            continue
        if el.name == "input":
            input_type = (el.get("type") or "text").lower()
            if input_type in ("submit", "button", "image", "reset", "file"):
                continue
            if input_type == "checkbox":
                form_data[name] = el.get("value", "on")  # auto-check (opt-in boxes)
            elif input_type == "radio":
                form_data.setdefault(name, el.get("value", ""))
            elif input_type == "hidden":
                form_data[name] = el.get("value", "")
            else:  # text, email, tel, ...
                form_data[name] = match_field(name, user_data, field_mappings)
        elif el.name == "textarea":
            form_data[name] = el.get_text(strip=True) or "N/A"
        elif el.name == "select":
            chosen = None
            for opt in el.find_all("option"):
                if opt.get("selected") is not None and opt.get("value"):
                    chosen = opt["value"]
                    break
            if chosen is None:
                for opt in el.find_all("option"):
                    if opt.get("value"):
                        chosen = opt["value"]
                        break
            if chosen is not None:
                form_data[name] = chosen
    return form_data


def evaluate_submission(status: int, text: str) -> tuple[bool, str]:
    """Decide whether a submission succeeded from the response."""
    low = text.lower()
    if any(word in low for word in SUCCESS_INDICATORS):
        return True, "Submitted (confirmation detected)"
    if status >= 400:
        return False, f"HTTP {status}"
    if any(word in low for word in ERROR_INDICATORS):
        return False, "Response indicates a validation error"
    return True, f"Submitted (HTTP {status})"


async def submit_form(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    url: str,
    *,
    user_data: dict[str, str],
    field_mappings: dict[str, str],
    max_retries: int,
    api_key: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Fetch a contest page, fill its form, and (unless dry-run) submit it."""
    result: dict[str, Any] = {
        "url": url,
        "submitted": False,
        "retries": 0,
        "reason": "Failed after retries",
        "forms": 0,
    }

    for attempt in range(1, max_retries + 1):
        result["retries"] = attempt
        try:
            async with sem:
                fetched = await fetch(session, url)
            if not fetched:
                result["reason"] = "Could not fetch page"
                await backoff(attempt)
                continue

            status, html = fetched
            soup = BeautifulSoup(html, "html.parser")
            forms = soup.find_all("form")
            if not forms:
                result["reason"] = "No forms found"
                return result

            result["forms"] = len(forms)
            form = choose_form(forms)
            form_data = build_form_data(form, user_data, field_mappings)

            captcha = detect_captcha(soup)
            if captcha:
                kind, sitekey = captcha
                label = "reCAPTCHA" if kind == "recaptcha" else "hCAPTCHA"
                if not sitekey:
                    result["reason"] = f"{label} detected but no sitekey"
                    return result
                if not api_key:
                    result["reason"] = f"{label} detected, no API key"
                    return result
                try:
                    token = await solve_captcha(kind, sitekey, url, api_key)
                except CaptchaError as exc:
                    result["reason"] = str(exc)
                    return result
                except Exception as exc:
                    result["reason"] = f"CAPTCHA solve failed: {exc}"
                    await backoff(attempt)
                    continue
                field = "g-recaptcha-response" if kind == "recaptcha" else "h-captcha-response"
                form_data[field] = token

            method = (form.get("method") or "post").lower()
            action = urljoin(url, form.get("action") or "")

            if dry_run:
                result["submitted"] = True
                result["reason"] = (
                    f"Dry run — would submit {len(form_data)} field(s) via {method.upper()}"
                )
                return result

            if method == "get":
                submit = await fetch(session, action, method="get", params=form_data)
            elif method == "post":
                submit = await fetch(session, action, method="post", data=form_data)
            else:
                result["reason"] = f"Unsupported method: {method}"
                return result

            if not submit:
                result["reason"] = "Submit request failed"
                await backoff(attempt)
                continue

            ok, note = evaluate_submission(*submit)
            result["submitted"] = ok
            result["reason"] = note
            if ok:
                return result
            # Non-success response — retry unless this was the last attempt.
            if attempt < max_retries:
                await backoff(attempt)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.exception("Error submitting %s", url)
            result["reason"] = f"Error: {exc}"
            await backoff(attempt)

    return result


# ========== UI ==========
def display_banner() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]🚀 AutoContest[/]\n[white]Automated Sweepstakes & Contest Entry Tool[/]\n\n"
            "[dim]by Adam Rivers — A product of Hello Security LLC Research Labs[/]",
            border_style="cyan",
            title="Welcome",
            subtitle="Automation Ready",
        )
    )


def display_results(
    results: list[dict[str, Any]],
    start_time: datetime,
    result_file: str,
    *,
    dry_run: bool = False,
) -> None:
    """Render a summary table and totals for a completed run."""
    table = Table(show_lines=True, header_style="bold magenta", border_style="cyan")
    table.add_column("Site", style="cyan", overflow="fold")
    table.add_column("Result", justify="center", style="bold")
    table.add_column("Notes", justify="left", style="white")

    success = skipped = failed = 0
    for r in results:
        reason = r.get("reason", "")
        low_reason = reason.lower()
        if r.get("submitted"):
            success += 1
            label = "[green]Dry run OK[/]" if dry_run else "[green]Success[/]"
            notes = reason or f"{r.get('forms', 1)} form(s) attempted"
        elif "captcha" in low_reason:
            skipped += 1
            label = "[yellow]Skipped (CAPTCHA)[/]"
            notes = reason
        elif "no forms" in low_reason:
            skipped += 1
            label = "[yellow]Skipped (no forms)[/]"
            notes = "No form elements found"
        else:
            failed += 1
            label = "[red]Failed[/]"
            notes = reason
        table.add_row(f"[cyan]{r['url']}[/]", label, notes)

    console.print(Panel.fit("[bold cyan]📊 Contest Automation Summary[/]", border_style="cyan"))
    console.print(table)

    total = len(results)
    duration = (datetime.now() - start_time).total_seconds()
    verb = "would-be entries" if dry_run else "entries"
    console.print(
        Panel.fit(
            f"[bold green]Automation complete — {success}/{total} {verb} in {duration:.1f}s[/]\n"
            f"[white]Success:[/] [green]{success}[/]   "
            f"[white]Skipped:[/] [yellow]{skipped}[/]   "
            f"[white]Failed:[/] [red]{failed}[/]\n\n"
            f"[white]Results saved to:[/] [magenta]{result_file}[/]",
            border_style="green",
        )
    )


# ========== Main Automation ==========
async def run_automation(
    config: dict[str, Any],
    *,
    result_file: str = DEFAULT_RESULT_FILE,
    config_file: str = DEFAULT_CONFIG_FILE,
    update_aggregators: bool = False,
    dry_run: bool = False,
    concurrency: Optional[int] = None,
    limit: int = 0,
    assume_yes: bool = False,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Run the full scrape-and-submit pipeline with real concurrency."""
    user_data = get_user_data(config)

    if not dry_run and is_placeholder_data(user_data):
        console.print(
            "[yellow]Your details still look like the example placeholder "
            "(John Doe / example@email.com).[/]"
        )
        console.print("[yellow]Set them via the menu or edit config.json first.[/]")
        if not assume_yes and not confirm(
            "Submit real entries with placeholder data anyway?", default=False
        ):
            console.print("[yellow]Aborted.[/]")
            return []

    concurrency = concurrency or config.get("concurrency", 10)
    timeout = aiohttp.ClientTimeout(total=config.get("request_timeout", 20))
    connector = aiohttp.TCPConnector(limit=concurrency)

    start_time = datetime.now()
    async with aiohttp.ClientSession(
        headers=DEFAULT_HEADERS, timeout=timeout, connector=connector
    ) as session:
        sem = asyncio.Semaphore(concurrency)

        if update_aggregators:
            added = await discover_aggregators(session, sem, config, quiet=quiet)
            if added:
                save_config(config, config_file)

        contest_urls = await scrape_contest_urls(
            session, sem, config["aggregator_urls"], quiet=quiet
        )
        if limit and len(contest_urls) > limit:
            console.print(f"[yellow]Limiting to {limit} of {len(contest_urls)} URLs.[/]")
            contest_urls = contest_urls[:limit]

        if not contest_urls:
            console.print("[red]No contest URLs found. Nothing to submit.[/]")
            return []

        console.print(f"[cyan]Submitting to {len(contest_urls)} contest form(s)...[/]")
        coros = [
            submit_form(
                session,
                sem,
                url,
                user_data=user_data,
                field_mappings=config["field_mappings"],
                max_retries=config["max_retries"],
                api_key=config.get("twocaptcha_api_key", ""),
                dry_run=dry_run,
            )
            for url in contest_urls
        ]
        results = await gather_with_progress(coros, "[cyan]Submitting forms...", quiet=quiet)

    Path(result_file).write_text(json.dumps(results, indent=4), encoding="utf-8")
    display_results(results, start_time, result_file, dry_run=dry_run)
    return results


# ========== Menu ==========
def menu(config: dict[str, Any], args: argparse.Namespace) -> None:
    display_banner()
    while True:
        console.print(
            Panel.fit(
                "[1] Run Automation (live)\n"
                "[2] Dry Run (fill forms, do NOT submit)\n"
                "[3] View Last Results\n"
                "[4] Enter User Details\n"
                "[5] Update Aggregator URLs\n"
                "[6] Exit",
                title="[bold cyan]Main Menu[/]",
                border_style="cyan",
            )
        )
        choice = Prompt.ask("Select an option", choices=["1", "2", "3", "4", "5", "6"])
        if choice in ("1", "2"):
            asyncio.run(
                run_automation(
                    config,
                    result_file=args.results,
                    config_file=args.config,
                    update_aggregators=False,
                    dry_run=(choice == "2"),
                    concurrency=args.concurrency,
                    limit=args.limit,
                    assume_yes=args.yes,
                )
            )
        elif choice == "3":
            result_path = Path(args.results)
            if result_path.exists():
                results = json.loads(result_path.read_text(encoding="utf-8"))
                display_results(results, datetime.now(), args.results)
            else:
                console.print("[red]No results found. Run automation first.[/]")
        elif choice == "4":
            config["user_data"] = input_user_data()
            save_config(config, args.config)
            console.print("[green]User details saved successfully![/]")
        elif choice == "5":
            asyncio.run(_update_only(config, args))
        elif choice == "6":
            console.print("[yellow]Exiting AutoContest...[/]")
            break


async def _update_only(config: dict[str, Any], args: argparse.Namespace) -> None:
    """Run aggregator discovery on its own (menu option / CLI flag)."""
    timeout = aiohttp.ClientTimeout(total=config.get("request_timeout", 20))
    concurrency = args.concurrency or config.get("concurrency", 10)
    connector = aiohttp.TCPConnector(limit=concurrency)
    async with aiohttp.ClientSession(
        headers=DEFAULT_HEADERS, timeout=timeout, connector=connector
    ) as session:
        sem = asyncio.Semaphore(concurrency)
        added = await discover_aggregators(session, sem, config)
        if added:
            save_config(config, args.config)


# ========== CLI ==========
def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="AutoContest",
        description="Automated Sweepstakes & Contest Entry Tool.",
    )
    parser.add_argument("--run", action="store_true", help="scrape and submit entries, then exit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and fill forms but do NOT submit anything",
    )
    parser.add_argument(
        "--update-aggregators",
        action="store_true",
        help="discover new aggregator sites (combine with --run to also enter)",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_FILE, help="path to config.json")
    parser.add_argument("--results", default=DEFAULT_RESULT_FILE, help="path to results JSON")
    parser.add_argument("--concurrency", type=int, default=None, help="max concurrent requests")
    parser.add_argument("--max-retries", type=int, default=None, help="retry attempts per form")
    parser.add_argument("--limit", type=int, default=0, help="cap number of contest URLs (0 = no cap)")
    parser.add_argument("-y", "--yes", action="store_true", help="skip confirmation prompts")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    init_logging()
    config = load_config(args.config)

    if args.max_retries is not None:
        config["max_retries"] = args.max_retries
    if args.concurrency is not None:
        config["concurrency"] = args.concurrency

    non_interactive = args.run or args.dry_run or args.update_aggregators
    try:
        if not non_interactive:
            menu(config, args)
            return 0

        if args.update_aggregators and not (args.run or args.dry_run):
            asyncio.run(_update_only(config, args))
            return 0

        asyncio.run(
            run_automation(
                config,
                result_file=args.results,
                config_file=args.config,
                update_aggregators=args.update_aggregators,
                dry_run=args.dry_run,
                concurrency=args.concurrency,
                limit=args.limit,
                assume_yes=args.yes,
            )
        )
        return 0
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Exiting AutoContest...[/]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
