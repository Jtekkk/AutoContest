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
from urllib.parse import urldefrag, urljoin, urlparse

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

# Specific confirmation phrases. Kept deliberately narrow: single words like
# "thank"/"success"/"entered" appear on nearly every sweepstakes page and made
# the old success count meaningless.
SUCCESS_INDICATORS = (
    "thank you for entering",
    "thanks for entering",
    "you have been entered",
    "you've been entered",
    "you're entered",
    "youre entered",
    "you are entered",
    "your entry has been",
    "entry received",
    "entry confirmed",
    "successfully entered",
    "you're now entered",
    "good luck",
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

# Hosts that are never contest-entry pages (social share/profile, app stores,
# link shorteners, JS-only widgets).
SKIP_DOMAINS = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "pinterest.com",
    "linkedin.com",
    "reddit.com",
    "addtoany.com",
    "play.google.com",
    "apps.apple.com",
    "bit.ly",
    "t.co",
    "sweepwidget.com",
    "royaldraw.com",
)
# Path segments that mark a page as navigation/account/legal/listing rather than
# an entry page. Matched against whole path segments to avoid false substrings
# (e.g. "/about" must not match "/about-town-giveaway").
SKIP_PATH_SEGMENTS = frozenset(
    {
        "login", "signin", "sign_in", "signup", "sign_up", "register",
        "account", "auth", "cart", "checkout", "share", "sharer",
        "privacy", "terms", "tos", "disclaimer", "about", "contact",
        "faq", "sitemap", "advertise", "rules", "category", "tag",
        "archive", "archives", "page", "feed", "wp-login.php", "wp-login",
    }
)
# Query-string markers that indicate a share/social endpoint.
SKIP_QUERY_MARKERS = ("linkurl=", "sharer", "share?", "u=http", "text=", "mini=true")

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
    # --- International aggregators (UK / IE / CA / AU / NZ / IN / ZA / PH) ---
    "https://www.competitiondatabase.co.uk/",
    "https://www.competitionstoday.co.uk/",
    "https://prizeinn.co.uk/companies",
    "https://sweepzy.co.uk/",
    "https://www.latestdeals.co.uk/competitions",
    "https://www.prize-draw.com/",
    "https://luckyturbo.co.uk/",
    "https://competitions.ie/",
    "https://www.fpd.ie/",
    "https://www.familyfun.ie/competition/",
    "https://irishkingcompetitions.ie/",
    "https://www.matesratescompetitions.com/competitions/",
    "https://eirecompetitions.ie/",
    "https://www.contestscoop.com/",
    "https://www.allcanadacontests.com/",
    "https://www.canadiansavers.ca/contests-canada/",
    "https://contestreminder.com/locales/canada/",
    "https://canadianparent.ca/rewards/contests-canada",
    "https://www.savealoonie.com/contests/",
    "https://www.competitions.com.au/",
    "https://www.aussiecomps.com/",
    "https://www.ozbargain.com.au/competition",
    "https://www.compaigns.com.au/",
    "https://giveaways.com.au/pages/giveaways-directory",
    "https://auscomps.au/",
    "https://www.freesamplesaustralia.com/competitions-and-giveaways/",
    "https://www.girl.com.au/competitions.htm",
    "https://www.competitions.co.nz/",
    "https://www.contest.co.nz/",
    "https://winstuff.co.nz/",
    "https://nz.wowfreebies.com/category/free-competitions/",
    "https://kiwifamilies.co.nz/competitions/",
    "https://www.fforfree.net/",
    "https://www.freebiesloot.com/",
    "https://www.adytude.com/",
    "https://givingmore.co.za/online-competition-club",
    "https://www.prized.co.za/",
    "https://www.winsomething.co.za/",
    "https://freehub.co.za/competitions/",
    "https://prizedrop.co.za/",
    "https://gosouthafrica.co.za/competitions/",
    "https://consumerrewards.co.za/",
    "https://www.contestsandpromos.com/",
    "https://www.phpromos.com/",
    # --- US sweepstakes / giveaway directories & communities ---
    "https://www.sweepstakesbible.com/",
    "https://www.sweepstake.com/directory/",
    "https://sweepstoday.com/",
    "https://www.sweeps4all.com/",
    "https://sweepstakesrush.com/current-sweepstakes/",
    "https://truesweepstakes.com/",
    "https://promosimple.com/giveaways/",
    "https://ourinstantwin.com/",
    "https://www.instantwincrazy.com/",
    "https://winbigdaily.com/",
    "https://openclassactions.com/sweepstakes.php",
    "https://www.contestlisting.com/",
    "https://www.sweepstakespit.com/",
    "https://www.justfreestuff.com/",
    "https://giveaways4mom.com/",
    "https://absolute-forum.com/forumdisplay.php?f=4",
    "https://www.sweeperschoice.com/",
    "https://iwincontests.com/",
    # --- Brand / media / retailer sweepstakes hubs ---
    "https://www.wheeloffortune.com/win",
    "https://www.audacy.com/contests",
    "https://www.hallmarkchannel.com/hallmark-channel-sweepstakes",
    "https://www.aarp.org/entertainment/sweeps/",
    "https://www.qvc.com/content/featured/sweepstakes.html",
    "https://www.hsn.com/content/sweepstakes/704",
    "https://www.consumerreports.org/sweepstakes/",
    "https://jenniferhudsonshow.com/pages/giveaways/",
    "https://www.thedrewbarrymoreshow.com/tags/prize",
    "https://priceisright.com/giveaways/",
    "https://www.bestbuy.com/site/sweepstakes",
    "https://www.tractorsupply.com/tsc/cms/sweepstakes",
    "https://www.dickssportinggoods.com/s/sweepstakes-details",
    "https://www.familyhandyman.com/sweepstakes/",
    "https://www.bettycrocker.com/coupons-promotions/sweepstakes",
    "https://www.pillsbury.com/sweepstakes",
    "https://www.kohls.com/feature/kohlscashsweeps.jsp",
    "https://www.vitacost.com/sweepstakes",
    "https://www.publix.com/mc/promotions",
    "https://www.walgreens.com/topic/promotion/myw.jsp",
    "https://www.basspro.com/shop/en/discoveryouradventure",
    "https://www.nascar.com/fan-rewards/",
    "https://www.purewow.com/giveaways",
    "https://www.today.com/together",
    "https://www.caranddriver.com/sweepstakes/",
    "https://www.seventeen.com/sweepstakes/",
    "https://www.usmagazine.com/sweepstakes/",
    "https://www.firstforwomen.com/sweepstakes/",
    # --- Freebie / deal blog giveaway sections ---
    "https://hip2save.com/sweepstakes/",
    "https://passionatepennypincher.com/giveaway/",
    "https://www.frugalcouponliving.com/category/giveaway/",
    "https://www.freebie-depot.com/category/weekly-giveaways/",
    "https://www.budgetsavvydiva.com/category/giveaway/",
    "https://chachingonashoestring.com/category/giveaways/",
    "https://chachingqueen.com/giveaways-list",
    "https://www.krogerkrazy.com/types/giveaway/",
    "https://www.freestufftimes.com/contests/",
    "https://www.utahsweetsavings.com/category/giveaways/",
    "https://fabulesslyfrugal.com/enter-giveaway/",
    "https://www.thefrugalgirl.com/category/giveaways/",
    "https://dealseekingmom.com/category/giveaways/",
    "https://freebiemom.com/category/sweepstakes/",
    "https://forthemommas.com/category/free-stuff/giveaways",
    # --- US local TV station contest hubs ---
    "https://kdvr.com/contests/",
    "https://www.wfla.com/contests/",
    "https://www.kxan.com/contests/",
    "https://ktla.com/contests/",
    "https://fox2now.com/contests/",
    "https://www.kget.com/contests/",
    "https://www.wpri.com/contests/",
    "https://fox59.com/contests/",
    "https://wgntv.com/contests/",
    "https://fox8.com/contests/",
    "https://www.wavy.com/contests/",
    "https://fox4kc.com/contests/",
    "https://wreg.com/contests/",
    "https://www.koin.com/community/contests/",
    "https://www.wivb.com/community/contests/",
    "https://pix11.com/pix11-contests/",
    "https://www.wjhl.com/contests/",
    "https://www.kron4.com/community/contests/",
    "https://www.krqe.com/contests/",
    "https://www.wkrn.com/contests/",
    "https://whnt.com/contests/",
    "https://www.wric.com/contests/",
    "https://www.wspa.com/contests/",
    "https://www.abc27.com/contests/",
    "https://www.wdtn.com/contests/",
    "https://foxbaltimore.com/station/contests",
    "https://wset.com/station/contests",
    "https://katu.com/station/contests",
    "https://wach.com/station/contests",
    "https://wjla.com/station/contests",
    "https://kutv.com/station/contests",
    "https://komonews.com/station/contests-community-events",
    "https://wpde.com/station/contests",
    "https://wsbt.com/station/contests",
    "https://kmph.com/station/contests",
    "https://wgme.com/station/contests",
    "https://wtov9.com/features/contests",
    "https://www.wfaa.com/contests",
    "https://www.khou.com/contests",
    "https://www.king5.com/contests",
    "https://www.wusa9.com/contests",
    "https://www.wbir.com/contests",
    "https://www.wcnc.com/contests",
    "https://www.wkyc.com/contests",
    "https://www.kare11.com/contests",
    "https://www.wtsp.com/contests",
    "https://www.11alive.com/contests",
    "https://www.kgw.com/contests",
    "https://www.9news.com/contests",
    "https://www.wgrz.com/contests",
    "https://www.kold.com/contests/",
    "https://www.wbrc.com/contests/",
    "https://www.wafb.com/contests/",
    "https://www.wctv.tv/contests/",
    "https://www.kltv.com/contests/",
    "https://www.wsfa.com/contests/",
    "https://www.kfvs12.com/contests/",
    "https://www.kwtx.com/contests/",
    "https://www.westernmassnews.com/contests/",
    "https://www.wtoc.com/contests/",
    "https://www.wsaz.com/contests/",
    "https://www.kktv.com/contests/",
    "https://www.ksla.com/contests/",
    "https://www.wilx.com/contests/",
    "https://www.wtvm.com/contests/",
    "https://www.wfsb.com/contests/",
    "https://www.wcpo.com/about-us/contests",
    "https://www.abc15.com/about-us/contests",
    "https://www.wxyz.com/about-us/contests",
    "https://www.kshb.com/about-us/contests",
    "https://www.wptv.com/about-us/contests",
    "https://www.kjrh.com/about-us/contests",
    "https://www.wsls.com/contests/",
    # --- US radio station contest hubs ---
    "https://www.z104country.com/contests/",
    "https://www.newcountry1015.com/contests/",
    "https://froggy981.com/contests/",
    "https://country1025.com/contests/",
    "https://hankfm.com/category/contests/",
    "https://www.kmoo.com/contests",
    "https://www.995thewolf.com/category/contests/",
    "https://www.newcountry963.com/category/contests/",
    "https://93qcountry.com/category/contests/",
    "https://minnesotasnewcountry.com/category/contests/",
    "https://www.933thebull.com/contests/",
    "https://www.kiss104fm.com/contests/",
    "https://www.959kissfm.com/all-contests/",
    "https://www.92profm.com/category/contests/",
    "https://kroc.com/contest-rules/",
    "https://wmmr.com/official-contest-rules/",
    "https://www.1045thezone.com/contests/",
    "https://hot1071.com/contests/",
    "https://thebeat.net/contests/",
    "https://ilovebobfm.com/contests/",
    "https://1047bobfm.com/contests/",
    "https://989magicfm.com/category/contests/",
    "https://fm100.com/contests/",
    "https://coast931.com/win-tickets",
    "https://cumulussavannah.com/what-we-offer/contest-events/",
    "https://www.ktcx.com/contests/",
    "https://www.b98.com/category/contests/national-contests/",
    "https://www.kix96.com/category/contests/national-contests/",
    "https://www.q997atlanta.com/contests/",
    "https://windfm.com/contests/",
    "https://www.myradiolink.com/contests/",
    "https://www.wtcmi.com/contests",
    "https://wgnradio.com/contests/",
    "https://radiomilwaukee.org/contests",
    "https://radiou.com/contests/",
    "https://www.whio.com/whio-radio/contests/",
    "https://krforadio.com/contest-rules/",
    "https://wixx.com/contestrules/",
    "https://wiky.com/contestrules/",
    "https://wsau.com/contestrules/",
    "https://wmbdradio.com/contestrules/",
    "https://kfgo.com/contestrules/",
    "https://wimz.com/contestrules/",
    # --- International aggregators & regional comp/giveaway sites ---
    "https://www.competitions-time.co.uk/",
    "https://wincompetitions.ie/",
    "https://iwinprizes.ie/",
    "https://www.wannawin.ca/",
    "https://www.lottos.com.au/",
    "https://www.evansabove.com/competitions/",
    "https://contestalert.in/",
    "https://www.indiadesire.com/",
    "https://giveawaysindia.com/giveaways/",
    "https://win-prizes.co.za/",
    "https://freeonlinecompetitions.co.za/",
    "https://allpromos.ph/",
    "https://www.manilashopper.com/",
    "https://sgdealsandfreebies.com/category/giveaways-competitions/",
    "https://thehoneycombers.com/singapore/things-to-do/giveaway/",
    "https://www.sassymamasg.com/category/giveaway/",
    "https://getfreebies.my/",
    "https://my.peraduan.com/",
    "https://malaysiagiveaway.com/",
    "https://competition.my/",
    "https://www.promosinnigeria.com/category/giveaways/",
    "https://giveawayng.com/",
    "https://naijawinners.com/",
    "https://connector.ae/competition",
    "https://www.shortlistdubai.com/competitions",
    "https://yalladubai.ae/competitions/",
    "https://whatson.ae/section/competitions/",
    "https://www.expatwoman.com/dubai/things-to-do/competitions",
    "https://www.timeoutdubai.com/competitions",
    "https://blaagiveaways.com/",
    "https://www.gewinnspiele-markt.de/",
    "https://www.gewinnspielverzeichnis.de/",
    "https://www.gewinnspiele-zentrale.de/",
    "https://www.gewinnspiele.de/gewinnspiele/",
    "https://www.gewinnspiel.de/",
    "https://www.kostenlos.de/gewinnspiele",
    "https://www.einfach-sparsam.de/gewinnspiele",
    "https://www.ledemondujeu.com/",
    "https://www.leparadisdesjeuxconcours.fr/",
    "https://www.jeu-concours.biz/",
    "https://www.concours-du-net.com/",
    "https://toutgagner.com/",
    "https://jeuxconcoursgratuits.fr/",
    "https://www.echantillonsclub.com/concours",
    "https://www.prijsvragengala.nl/",
    "https://www.prijsvragen.nl/",
    "https://www.prijzenzolder.nl/",
    "https://gratiswinactie.nl/",
    "https://www.winactie.nl/",
    "https://prijsvragen247.nl/",
    "https://winacties.nl/",
    "https://www.sorteopremios.com/",
    "https://sorteosmania.es/",
    "https://www.premiosfaciles.com/",
    "https://www.concursator.com/",
    "https://www.sortea2.com/",
    "https://www.millonesdesorteos.com/",
    "https://yoquieroparticipar.com/sorteos-activos/",
    "https://www.dimmicosacerchi.it/concorsi-a-premi",
    "https://www.soldissimi.it/concorsi-a-premio/",
    "https://campionigratuiti.eu/concorsi/",
    "https://www.omaggiomania.com/concorsi-a-premi/",
    "https://www.premieconcorsi.com/concorsi-a-premi/",
    "https://www.supercampione.it/concorsi-gratuiti",
    "https://www.scontrinofelice.it/concorsi-gratuiti/",
    "https://fajnekonkursy.pl/",
    "https://zgarniajto.pl/",
    "https://wygrajta.pl/aktualne-konkursy/",
    "https://konkursiada.pl/",
    "https://www.konkursynagrody.pl/",
    "https://wygrywajwsieci.pl/",
    # --- US freebie / mom / niche giveaway blogs ---
    "https://emilysfrugaltips.com/category/giveaways/",
    "https://www.southernsavers.com/sweepstakes/",
    "https://www.thefarmgirlgabs.com/category/giveaways-2/",
    "https://theswearingmomsguidetolife.com/category/life-style/contest-giveaways/",
    "https://powered-by-mom.com/current-giveaways/",
    "https://www.momdoesreviews.com/giveaways/",
    "https://deliciouslysavvy.com/savvy-giveaways/",
    "https://www.emilyreviews.com/current-giveaways",
    "https://mamathefox.com/category/giveaway/",
    "https://www.mommymusings.com/giveaways/",
    "https://momhomeguide.com/mom-blog-giveaways/",
    "https://www.thebettermom.com/blog/category/Giveaways",
    "https://www.allbeautifulmommies.com/giveaways/",
    "https://www.simplystacie.net/current-giveaways/",
    "https://simplysweethome.com/category/giveaways/",
    "https://twoclassychics.com/reviews-and-giveaways/",
    "https://www.workmoneyfun.com/giveaway-linky/",
    "https://thestuffofsuccess.com/category/giveaways/",
    "https://mrswebersneighborhood.com/category/reviewsgiveaways/",
    "https://cleverlyme.com/category/giveaways/",
    "https://yabookscentral.com/category/giveaways/",
    "https://blog.freshfiction.com/category/giveaways/",
    "https://romancenovelgiveaways.com/",
    "https://bewitchedbookworms.com/",
    "https://www.longandshortreviews.com/",
    "https://readingismysuperpower.org/giveaways/",
    "https://www.thechildrensbookreview.com/",
    "https://www.readingreality.net/category/giveaways/",
    "https://thebookreviewcrew.com/category/giveaways/",
    "https://www.dogtipper.com/our-current-giveaways/",
    "https://www.dailypaws.com/sweepstakes",
    # --- Brand / retailer / CPG sweepstakes hubs ---
    "https://www.naturalgrocers.com/contest-rules",
    "https://superiorgrocers.com/sweepstakes/",
    "https://www.albertsons.com/shopandwin.html",
    "https://www.safeway.com/shopandwin.html",
    "https://www.kwiktrip.com/sweepstakes",
    "https://www.cvs.com/content/social-media-sweepstakes-rules",
    "https://newsroom.bjs.com/Sweepstakes-Rules/",
    "https://www.hy-vee.com/corporate/news-events/promotions/",
    "https://www.tlc.com/giveaways",
    "https://www.insp.com/all-sweepstakes/",
    "https://www.tvinsider.com/category/sweepstakes/",
    "https://www.cwtv.com/thecw/sweepstakes-rules/",
    "https://www.maybelline.com/promotions-and-sweepstakes",
    "https://www.makeup.com/sweepstakes",
    "https://www.shiseido.com/us/en/beauty-giveaway.html",
    "https://www.avon.com/sweepstakes",
    "https://www.to112.com/pages/sweepstakes",
    "https://www.skincare.com/sweepstakes",
    "https://www.narscosmetics.com/USA/sweepstakes",
    "https://www.routemagazine.us/centennialsweepstakes",
    "https://www.refinery29.com/en-us/contests",
    "https://www.freepeople.com/giveaways/",
    "https://sunset.com/sweepstakes",
    "https://www.vikingcruises.com/oceans/contact/sweepstakes.html",
    "https://www.expediacruises.com/en-us/corporate/contest",
    "https://www.cruiseone.com/vacation/deals/promos/contest-enter-to-win",
    "https://www.victorybeer.com/tastevictorysweeps/",
    "https://www.naturallight.com/GreatPrizes",
    "https://mountaindewpromos.com/",
    "https://fritospromos.com/",
    "https://www.tastyrewards.com/en-us",
    "https://www.monsterenergy.com/en-us/promotions/",
    "https://www.kelloggs.com/en_US/offers-and-promotions.html",
    "https://www.wkkellogg.com/our-foods/promotions",
    "https://www.drpepper.com/tuition/",
    "https://www.ihop.com/en/sweepstakes",
    "https://www.applebees.com/en/games/collect-the-combos-sweepstakes",
    "https://www.buffalowildwings.com/rewards/",
    "https://www.wingstop.com/contest",
    "https://www.papajohns.com/whatsyourstyle-sweeps/",
    "https://www.gamestop.com/sweepstakes.html",
    "https://www.yeti.com/en_US/sweepstakes.html",
    "https://www.samsung.com/us/shop/sweepstakes/",
    "https://my.nintendo.com/reward_categories/sweepstake",
    "https://www.crateandbarrel.com/sweeps",
    "https://www.williams-sonoma.com/pages/habitat-sweepstakes.html",
    "https://www.flyfrontier.com/sweepstakes/",
    "https://www.chewy.com/app/content/giveaway-sweepstakes-rules",
    "https://cruises.delta.com/promotion/sweepstakes.do",
    # --- Sweepstakes directories, forums & niche giveaway sites ---
    "https://www.prizestakes.com/",
    "https://myentertowin.com/",
    "https://www.serbakuis.com/",
    "https://giveawaydrop.com/",
    "https://forums.moneysavingexpert.com/categories/competitions",
    "https://slickdeals.net/forums/forumdisplay.php?f=25",
    "https://phatwalletforums.com/category/25/contests-sweepstakes",
    "https://www.goodreads.com/giveaway",
    "https://www.gamerpower.com/giveaways",
    "https://www.rd.com/sweepstakes/",
    "https://www.bassmaster.com/current-sweepstakes/",
    "https://moderncat.com/articles/giveaway/",
    "https://moderndogmagazine.com/articles/giveaway/",
    "https://charitypaws.com/freebies/",
    "https://theliterarylifestyle.com/book-giveaways/",
    "https://bonafidebookworm.com/best-book-giveaways/",
    "https://clcannon.net/contests/",
    "https://app.thestorygraph.com/giveaways",
    "https://bookriot.com/giveaways/",
    "https://livingmontessorinow.com/giveaway-linky/giveaway-linky-list/",
    "https://familyfocusblog.com/ongoing-giveaway-linky/",
    "https://www.bumpandbabymatters.com/giveaway",
    "https://www.todaysparent.com/contests/",
    "https://www.collegexpress.com/",
    "https://www.idropnews.com/giveaways/",
    "https://thegadgetflow.com/blog/categories/giveaways/",
    "https://www.hackster.io/giveaways",
    "https://gungiveaways.net/",
    "https://christaquilts.com/tag/fabric-giveaway/",
    "https://blog.shannonfabrics.com/blog/tag/giveaways",
    "https://www.quiltingintherain.com/tag/fabric-giveaways",
    "https://www.quilterblogs.com/tag/giveaway/",
    "https://www.sewmamasew.com/",
    # --- International — Europe (DE/AT/CH/FR/BE/NL/ES/IT/PL/PT/SE/DK/NO/FI/CZ/RO/GR) ---
    "https://www.supergewinne.de/gewinnspiele",
    "https://www.gewinnspiele-fuer-gewinner.de/",
    "https://www.last-minute-gewinnspiele.de/",
    "https://www.gewinnspielverzeichnis.at/",
    "https://www.gewinnspielsammlung.at/",
    "https://reisegewinnspiele.at/",
    "https://www.top10.at/gewinnspiele/",
    "https://www.weekend.at/gewinnspiele",
    "https://win4win.ch/",
    "https://www.alle-schweizer-wettbewerbe.ch/",
    "https://wettbewerb.ch/",
    "https://glueckspilz.ch/",
    "https://www.alle-gewinnspiele.ch/",
    "https://alle-wettbewerbe.ch/",
    "https://www.wettbewerbe365.ch/",
    "https://dein-gewinnspiel.ch/",
    "https://www.concours.ch/",
    "https://www.accrowin.ch/",
    "https://radin.ch/category/concours-suisse/",
    "https://www.suisse-gratuite.ch/gagner/",
    "https://www.reducavenue.com/les-jeux-et-concours",
    "https://www.offresasaisir.fr/jeux-concours",
    "https://www.kuzeo.com/concours/sites/",
    "https://www.concours.fr/",
    "https://www.cadeauxagagner.fr/",
    "https://www.autokdo.com/",
    "https://www.concoursbelgique.be/",
    "https://www.echantillonsgratuits.be/concours-belgique",
    "https://www.jeuxconcoursonline.be/",
    "https://www.spiroo.be/jeux.htm",
    "https://winprijzen.be/",
    "https://www.wedstrijden.be/",
    "https://www.gratiswedstrijden.be/",
    "https://www.gogratis.be/cat/wedstrijden/",
    "https://www.dewedstrijden.be/",
    "https://www.gratis.nl/prijsvragen.php",
    "https://muestrasyregalosgratis.es/sorteos-gratis/",
    "https://www.baratuni.es/sorteos-gratis",
    "https://mejoresmuestrasgratis.com/sorteos-gratis-online/",
    "https://primopremio.net/concorsi-a-premi/",
    "https://www.campioniomaggiogratuiti.it/concorsi-a-premi/",
    "https://aktualnekonkursy.pl/",
    "https://kobietamag.pl/konkursy/",
    "https://upolujnagrode.pl/",
    "https://www.e-konkursy.info/",
    "https://www.sledzimykonkursy.pl/",
    "https://www.agrekon.pl/",
    "https://blog.passatemposportugal.com.pt/",
    "https://l.opoupadinho.pt/",
    "https://www.asmelhoresofertas.net/passatempos/",
    "https://www.paramim.com.pt/passatempos",
    "https://ofertar.pt/",
    "https://www.viagenseferias.net/concursos",
    "https://www.tavlingsguiden.se/",
    "https://www.blienvinnare.com/",
    "https://www.bastgratis.se/tavlingar/",
    "https://gratisprinsessan.se/tavlingar/",
    "https://viivilla.se/tavlingar/",
    "https://www.konkurrencesiden.dk/",
    "https://www.vindgratis.dk/",
    "https://www.konkurrencer.dk/",
    "https://dagensvinder.dk/",
    "https://konkuro.dk/",
    "https://vind24.dk/konkurrence-oversigt/",
    "https://www.blivenvinder.dk/",
    "https://www.blienvinner.no/",
    "https://vinnende.no/",
    "https://nettkonkurranser.com/",
    "https://gjerrigknark.com/konkurranser",
    "https://konkurranseguiden.no/",
    "https://www.konkurransenett.no/",
    "https://www.allekonkurranser.no/",
    "https://parhaatpalat.fi/parhaat-kilpailut-netissa/",
    "https://voittojahti.fi/",
    "https://nettikilpailu.fi/",
    "https://arpaonni.fi/",
    "https://www.arpoo.fi/",
    "https://www.kilpailu.fi/fi/",
    "https://netinkilpailut.com/",
    "https://www.kilpailumaailma.fi/",
    "https://ie.wowfreebies.com/category/free-competitions/",
    "https://irishwincompetitions.ie/",
    "https://www.chcemesoutezit.cz/",
    "https://www.vyhrajvyhraj.cz/",
    "https://www.soutez.org/",
    "https://www.soutezeonline.cz/",
    "https://www.fiftyfifty.cz/souteze-o-ceny-na-internetu/",
    "https://vecizdarma.cz/veci-zdarma/vyherni-souteze-zdarma/",
    "https://www.concursuri.biz/",
    "https://concursul.ro/",
    "https://www.concursuri.online/",
    "https://www.konkurs.ro/",
    "https://wishmo.ro/concursuri",
    "https://www.concursoman.ro/",
    "https://concursier.ro/",
    "https://www.castiga.net/",
    "https://concursurionline.ro/",
    "https://diagonismos.gr/",
    "https://wegive.gr/",
    "https://kerdiseto.gr/",
    "https://epitrapaizoume.gr/contests/",
    "https://www.epithimies.gr/family/activities/contest-page",
    # --- International — UK / Ireland / Canada / Australia / New Zealand ---
    "https://www.competitions-whale.co.uk/",
    "https://giveawaytreasures.co.uk/",
    "https://felixcompetitions.uk/",
    "https://compwatch.co.uk/sites",
    "https://www.chelseamamma.co.uk/category/competitions/",
    "https://pickmypostcode.com/competitions/",
    "https://comps.pickmypostcode.com/",
    "https://wowfreebies.co.uk/free-competitions/",
    "https://www.latestfreestuff.co.uk/",
    "https://freestuff.co.uk/",
    "https://comps.womanmagazine.co.uk/",
    "https://comps.womansownmagazine.co.uk/",
    "https://comps.whatsontv.co.uk/",
    "https://competitions.goodto.com/",
    "https://competitions.stuff.tv/",
    "https://competitions.olivemagazine.com/",
    "https://competitions.madeformums.com/",
    "https://competitions.womanandhome.com/",
    "https://competitions.womansweekly.com/",
    "https://www.sainsburysmagazine.co.uk/win",
    "https://www.smoothradio.com/win/",
    "https://www.irishtimes.com/competitions/",
    "https://www.mummypages.ie/competitions-and-promotions",
    "https://primecompetitions.com/",
    "https://www.everymum.ie/",
    "https://mumsmoney.ie/",
    "https://www.rte.ie/tv/competitions/",
    "https://www.spin1038.com/win",
    "https://www.nova.ie/fun-stuff/competitions/",
    "https://www.todayfm.com/win",
    "https://free.ca/contests/",
    "https://www.contestqueen.com/",
    "https://curiousaboutcanadiancontests.com/",
    "https://mommymoment.ca/current-giveaways/",
    "https://www.contestformoms.com/",
    "https://www.frugalmomeh.com/",
    "https://www.competitionsguide.com.au/",
    "https://compers.com.au/",
    "https://www.thethriftyissue.com.au/",
    "https://prizereactor.com.au/",
    "https://luv2win.com.au/",
    "https://mumcentral.com.au/category/competitions/",
    "https://mouthsofmums.com.au/mom-comps/",
    "https://www.kidspot.com.au/lifestyle/entertainment/competitions/",
    "https://www.kiis1065.com.au/competition/",
    "https://www.aucklandforkids.co.nz/win/",
    "https://www.nzherald.co.nz/promotions/",
    "https://luckygiveaways.co.nz/",
    "https://www.thehits.co.nz/win/",
    "https://www.zmonline.com/win/",
    "https://www.thecoast.net.nz/win/",
    "https://www.theedge.co.nz/home/win.html",
    "https://totstoteens.co.nz/win/",
    "https://www.ohbaby.co.nz/competitions",
    "https://kidspot.co.nz/competitions/",
    "https://familytimes.co.nz/category/competitions/",
    "https://dish.co.nz/competitions",
    # --- International — Asia / Africa / Latin America / Middle East ---
    "https://www.contest.net.in/competitions-list",
    "https://www.tadaang.in/contest",
    "https://contestchacha.com/",
    "https://indiafreestuff.in/",
    "https://www.desidime.com/groups/contests",
    "https://www.readersdigest.in/sweepstakes",
    "https://deals4india.in/freebies-online",
    "https://bdwinners.com/gifts",
    "https://www.singsaver.com.sg/blog/giveaway-and-competition-winners",
    "https://www.timeout.com/singapore/contests",
    "https://infokuisberhadiah.com/",
    "https://infokuisnetwork.id/",
    "https://lombapad.com/Info/giveaway/",
    "https://freejingdi.com/",
    "https://allpromonigeria.blogspot.com/",
    "https://promoupdate4.blogspot.com/",
    "https://nairapromo.blogspot.com/",
    "https://ezeecompetitions.com/",
    "https://www.food-blog.co.za/competitions/",
    "https://musabaqat.org/",
    "https://www.for9a.com/en/opportunity/category/Competitions-and-Awards",
    "https://www.shopandwinrewards.com/",
    "https://dubaisavers.com/guides/raffles-lotteries-in-uae/",
    "https://promocoesnainternet.com.br/sorteios-gratis/",
    "https://pegapromocao.com.br/concursos-culturais/",
    "https://galardians.com/promocoes-concursos-culturais/",
    "https://acheipromocao.com.br/concurso-cultural",
    "https://www.sopromocoes.com.br/participacoes/concursos-culturais",
    "https://participarpromocao.com.br/",
    "https://www.guiadepremios.com/",
    "https://ganapromo.com/",
    "https://www.promodescuentos.com/grupo/concursos",
    "https://wynplay.com/es/",
    "https://consiguiendoregalitos.com/sorteos/",
    "https://www.premios.com/",
    "https://sorteosdehoy.com.ar/",
    "https://promocionesenargentina.blogspot.com/",
    "https://regalosymuestrasgratis.com/category/concursosgratis-sorteosgratis-premiosgratis",
    "https://www.nosotrasonline.com.co/magazin/concursos/",
    "https://perupromo.com/",
    "https://pe.cgana.com/",
    "https://www.13.cl/concursos",
    "https://www.facesorteos.com/",
    "https://www.muestrasgratisychollos.com/sorteos-y-concursos/",
    "https://blog.sorteopremios.com/",
    # --- Brand / retailer / magazine / niche giveaway sections ---
    "https://web.boscovsemail.com/forms/sweepstakes",
    "https://www.groceryoutlet.com/wwys",
    "https://www.sandals.com/sweepstakes/",
    "https://www.beaches.com/sweepstakes/",
    "https://www.wyndhamhotels.com/wyndham-rewards/hotel-deals/travel-sweepstakes",
    "https://www.visitorlando.com/win-a-trip/",
    "https://www.dreamvacations.com/vacation/deals/promos/contest-enter-to-win",
    "https://www.40andholding.com/giveaway/",
    "https://rog.asus.com/articles/giveaways/",
    "https://gaming.lenovo.com/giveaways",
    "https://www.pjsgames.com/blogs/giveaways",
    "https://www.wholelattelove.com/pages/whole-latte-love-giveaways",
    "https://www.seghesio.com/sweepstakes/",
    "https://imagerywinery.com/estate-sweeps/",
    "https://hypebeast.com/giveaways",
    "https://www.brooksrunning.com/en_us/brooks-run-club-sweepstakes/",
    "https://runyourstate.com/pages/giveaways",
    "https://www.enfamil.com/current-past-sweepstakes/",
    "https://www.newtonbaby.com/blogs/sweepstakes-giveaways",
    "https://www.thebump.com/sweepstakes",
    "https://shop.kids2.com/pages/giveaway",
    "https://www.babylist.com/best-baby-registry-giveaway",
    "https://www.shoplc.com/WatchAndWin/giveaways",
    "https://www.bobswatches.com/giveaway/win-5000-watch-credit",
    "https://www.freecast.com/wnw/sweepstakes",
    "https://victoryplus.com/legal/watch-and-win",
    "https://guideposts.org/giveaway/",
    "https://www.motherearthnews.com/giveaways/",
    "https://www.wired2fish.com/giveaways",
    "https://www.finewoodworking.com/tag/giveaways",
    "https://www.protoolreviews.com/category/contests/",
    "https://www.shutterbug.com/category/sweepstakes",
    "https://unleashed.dogtv.com/giveaways/",
    "https://www.toe-beans.com/pages/pet-supplies-giveaways",
    "https://www.nandog.com/pages/giveaway",
    "https://www.aquiltinglife.com/category/giveaways/",
    "https://suznquilts.blog/category/a-giveaway/",
    "https://blog.expressionfiberarts.com/topics/yarn-giveaways/",
    "https://scrapbookpal.com/blogs/giveaways",
    "https://kathleendriggers.com/category/scrapbooking/fun-stuff/",
    "https://www.eatyourbooks.com/blog/category/cookbook-giveaways",
    "https://bookclubs.com/giveaways",
    "https://bookfinity.com/giveaways",
    "https://www.writerswrite.com/books/giveaway/",
    "https://www.meeplemountain.com/board-game-giveaways/",
    "https://everythingboardgames.com/current-giveaways",
    "https://unfilteredgamer.com/board-game-giveaways/",
    "https://shelfgamer.com/giveaway/",
    "https://casualgamerevolution.com/blog/giveaways",
    "https://www.boardgamecapital.com/board-game-giveaways.htm",
    "https://onthewater.com/category/contests-and-giveaways",
    "https://rustyangler.com/free-fishing-gear",
    "https://www.whitetailsunlimited.com/current-contests/deer-gear-giveaway/",
    "https://gsioutdoors.com/pages/giveaway",
    "https://exomtngear.com/pages/independent-outdoor-gear-giveaway",
    "https://www.tackleworld.com/pages/giveaway",
    "https://discounttackle.com/pages/discount-tackle-giveaway",
    "https://www.tacklewarehouse.com/bass-fishing/social/giveaway.html",
    "https://scoutlife.org/giveaways/",
    "https://theculinarychronicles.com/category/giveaways/",
    "https://www.splendidtable.org/cookbook",
    "https://diyprojects.com/giveaway/",
    "https://johnmalecki.com/pages/tool-kit-giveaway",
    "https://infinitytools.com/blogs/giveaways",
    "https://www.woodcraft.com/pages/giveaway",
    "https://seedsforgenerations.com/category/giveaway/",
    "https://growformegardening.com/giveaway/",
    "https://rootedinjs.com/pages/plant-giveaways",
    "https://www.camerachamp.com/collections/current-giveaways",
    "https://shotkit.com/giveaways/",
    "https://homeschoolgiveaways.com/",
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
        # Union the current built-in source list into the saved one. Without
        # this, a config.json written by an older build permanently shadows the
        # defaults, so newly shipped aggregator URLs would never reach the user.
        # Saved URLs (incl. any the user added) are kept and come first; missing
        # built-ins are appended.
        saved_urls = config.get("aggregator_urls")
        if isinstance(saved_urls, list):
            seen = set(saved_urls)
            added = [u for u in DEFAULT_AGGREGATOR_URLS if u not in seen]
            if added:
                config["aggregator_urls"] = saved_urls + added
                console.print(
                    f"[cyan]Added {len(added)} new built-in source(s) to your saved list "
                    f"({len(config['aggregator_urls'])} total).[/]"
                )
        else:
            config["aggregator_urls"] = list(DEFAULT_AGGREGATOR_URLS)
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
def is_entry_candidate(url: str) -> bool:
    """Filter out links that are clearly not individual contest-entry pages.

    Drops social share/profile links, link shorteners, and navigation/account/
    legal/listing pages so the run targets real entry pages instead of the
    surrounding site chrome.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    if any(host == d or host.endswith("." + d) for d in SKIP_DOMAINS):
        return False
    query = parsed.query.lower()
    if query and any(marker in query for marker in SKIP_QUERY_MARKERS):
        return False
    for seg in parsed.path.lower().split("/"):
        if not seg:
            continue
        # Test the raw segment and its extension-stripped stem so "privacy.htm"
        # and "page.pl" are caught by "privacy"/"page".
        if seg in SKIP_PATH_SEGMENTS or seg.split(".", 1)[0] in SKIP_PATH_SEGMENTS:
            return False
    return True


def extract_contest_links(base_url: str, html: str) -> list[str]:
    """Return absolute, de-duplicated contest-entry links found in *html*."""
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        # Drop the URL fragment so "/x#comment-1", "/x#respond", "/x" collapse.
        link = urldefrag(urljoin(base_url, a["href"])).url
        if not link.startswith("http"):
            continue
        low = link.lower()
        if not any(k in low for k in CONTEST_KEYWORDS):
            continue
        if not is_entry_candidate(link):
            continue
        if link in seen:
            continue
        seen.add(link)
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


IDENTITY_KEYWORDS = ("email", "first", "last", "name", "address", "zip", "phone", "fname", "lname")
SEARCH_FIELD_NAMES = ("q", "s", "query", "search", "keyword", "keywords")


def form_entry_score(form: Any) -> int:
    """Score how much a form looks like a real contest-entry form.

    Returns -1 for forms that are definitely not entries (they contain a
    password field, i.e. login/registration), otherwise the number of distinct
    identity fields present. Pure search boxes score 0.
    """
    score = 0
    for el in form.find_all(["input", "select", "textarea"]):
        itype = (el.get("type") or "text").lower()
        if itype == "password":
            return -1
        name = (el.get("name") or "").lower()
        if itype == "search" or name in SEARCH_FIELD_NAMES:
            continue
        if any(k in name for k in IDENTITY_KEYWORDS):
            score += 1
    return score


def choose_form(forms: list[Any]) -> Optional[Any]:
    """Pick the most likely contest-entry form, or ``None`` if none qualifies.

    A form must contain at least one identity field (name/email/address/…) to be
    considered an entry form; this filters out search boxes, login forms, and
    newsletter-only widgets that previously produced bogus "success" results.
    """
    best: Optional[Any] = None
    best_score = 0
    for form in forms:
        score = form_entry_score(form)
        if score > best_score:
            best, best_score = form, score
    return best


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


def evaluate_submission(status: int, text: str) -> tuple[bool, bool, str]:
    """Classify a submission response as ``(submitted, confirmed, note)``.

    ``confirmed`` is only True when the response text carries an explicit
    entry-confirmation phrase. A bare HTTP 200 counts as submitted-but-
    unconfirmed, because a 200 alone does not prove an entry was recorded.
    """
    low = text.lower()
    if any(phrase in low for phrase in SUCCESS_INDICATORS):
        return True, True, "Entry confirmed"
    if status >= 400:
        return False, False, f"HTTP {status}"
    if any(word in low for word in ERROR_INDICATORS):
        return False, False, "Response indicates a validation error"
    return True, False, f"Submitted, unconfirmed (HTTP {status})"


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
        "confirmed": False,
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
            if form is None:
                result["reason"] = "No entry form found"
                return result
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

            submitted, confirmed, note = evaluate_submission(*submit)
            result["submitted"] = submitted
            result["confirmed"] = confirmed
            result["reason"] = note
            if submitted:
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

    confirmed = unconfirmed = skipped = failed = 0
    for r in results:
        reason = r.get("reason", "")
        low_reason = reason.lower()
        if dry_run and r.get("submitted"):
            unconfirmed += 1
            label = "[green]Dry run OK[/]"
            notes = reason
        elif r.get("confirmed"):
            confirmed += 1
            label = "[green]Confirmed[/]"
            notes = reason
        elif r.get("submitted"):
            unconfirmed += 1
            label = "[cyan]Submitted?[/]"
            notes = reason
        elif "captcha" in low_reason:
            skipped += 1
            label = "[yellow]Skipped (CAPTCHA)[/]"
            notes = reason
        elif "no forms" in low_reason or "no entry form" in low_reason:
            skipped += 1
            label = "[yellow]Skipped (no entry form)[/]"
            notes = reason
        else:
            failed += 1
            label = "[red]Failed[/]"
            notes = reason
        table.add_row(f"[cyan]{r['url']}[/]", label, notes)

    console.print(Panel.fit("[bold cyan]📊 Contest Automation Summary[/]", border_style="cyan"))
    console.print(table)

    total = len(results)
    duration = (datetime.now() - start_time).total_seconds()
    if dry_run:
        headline = f"[bold green]Dry run complete — {unconfirmed}/{total} form(s) would be submitted in {duration:.1f}s[/]"
        breakdown = f"[white]Would submit:[/] [green]{unconfirmed}[/]   "
    else:
        headline = (
            f"[bold green]Automation complete — {confirmed} confirmed "
            f"of {total} pages in {duration:.1f}s[/]"
        )
        breakdown = (
            f"[white]Confirmed:[/] [green]{confirmed}[/]   "
            f"[white]Submitted (unconfirmed):[/] [cyan]{unconfirmed}[/]   "
        )
    console.print(
        Panel.fit(
            f"{headline}\n"
            f"{breakdown}"
            f"[white]Skipped:[/] [yellow]{skipped}[/]   "
            f"[white]Failed:[/] [red]{failed}[/]\n\n"
            f"[dim]\"Submitted (unconfirmed)\" means the page returned OK but no entry "
            f"confirmation was detected — it may not be a real entry.[/]\n"
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
