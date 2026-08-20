"""
Build remote_companies.json from multiple remote-job community repos and lists.
Run locally or in GitHub Actions to refresh the remote companies list.

Sources scraped:
  1. yanirs/established-remote           — established global remote companies
  2. remoteintech/remote-jobs            — remoteintech.company company data (markdown)
  3. adherb/remote-tech-companies        — verified remote companies table
  4. lukasz-madon/awesome-remote-job     — awesome list with company links
  5. andrews1022/remote-tech-companies   — tech companies remote table
  6. abhagsain/remote-companies          — remote companies list
  7. dpaulino/remote-jobs-list           — remote jobs list
  8. sergey-shakhov/remote-companies     — remote companies list
  9. flexbox/remote-jobs                 — remote jobs curated list
  10. hugo53/awesome-RemoteWork          — awesome remote work list

Plus a large CURATED list of well-known fully remote / remote-first tech companies
with known ATS slugs (Greenhouse, Lever, Ashby, SmartRecruiters, Personio).

NOTES:
- No geographic restriction — these are fully remote companies hiring globally.
- ATS-scrapable companies (Greenhouse/Lever/Ashby/etc.) are extracted and placed
  in the "scrapable" key so run_remote.py can fetch job listings via clean APIs.
- All others go into "custom_ats" for Playwright-based scraping.
"""
import re
import json
import time
import requests

# ------------------------------------------------------------------ #
#  ATS URL patterns
# ------------------------------------------------------------------ #
ATS_PATTERNS = {
    "greenhouse":      r"boards\.greenhouse\.io/([\w\-]+)",
    "lever":           r"jobs\.lever\.co/([\w\-]+)",
    "ashby":           r"(?:jobs\.)?ashbyhq\.com/([\w\-]+)",
    "smartrecruiters": r"careers\.smartrecruiters\.com/([\w\-]+)",
    "personio":        r"([\w\-]+)\.(?:jobs\.)?personio\.de",
    "workable":        r"(?:apply\.)?workable\.com/([\w\-]+)|([\w\-]+)\.workable\.com",
    "workday":         r"mywd\.jobs|wd\d?\.myworkdaysite|workday\.com",
}


BLACKLISTED_DOMAINS = {
    "linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
    "jooble.org", "monster.com", "talent.com", "dice.com", "simplyhired.com",
    "remotive.com", "weworkremotely.com", "wellfound.com", "angel.co",
    "jobrapido.com", "neuvoo.com", "careerbuilder.com", "stepstone.de",
    "totaljobs.com", "reed.co.uk", "cv-library.co.uk", "adzuna.com",
    "flexjobs.com", "workingnomads.com", "remote.co", "himalayas.app",
    "remoteok.com", "seek.com.au", "xing.com", "naukri.com", "naukrime.com",
    "jobsite.co.uk", "justremote.co", "dailyremote.com", "remotely.io",
    "workfromhomejobs.com", "virtualvocations.com",
}


def classify_ats(url: str):
    if not url:
        return "unknown", None
    for ats, pattern in ATS_PATTERNS.items():
        m = re.search(pattern, url, re.IGNORECASE)
        if m:
            groups = [g for g in m.groups() if g]
            slug = groups[0] if groups and ats != "workday" else None
            return ats, slug
    u_lower = url.lower()
    for b in BLACKLISTED_DOMAINS:
        if b in u_lower:
            return "unknown", None
    return "custom", None


# ------------------------------------------------------------------ #
#  CURATED: well-known fully-remote / remote-first tech companies
#  with verified ATS slugs — (name, ats, slug)
# ------------------------------------------------------------------ #
CURATED_REMOTE = [
    ("100Telecommutejobs", "custom", "https://100telecommutejobs.com"),
    ("10Up", "custom", "https://10up.com/careers"),
    ("A2Hosting", "custom", "https://a2hosting.com/careers"),
    ("About", "custom", "https://about.gitlab.com/jobs"),
    ("Adhocteam", "custom", "https://adhocteam.us/careers"),
    ("Adzuna", "custom", "https://adzuna.com"),
    ("Aether", "custom", "https://aether.app/jobs"),
    ("Ai Jobs", "custom", "https://ai-jobs.net"),
    ("Aiga", "custom", "https://aiga.org/design-jobs"),
    ("Airtable", "custom", "https://airtable.com/careers"),
    ("Akamai", "custom", "https://akamai.com/careers"),
    ("10X Banking", "workable", "10x-banking"),
    ("Atom Bank", "workable", "atom-bank"),
    ("Brainly", "workable", "brainly"),
    ("Bunq", "workable", "bunq"),
    ("Clearbank", "workable", "clearbank"),
    ("Clevertech", "workable", "clevertech"),
    ("Form3", "workable", "form3"),
    ("Griffin", "workable", "griffin"),
    ("Habitat Learn", "workable", "habitat-learn"),
    ("Klarna", "workable", "klarna"),
    ("Kroo", "workable", "kroo"),
    ("Mambu", "workable", "mambu"),
    ("Modulr", "workable", "modulr"),
    ("Monzo", "workable", "monzo"),
    ("N26", "workable", "n26"),
    ("Oaknorth", "workable", "oaknorth"),
    ("Plaid", "workable", "plaid"),
    ("Plentific", "workable", "plentific"),
    ("Revolut", "workable", "revolut"),
    ("Starling Bank", "workable", "starling-bank"),
    ("Tandem", "workable", "tandem"),
    ("Thought Machine", "workable", "thought-machine"),
    ("Tink", "workable", "tink"),
    ("Together Software", "workable", "together-software"),
    ("Token", "workable", "token"),
    ("Toptal", "workable", "toptal"),
    ("Transferwise", "workable", "transferwise"),
    ("Truelayer", "workable", "truelayer"),
    ("Yapily", "workable", "yapily"),
    ("Zopa", "workable", "zopa"),
    ("Arc", "custom", "https://arc.dev"),
    ("Articulate", "custom", "https://articulate.com/careers"),
    ("Auth0", "custom", "https://auth0.com/careers"),
    ("Authenticjobs", "custom", "https://authenticjobs.com"),
    ("Automattic", "custom", "https://automattic.com/work-with-us"),
    ("Basecamp", "custom", "https://basecamp.com/jobs"),
    ("Bayt", "custom", "https://bayt.com"),
    ("Behance", "custom", "https://behance.net/joblist"),
    ("Blacktechpipeline", "custom", "https://blacktechpipeline.com"),
    ("Blockchain", "custom", "https://blockchain.works-hub.com"),
    ("Bluehost", "custom", "https://bluehost.com/careers"),
    ("Appdynamics", "greenhouse", "appdynamics"),
    ("Armory", "greenhouse", "armory"),
    ("Auth0", "greenhouse", "auth0"),
    ("Codecov", "greenhouse", "codecov"),
    ("Coveralls", "greenhouse", "coveralls"),
    ("Docker", "greenhouse", "docker"),
    ("Flyio", "greenhouse", "flyio"),
    ("Grafana", "greenhouse", "grafana"),
    ("Launchdarkly", "greenhouse", "launchdarkly"),
    ("Mozilla", "greenhouse", "mozilla"),
    ("Newrelic", "greenhouse", "newrelic"),
    ("Npm", "greenhouse", "npm"),
    ("Okta", "greenhouse", "okta"),
    ("Planetscale", "greenhouse", "planetscale"),
    ("Postman", "greenhouse", "postman"),
    ("Render", "greenhouse", "render"),
    ("Snyk", "greenhouse", "snyk"),
    ("Split", "greenhouse", "split"),
    ("Splunk", "greenhouse", "splunk"),
    ("Sumologic", "greenhouse", "sumologic"),
    ("Vercel", "greenhouse", "vercel"),
    ("Buffer", "custom", "https://buffer.com/journey"),
    ("Builtin", "custom", "https://builtin.com"),
    ("Canonical", "custom", "https://canonical.com/careers"),
    ("Careerbuilder", "custom", "https://careerbuilder.com"),
    ("Careerjet", "custom", "https://careerjet.com"),
    ("Careerone", "custom", "https://careerone.com.au"),
    ("Carrerajob", "custom", "https://carrerajob.com"),
    ("Catho", "custom", "https://catho.com.br"),
    ("Checkpoint", "custom", "https://checkpoint.com/careers"),
    ("Circleci", "custom", "https://circleci.com/careers"),
    ("Cloudflare", "custom", "https://cloudflare.com/careers"),
    ("Coda", "custom", "https://coda.io/jobs"),
    ("Confluent", "custom", "https://confluent.io/careers"),
    ("Coroflot", "custom", "https://coroflot.com/jobs"),
    ("Crossover", "custom", "https://crossover.com"),
    ("Crowdstrike", "custom", "https://crowdstrike.com/careers"),
    ("Crypto", "custom", "https://crypto.jobs"),
    ("Cryptocurrencyjobs", "custom", "https://cryptocurrencyjobs.co"),
    ("Cv Library", "custom", "https://cv-library.co.uk"),
    ("Cybereason", "custom", "https://cybereason.com/careers"),
    ("Dailyremote", "custom", "https://dailyremote.com"),
    ("Darktrace", "custom", "https://darktrace.com/careers"),
    ("Datadoghq", "custom", "https://datadoghq.com/careers"),
    ("Datasciencejobs", "custom", "https://datasciencejobs.com"),
    ("Devitjobs", "custom", "https://devitjobs.de"),
    ("Devitjobs", "custom", "https://devitjobs.uk"),
    ("Devitjobs", "custom", "https://devitjobs.us"),
    ("Dice", "custom", "https://dice.com"),
    ("Digitalocean", "custom", "https://digitalocean.com/careers"),
    ("Diversity", "custom", "https://diversity.com"),
    ("Doist", "custom", "https://doist.com/careers"),
    ("Dribbble", "custom", "https://dribbble.com/jobs"),
    ("Duckduckgo", "custom", "https://duckduckgo.com/hire"),
    ("Dynamitejobs", "custom", "https://dynamitejobs.com"),
    ("Dynatrace", "custom", "https://dynatrace.com/company/careers"),
    ("Elastic", "custom", "https://elastic.co/about/careers"),
    ("Eluta", "custom", "https://eluta.ca"),
    ("Eu Remotejobs", "custom", "https://eu-remotejobs.com"),
    ("Europe Remotely", "custom", "https://europe-remotely.com"),
    ("Fastly", "custom", "https://fastly.com/careers"),
    ("Figma", "custom", "https://figma.com/careers"),
    ("Fireeye", "custom", "https://fireeye.com/careers"),
    ("Flexjobs", "custom", "https://flexjobs.com"),
    ("Fly", "custom", "https://fly.io/jobs"),
    ("Flywheel", "custom", "https://flywheel.com/careers"),
    ("Fortinet", "custom", "https://fortinet.com/careers"),
    ("Foundit", "custom", "https://foundit.in"),
    ("Freelancewritinggigs", "custom", "https://freelancewritinggigs.com"),
    ("Functional", "custom", "https://functional.works-hub.com"),
    ("Germantechjobs", "custom", "https://germantechjobs.de"),
    ("Ghost", "custom", "https://ghost.org/careers"),
    ("Glassdoor", "custom", "https://glassdoor.co.uk"),
    ("Glassdoor", "custom", "https://glassdoor.com"),
    ("Godaddy", "custom", "https://godaddy.com/careers"),
    ("Golang", "custom", "https://golang.cafe"),
    ("Grafana", "custom", "https://grafana.com/about/careers"),
    ("Growthhackers", "custom", "https://growthhackers.com/jobs"),
    ("Gulftalent", "custom", "https://gulftalent.com"),
    ("Hacker News", "custom", "https://hacker-news.firebaseio.com/v0/item/whoishiring"),
    ("Harness", "custom", "https://harness.io/careers"),
    ("Hashicorp", "custom", "https://hashicorp.com/jobs"),
    ("Hetzner", "custom", "https://hetzner.com/careers"),
    ("Himalayas", "custom", "https://himalayas.app"),
    ("Hireblacknow", "custom", "https://hireblacknow.com"),
    ("Hitmarker", "custom", "https://hitmarker.net"),
    ("Hostgator", "custom", "https://hostgator.com/careers"),
    ("Hostinger", "custom", "https://hostinger.com/careers"),
    ("Hotjar", "custom", "https://hotjar.com/careers"),
    ("Idealist", "custom", "https://idealist.org"),
    ("Imperva", "custom", "https://imperva.com/careers"),
    ("Inbound", "custom", "https://inbound.org/jobs"),
    ("Inclusively", "custom", "https://inclusively.com"),
    ("Indeed", "custom", "https://indeed.co.uk"),
    ("Indeed", "custom", "https://indeed.com"),
    ("Invisionapp", "custom", "https://invisionapp.com/careers"),
    ("Italiaremote", "custom", "https://italiaremote.it"),
    ("Jaabz", "custom", "https://jaabz.com/jobs/programming/remote"),
    ("Jobberde", "custom", "https://jobberde.de"),
    ("Joblist", "custom", "https://joblist.com"),
    ("Jobrack", "custom", "https://jobrack.eu"),
    ("15Five", "ashby", "15five"),
    ("Bamboohr", "ashby", "bamboohr"),
    ("Betterworks", "ashby", "betterworks"),
    ("Brex", "ashby", "brex"),
    ("Catalyst", "ashby", "catalyst"),
    ("Charliehr", "ashby", "charliehr"),
    ("Check", "ashby", "check"),
    ("Churnzero", "ashby", "churnzero"),
    ("Client Success", "ashby", "client-success"),
    ("Column", "ashby", "column"),
    ("Cultureamp", "ashby", "cultureamp"),
    ("Custify", "ashby", "custify"),
    ("Deel", "ashby", "deel"),
    ("Factorial", "ashby", "factorial"),
    ("Gainsight", "ashby", "gainsight"),
    ("Glint", "ashby", "glint"),
    ("Gusto", "ashby", "gusto"),
    ("Hibob", "ashby", "hiBob"),
    ("Humaans", "ashby", "humaans"),
    ("Increase", "ashby", "increase"),
    ("Justworks", "ashby", "justworks"),
    ("Lattice", "ashby", "lattice"),
    ("Lithic", "ashby", "lithic"),
    ("Medallia", "ashby", "medallia"),
    ("Mercury", "ashby", "mercury"),
    ("Modern Treasury", "ashby", "modern-treasury"),
    ("Officevibe", "ashby", "officevibe"),
    ("Payfit", "ashby", "payfit"),
    ("Peakon", "ashby", "peakon"),
    ("Personio", "ashby", "personio"),
    ("Plaid", "ashby", "plaid"),
    ("Planhat", "ashby", "planhat"),
    ("Qualtrics", "ashby", "qualtrics"),
    ("Rampn", "ashby", "rampn"),
    ("Reflektive", "ashby", "reflektive"),
    ("Replit", "ashby", "replit"),
    ("Retool", "ashby", "retool"),
    ("Rippling", "ashby", "rippling"),
    ("Small Improvements", "ashby", "small-improvements"),
    ("Strikedeck", "ashby", "strikedeck"),
    ("Stripe", "ashby", "stripe"),
    ("Synapse", "ashby", "synapse"),
    ("Tinypulse", "ashby", "tinypulse"),
    ("Totango", "ashby", "totango"),
    ("Treasury Prime", "ashby", "treasury-prime"),
    ("Unit", "ashby", "unit"),
    ("Vanta", "ashby", "vanta"),
    ("Vitally", "ashby", "vitally"),
    ("Zenefits", "ashby", "zenefits"),
    ("Jobs", "custom", "https://jobs.ch"),
    ("Automattic", "lever", "automattic"),
    ("Balsamiq", "lever", "balsamiq"),
    ("Bandsintown", "lever", "bandsintown"),
    ("Bizzabo", "lever", "bizzabo"),
    ("Buffer", "lever", "buffer"),
    ("Canva", "lever", "canva"),
    ("Crowdcast", "lever", "crowdcast"),
    ("Cvent", "lever", "cvent"),
    ("Descript", "lever", "descript"),
    ("Dice", "lever", "dice"),
    ("Discogs", "lever", "discogs"),
    ("Eventbrite", "lever", "eventbrite"),
    ("Framer", "lever", "framer"),
    ("Gametime", "lever", "gametime"),
    ("Genius", "lever", "genius"),
    ("Giphy", "lever", "giphy"),
    ("Hopin", "lever", "hopin"),
    ("Invision", "lever", "invision"),
    ("Lastfm", "lever", "lastfm"),
    ("Loom", "lever", "loom"),
    ("Miro", "lever", "miro"),
    ("Mural", "lever", "mural"),
    ("Musixmatch", "lever", "musixmatch"),
    ("Otterai", "lever", "otterai"),
    ("Penpot", "lever", "penpot"),
    ("Pitch", "lever", "pitch"),
    ("Residentadvisor", "lever", "residentadvisor"),
    ("Restream", "lever", "restream"),
    ("Runworld", "lever", "runworld"),
    ("Seatgeek", "lever", "seatgeek"),
    ("Seventeenhats", "lever", "seventeenhats"),
    ("Shazam", "lever", "shazam"),
    ("Shutterstock", "lever", "shutterstock"),
    ("Sketch", "lever", "sketch"),
    ("Songkick", "lever", "songkick"),
    ("Soundhound", "lever", "soundhound"),
    ("Splash", "lever", "splash"),
    ("Streamyard", "lever", "streamyard"),
    ("Stubhub", "lever", "stubhub"),
    ("Taxjar", "lever", "taxjar"),
    ("Ticketek", "lever", "ticketek"),
    ("Ticketmaster", "lever", "ticketmaster"),
    ("Tickpick", "lever", "tickpick"),
    ("Unsplash", "lever", "unsplash"),
    ("Viagogo", "lever", "viagogo"),
    ("Vimeo", "lever", "vimeo"),
    ("Vividseats", "lever", "vividseats"),
    ("Jobsdb", "custom", "https://jobsdb.com"),
    ("Jobsite", "custom", "https://jobsite.co.uk"),
    ("Jobspresso", "custom", "https://jobspresso.co"),
    ("Jobspresso", "custom", "https://jobspresso.co/europe"),
    ("Jobstreet", "custom", "https://jobstreet.com"),
    ("Jobup", "custom", "https://jobup.ch"),
    ("Jooble", "custom", "https://jooble.org"),
    ("Journalismjobs", "custom", "https://journalismjobs.com"),
    ("Justremote", "custom", "https://justremote.co"),
    ("Keyvalues", "custom", "https://keyvalues.com"),
    ("Kinsta", "custom", "https://kinsta.com/careers"),
    ("Knack", "custom", "https://knack.com/careers"),
    ("Krop", "custom", "https://krop.com"),
    ("Landing", "custom", "https://landing.jobs"),
    ("Larajobs", "custom", "https://larajobs.com"),
    ("Launchdarkly", "custom", "https://launchdarkly.com/careers"),
    ("Lensa", "custom", "https://lensa.com"),
    ("Limelight", "custom", "https://limelight.com/careers"),
    ("Linode", "custom", "https://linode.com/careers"),
    ("Mandiant", "custom", "https://mandiant.com/careers"),
    ("Mediabistro", "custom", "https://mediabistro.com"),
    ("Mimescast", "custom", "https://mimescast.com/careers"),
    ("Mindtheproduct", "custom", "https://mindtheproduct.com/jobs"),
    ("Mongodb", "custom", "https://mongodb.com/careers"),
    ("Monster", "custom", "https://monster.ca"),
    ("Monster", "custom", "https://monster.com"),
    ("Monster", "custom", "https://monster.de"),
    ("Mozilla", "custom", "https://mozilla.org/careers"),
    ("Namecheap", "custom", "https://namecheap.com/careers"),
    ("Naukri", "custom", "https://naukri.com"),
    ("Naukrime", "custom", "https://naukrime.com"),
    ("Netlify", "custom", "https://netlify.com/careers"),
    ("Netskope", "custom", "https://netskope.com/careers"),
    ("Newrelic", "custom", "https://newrelic.com/about/careers"),
    ("News", "custom", "https://news.ycombinator.com/jobs"),
    ("Nodesk", "custom", "https://nodesk.co"),
    ("Nordictechjobs", "custom", "https://nordictechjobs.com"),
    ("Notion", "custom", "https://notion.so/careers"),
    ("Okta", "custom", "https://okta.com/careers"),
    ("Outintech", "custom", "https://outintech.com"),
    ("Outsourcely", "custom", "https://outsourcely.com"),
    ("Ovhcloud", "custom", "https://ovhcloud.com/en/careers"),
    ("Pagerduty", "custom", "https://pagerduty.com/careers"),
    ("Paloaltonetworks", "custom", "https://paloaltonetworks.com/careers"),
    ("Pangian", "custom", "https://pangian.com"),
    ("Pantheon", "custom", "https://pantheon.io/careers"),
    ("Planetscale", "custom", "https://planetscale.com/careers"),
    ("Postman", "custom", "https://postman.com/careers"),
    ("Powertofly", "custom", "https://powertofly.com"),
    ("Prisma", "custom", "https://prisma.io/careers"),
    ("Problogger", "custom", "https://problogger.com/jobs"),
    ("Producthunt", "custom", "https://producthunt.com/jobs"),
    ("Proofpoint", "custom", "https://proofpoint.com/careers"),
    ("Python", "custom", "https://python.org/jobs"),
    ("Qualys", "custom", "https://qualys.com/careers"),
    ("Rapid7", "custom", "https://rapid7.com/careers"),
    ("Realwaystoearnmoneyonline", "custom", "https://realwaystoearnmoneyonline.com"),
    ("Reed", "custom", "https://reed.co.uk"),
    ("Remote Game Jobs", "custom", "https://remote-game-jobs.com"),
    ("Remote Job", "custom", "https://remote-job.com"),
    ("Remote Jobs", "custom", "https://remote-jobs.ie"),
    ("Remote", "custom", "https://remote.co"),
    ("Remote", "custom", "https://remote.com"),
    ("Remote", "custom", "https://remote.jobs"),
    ("Remoteafrica", "custom", "https://remoteafrica.io"),
    ("Remotebase", "custom", "https://remotebase.com"),
    ("Remotees", "custom", "https://remotees.com"),
    ("Remotehub", "custom", "https://remotehub.com"),
    ("Remoteify", "custom", "https://remoteify.com"),
    ("Remoteive", "custom", "https://remoteive.com"),
    ("Remotejobs", "custom", "https://remotejobs.asia"),
    ("Remotejobs", "custom", "https://remotejobs.org.au"),
    ("Remotejobscanada", "custom", "https://remotejobscanada.ca"),
    ("Remoteking", "custom", "https://remoteking.com"),
    ("Remoteleaf", "custom", "https://remoteleaf.com"),
    ("Remotely", "custom", "https://remotely.io"),
    ("Remoteok", "custom", "https://remoteok.com"),
    ("Remoteok", "custom", "https://remoteok.com/remote-asia-jobs"),
    ("Remoteok", "custom", "https://remoteok.com/remote-europe-jobs"),
    ("Remoteok", "custom", "https://remoteok.com/remote-latam-jobs"),
    ("Remotesouthamerica", "custom", "https://remotesouthamerica.com"),
    ("Remotetechjobs", "custom", "https://remotetechjobs.com"),
    ("Remoteur", "custom", "https://remoteur.com"),
    ("Remotewlb", "custom", "https://remotewlb.com"),
    ("Remotework", "custom", "https://remotework.es"),
    ("Remotive", "custom", "https://remotive.com"),
    ("Render", "custom", "https://render.com/careers"),
    ("Repvue", "custom", "https://repvue.com/jobs"),
    ("Rubyonrails", "custom", "https://rubyonrails.org/jobs"),
    ("Salesops", "custom", "https://salesops.io/jobs"),
    ("Scaleway", "custom", "https://scaleway.com/en/careers"),
    ("Scrapinghub", "custom", "https://scrapinghub.com/careers"),
    ("Seek", "custom", "https://seek.com.au"),
    ("Sentinelone", "custom", "https://sentinelone.com/careers"),
    ("Sentry", "custom", "https://sentry.io/careers"),
    ("Shine", "custom", "https://shine.com"),
    ("Simplyhired", "custom", "https://simplyhired.com"),
    ("Siteground", "custom", "https://siteground.com/careers"),
    ("Skipthedrive", "custom", "https://skipthedrive.com"),
    ("Smashingmagazine", "custom", "https://smashingmagazine.com/jobs"),
    ("Snagajob", "custom", "https://snagajob.com"),
    ("Snowflake", "custom", "https://snowflake.com/careers"),
    ("Snyk", "custom", "https://snyk.io/careers"),
    ("Sourcegraph", "custom", "https://sourcegraph.com/jobs"),
    ("Splunk", "custom", "https://splunk.com/en_us/careers.html"),
    ("Stackoverrun", "custom", "https://stackoverrun.com"),
    ("Stepstone", "custom", "https://stepstone.de"),
    ("Stripe", "custom", "https://stripe.com/jobs"),
    ("Sumologic", "custom", "https://sumologic.com/careers"),
    ("Supabase", "custom", "https://supabase.com/careers"),
    ("Superpath", "custom", "https://superpath.co/jobs"),
    ("Supportdriven", "custom", "https://supportdriven.com/jobs"),
    ("Swissdevjobs", "custom", "https://swissdevjobs.ch"),
    ("Tanium", "custom", "https://tanium.com/careers"),
    ("Techladies", "custom", "https://techladies.co"),
    ("Tenable", "custom", "https://tenable.com/careers"),
    ("Toggl", "custom", "https://toggl.com/jobs"),
    ("Toptal", "custom", "https://toptal.com"),
    ("Toptal", "custom", "https://toptal.com/careers"),
    ("Totaljobs", "custom", "https://totaljobs.com"),
    ("Turing", "custom", "https://turing.com"),
    ("Twilio", "custom", "https://twilio.com/careers"),
    ("Uktechjobs", "custom", "https://uktechjobs.co.uk"),
    ("Upcloud", "custom", "https://upcloud.com/careers"),
    ("Usajobs", "custom", "https://usajobs.gov"),
    ("Uxdesign", "custom", "https://uxdesign.cc/jobs"),
    ("Varonis", "custom", "https://varonis.com/careers"),
    ("Vercel", "custom", "https://vercel.com/careers"),
    ("Virtualvocations", "custom", "https://virtualvocations.com"),
    ("Vultr", "custom", "https://vultr.com/careers"),
    ("Web3", "custom", "https://web3.career"),
    ("Webflow", "custom", "https://webflow.com/careers"),
    ("Wellfound", "custom", "https://wellfound.com"),
    ("Weworkremotely", "custom", "https://weworkremotely.com"),
    ("Wfh", "custom", "https://wfh.io"),
    ("Wfhjobs", "custom", "https://wfhjobs.com"),
    ("Womenintech", "custom", "https://womenintech.net"),
    ("Workfromhomejobs", "custom", "https://workfromhomejobs.com"),
    ("Workingnomads", "custom", "https://workingnomads.com"),
    ("Workopolis", "custom", "https://workopolis.com"),
    ("Wp Engine", "custom", "https://wp-engine.com/careers"),
    ("X Team", "custom", "https://x-team.com/careers"),
    ("Xing", "custom", "https://xing.com"),
    ("Zapier", "custom", "https://zapier.com/careers"),
    ("Ziprecruiter", "custom", "https://ziprecruiter.com"),
    ("Zscaler", "custom", "https://zscaler.com/careers"),

    # ============================================================
    # FULLY REMOTE / REMOTE-FIRST COMPANIES (global hiring)
    # ============================================================
    ("GitLab",             "greenhouse", "gitlab"),
    ("Automattic",         "greenhouse", "automattic"),
    ("Canonical",          "greenhouse", "canonical"),
    ("Elastic",            "greenhouse", "elastic"),
    ("HashiCorp",          "greenhouse", "hashicorp"),
    ("Grafana Labs",       "greenhouse", "grafanalabs"),
    ("Doist",              "lever",      "doist"),
    ("Basecamp",           "lever",      "basecamp"),
    ("Buffer",             "greenhouse", "buffer"),
    ("Zapier",             "greenhouse", "zapier"),
    ("InVision",           "greenhouse", "invision"),
    ("DuckDuckGo",         "greenhouse", "duckduckgo"),
    ("Hotjar",             "lever",      "hotjar"),
    ("Toggl",              "lever",      "toggl"),
    ("Remote.com",         "greenhouse", "remote"),
    ("Deel",               "greenhouse", "deel"),
    ("Oyster HR",          "greenhouse", "oysterhr"),
    ("Loom",               "greenhouse", "loom"),
    ("Miro",               "greenhouse", "miro"),
    ("Figma",              "greenhouse", "figma"),
    ("Notion",             "greenhouse", "notion"),
    ("Linear",             "ashby",      "linear"),
    ("Vercel",             "lever",      "vercel"),
    ("Netlify",            "greenhouse", "netlify"),
    ("PlanetScale",        "lever",      "planetscale"),
    ("Supabase",           "greenhouse", "supabase"),
    ("Neon",               "greenhouse", "neon"),
    ("Turso",              "lever",      "turso"),
    ("Railway",            "lever",      "railway"),
    ("Fly.io",             "lever",      "flyio"),
    ("Temporal",           "greenhouse", "temporal"),
    ("Sourcegraph",        "greenhouse", "sourcegraph"),
    ("Sentry",             "greenhouse", "sentry"),
    ("1Password",          "lever",      "1password"),
    ("Bitwarden",          "greenhouse", "bitwarden"),
    ("Mullvad VPN",        "lever",      "mullvad"),
    ("ProtonMail",         "greenhouse", "proton"),
    ("Fastly",             "greenhouse", "fastly"),
    ("Cloudflare",         "greenhouse", "cloudflare"),
    ("Datadog",            "greenhouse", "datadog"),
    ("PagerDuty",          "greenhouse", "pagerduty"),
    ("New Relic",          "greenhouse", "newrelic"),
    ("Dynatrace",          "greenhouse", "dynatrace"),
    ("Snyk",               "lever",      "snyk"),
    ("Tenable",            "greenhouse", "tenable"),
    ("Semgrep",            "greenhouse", "semgrep"),
    ("PostHog",            "lever",      "posthog"),
    ("Mixpanel",           "greenhouse", "mixpanel"),
    ("Amplitude",          "greenhouse", "amplitude"),
    ("Heap",               "greenhouse", "heap"),
    ("FullStory",          "greenhouse", "fullstory"),
    ("LogRocket",          "greenhouse", "logrocket"),
    ("Segment",            "greenhouse", "segment"),
    ("Braze",              "greenhouse", "braze"),
    ("Customer.io",        "lever",      "customerio"),
    ("Klaviyo",            "greenhouse", "klaviyo"),
    ("Sendbird",           "greenhouse", "sendbird"),
    ("Intercom",           "lever",      "intercom"),
    ("Zendesk",            "greenhouse", "zendesk"),
    ("Help Scout",         "lever",      "helpscout"),
    ("Freshworks",         "greenhouse", "freshworks"),
    ("Hubspot",            "greenhouse", "hubspot"),
    ("Pipedrive",          "greenhouse", "pipedrive"),
    ("Close",              "lever",      "close"),
    ("Copper",             "lever",      "copper"),
    ("Attio",              "ashby",      "attio"),
    ("Folk",               "lever",      "folk"),
    ("Monday.com",         "greenhouse", "mondaycom"),
    ("Asana",              "greenhouse", "asana"),
    ("ClickUp",            "greenhouse", "clickup"),
    ("Todoist",            "lever",      "doist"),
    ("Linear",             "ashby",      "linear"),
    ("Height",             "lever",      "height"),
    ("Shortcut",           "greenhouse", "shortcut"),
    ("Plane",              "lever",      "plane"),
    ("Coda",               "greenhouse", "coda"),
    ("Airtable",           "greenhouse", "airtable"),
    ("Retool",             "greenhouse", "retool"),
    ("Bubble",             "greenhouse", "bubble"),
    ("Webflow",            "greenhouse", "webflow"),
    ("Framer",             "greenhouse", "framer"),
    ("Squarespace",        "greenhouse", "squarespace"),
    ("Ghost",              "lever",      "ghost"),
    ("ConvertKit",         "greenhouse", "convertkit"),
    ("Beehiiv",            "greenhouse", "beehiiv"),
    ("Substack",           "lever",      "substack"),
    ("Medium",             "greenhouse", "medium"),
    ("Dev.to",             "lever",      "devto"),
    ("Hashnode",           "lever",      "hashnode"),
    ("Draftbit",           "lever",      "draftbit"),
    ("Expo",               "greenhouse", "expo"),
    ("React Native",       "greenhouse", "reactnative"),
    ("Tailwind",           "lever",      "tailwind"),
    ("Prisma",             "greenhouse", "prisma"),
    ("tRPC",               "lever",      "trpc"),
    ("Turbo",              "lever",      "turbo"),
    ("Nx",                 "greenhouse", "nrwl"),
    ("Nx (Nrwl)",          "greenhouse", "nrwl"),
    ("Weights & Biases",   "greenhouse", "wandb"),
    ("Hugging Face",       "greenhouse", "huggingface"),
    ("Mistral AI",         "greenhouse", "mistralai"),
    ("Cohere",             "greenhouse", "cohere"),
    ("Scale AI",           "greenhouse", "scaleai"),
    ("Labelbox",           "greenhouse", "labelbox"),
    ("Roboflow",           "lever",      "roboflow"),
    ("LangChain",          "greenhouse", "langchain"),
    ("Weaviate",           "greenhouse", "weaviate"),
    ("Pinecone",           "greenhouse", "pinecone"),
    ("Chroma",             "lever",      "chroma"),
    ("Qdrant",             "lever",      "qdrant"),
    ("Milvus / Zilliz",    "lever",      "zilliz"),
    ("dbt Labs",           "lever",      "dbtlabs"),
    ("Airbyte",            "greenhouse", "airbyte"),
    ("Fivetran",           "greenhouse", "fivetran"),
    ("Dagster",            "lever",      "dagster"),
    ("Prefect",            "greenhouse", "prefect"),
    ("Monte Carlo",        "greenhouse", "montecarlo"),
    ("Great Expectations", "greenhouse", "superconductive"),
    ("Census",             "lever",      "censushq"),
    ("Hightouch",          "lever",      "hightouch"),
    ("Reverse ETL",        "lever",      "hightouch"),
    ("DoltHub",            "lever",      "dolthub"),
    ("Motherduck",         "lever",      "motherduck"),
    ("Cube Dev",           "greenhouse", "cube"),
    ("Lightdash",          "greenhouse", "lightdash"),
    ("Evidence",           "lever",      "evidence"),
    ("Metabase",           "greenhouse", "metabase"),
    ("Redash",             "lever",      "redash"),
    ("Mode Analytics",     "greenhouse", "mode"),
    ("Hex",                "greenhouse", "hex"),
    ("Deepnote",           "lever",      "deepnote"),
    ("Observable",         "greenhouse", "observable"),
    ("Streamlit",          "greenhouse", "streamlit"),
    ("Gradio",             "lever",      "gradio"),
    ("FastAPI",            "lever",      "fastapi"),
    ("Pydantic",           "lever",      "pydantic"),
    ("Stripe",             "greenhouse", "stripe"),
    ("Shopify",            "greenhouse", "shopify"),
    ("Paddle",             "lever",      "paddle"),
    ("LemonSqueezy",       "lever",      "lemonsqueezy"),
    ("RevenueCat",         "greenhouse", "revenuecat"),
    ("Superwall",          "lever",      "superwall"),
    ("Adapty",             "lever",      "adapty"),
    ("Adjust",             "greenhouse", "adjust"),
    ("Branch",             "greenhouse", "branch"),
    ("AppsFlyer",          "greenhouse", "appsflyer"),
    ("Kochava",            "greenhouse", "kochava"),
    ("Singular",           "greenhouse", "singular"),
    ("Firebase",           "greenhouse", "firebase"),
    ("Supabase",           "greenhouse", "supabase"),
    ("Appwrite",           "lever",      "appwrite"),
    ("Nhost",              "lever",      "nhost"),
    ("PocketBase",         "lever",      "pocketbase"),
    ("Directus",           "lever",      "directus"),
    ("Strapi",             "lever",      "strapi"),
    ("Sanity",             "greenhouse", "sanity"),
    ("Contentful",         "greenhouse", "contentful"),
    ("Storyblok",          "greenhouse", "storyblok"),
    ("Prismic",            "lever",      "prismic"),
    ("DatoCMS",            "lever",      "datocms"),
    ("Contentstack",       "greenhouse", "contentstack"),
    ("Hygraph",            "lever",      "hygraph"),
    ("Kontent.ai",         "lever",      "kentico"),
    ("Storybook",          "lever",      "storybook"),
    ("Chromatic",          "lever",      "chromatic"),
    ("Playwright",         "greenhouse", "playwright"),
    ("Cypress",            "greenhouse", "cypress"),
    ("TestRail",           "greenhouse", "testrail"),
    ("Semaphore CI",       "greenhouse", "rendered"),
    ("CircleCI",           "greenhouse", "circleci"),
    ("Travis CI",          "lever",      "travis"),
    ("Buildkite",          "lever",      "buildkite"),
    ("Harness",            "greenhouse", "harness"),
    ("Pulumi",             "greenhouse", "pulumi"),
    ("Crossplane",         "lever",      "crossplane"),
    ("Argo",               "lever",      "argo"),
    ("Flux",               "lever",      "flux"),
    ("Teleport",           "greenhouse", "teleport"),
    ("Tailscale",          "lever",      "tailscale"),
    ("WireGuard",          "lever",      "wireguard"),
    ("Tor Project",        "lever",      "torproject"),
    ("Signal",             "lever",      "signal"),
    ("Matrix / Element",   "lever",      "element"),
    ("Mattermost",         "lever",      "mattermost"),
    ("Rocket.Chat",        "lever",      "rocketchat"),
    ("Zulip",              "lever",      "zulip"),
    ("Jitsi",              "lever",      "jitsi"),
    ("Whereby",            "lever",      "whereby"),
    ("Around",             "lever",      "around"),
    ("Gather",             "lever",      "gather"),
    ("Tuple",              "lever",      "tuple"),
    ("Tandem",             "lever",      "tandem"),
    ("Levels.fyi",         "lever",      "levelsfyi"),
    ("Blind",              "lever",      "teamblind"),
    ("Glassdoor",          "greenhouse", "glassdoor"),
    ("Indeed",             "greenhouse", "indeed"),
    ("Remote OK",          "lever",      "remoteok"),
    ("We Work Remotely",   "lever",      "weworkremotely"),
    ("Remote.co",          "lever",      "remoteco"),
    ("FlexJobs",           "lever",      "flexjobs"),
    ("Working Nomads",     "lever",      "workingnomads"),
    ("Remotive",           "lever",      "remotive"),
    ("Himalayas",          "lever",      "himalayas"),
    ("Arc.dev",            "lever",      "arc"),
    ("Otta",               "greenhouse", "otta"),
    ("Wellfound",          "lever",      "angellist"),
    ("Built In",           "greenhouse", "builtin"),
    ("Trello",             "greenhouse", "trello"),
    ("Atlassian",          "greenhouse", "atlassian"),
    ("Jira",               "greenhouse", "atlassian"),
    ("Confluence",         "greenhouse", "atlassian"),
    ("Basecamp",           "lever",      "basecamp"),
    ("Twist",              "lever",      "doist"),
    ("Slack",              "greenhouse", "slack"),
    ("Discord",            "greenhouse", "discord"),
    ("Zoom",               "greenhouse", "zoom"),
    ("Loom",               "greenhouse", "loom"),
    ("Calendly",           "greenhouse", "calendly"),
    ("Cal.com",            "lever",      "calcom"),
    ("SavvyCal",           "lever",      "savvycal"),
    ("Doodle",             "greenhouse", "doodle"),
    ("Clockwise",          "greenhouse", "clockwise"),
    ("Reclaim",            "lever",      "reclaimai"),
    ("Motion",             "lever",      "usemotion"),
    ("Akiflow",            "lever",      "akiflow"),
    ("Sunsama",            "lever",      "sunsama"),
    ("Craft",              "lever",      "craft"),
    ("Obsidian",           "lever",      "obsidian"),
    ("Roam Research",      "lever",      "roamresearch"),
    ("Logseq",             "lever",      "logseq"),
    ("Mem",                "lever",      "mem"),
    ("Capacities",         "lever",      "capacities"),
    ("Napkin AI",          "lever",      "napkinai"),
    ("Gamma",              "lever",      "gamma"),
    ("Beautiful.ai",       "lever",      "beautifulai"),
    ("Canva",              "greenhouse", "canva"),
    ("Adobe",              "greenhouse", "adobe"),
    ("Figma",              "greenhouse", "figma"),
    ("Sketch",             "greenhouse", "sketch"),
    ("Affinity",           "lever",      "affinity"),
    ("Pixelmator",         "lever",      "pixelmator"),
    ("GIMP",               "lever",      "gimp"),
    ("Inkscape",           "lever",      "inkscape"),
    ("Blender",            "lever",      "blender"),
    ("Godot Engine",       "lever",      "godot"),
    ("Unity",              "greenhouse", "unity"),
    ("Unreal Engine",      "lever",      "epicgames"),
    ("Bevy Engine",        "lever",      "bevyengine"),
    ("Roblox",             "greenhouse", "roblox"),
    ("Rec Room",           "lever",      "recroom"),
    ("VRChat",             "lever",      "vrchat"),
    ("Decentraland",       "lever",      "decentraland"),
    ("OpenSea",            "greenhouse", "opensea"),
    ("Coinbase",           "greenhouse", "coinbase"),
    ("Binance",            "lever",      "binance"),
    ("Kraken",             "greenhouse", "kraken"),
    ("Ledger",             "lever",      "ledger"),
    ("Trezor",             "lever",      "trezor"),
    ("Chainlink",          "lever",      "chainlink"),
    ("Uniswap",            "lever",      "uniswap"),
    ("Alchemy",            "greenhouse", "alchemy"),
    ("Infura",             "greenhouse", "infura"),
    ("Moralis",            "lever",      "moralis"),
    ("Thirdweb",           "lever",      "thirdweb"),
    ("Fleek",              "lever",      "fleek"),
    ("IPFS / Protocol Labs", "greenhouse", "protocollabs"),
    ("Filecoin",           "greenhouse", "protocollabs"),
    ("Ethereum Foundation","lever",      "ethereumfoundation"),
    ("Solana Labs",        "greenhouse", "solanalabs"),
    ("Near Protocol",      "lever",      "nearprotocol"),
    ("Aptos Labs",         "greenhouse", "aptos"),
    ("Sui",                "greenhouse", "mysten"),
    ("Starkware",          "greenhouse", "starkware"),
    ("Polygon",            "greenhouse", "polygon"),
    ("Arbitrum",           "greenhouse", "arbitrum"),
    ("Optimism",           "greenhouse", "optimism"),
    ("zkSync",             "lever",      "zksync"),
    ("Base",               "greenhouse", "base"),
    ("Avalanche",          "greenhouse", "ava"),
    ("Stellar",            "greenhouse", "stellar"),
    ("Ripple",             "greenhouse", "ripple"),
    ("Phantom",            "lever",      "phantom"),
    ("MetaMask",           "greenhouse", "metamask"),
    ("Rainbow Wallet",     "lever",      "rainbow"),
    ("WalletConnect",      "lever",      "walletconnect"),
    ("Safe",               "lever",      "safe"),
    ("Gnosis Chain",       "lever",      "gnosis"),
    ("Consensys",          "greenhouse", "consensys"),
    ("Alchemy",            "greenhouse", "alchemy"),
    ("Hardhat",            "lever",      "hardhat"),
    ("Foundry",            "lever",      "foundry"),
    ("OpenZeppelin",       "lever",      "openzeppelin"),
    ("Chainalysis",        "greenhouse", "chainalysis"),
    ("Elliptic",           "greenhouse", "elliptic"),
    ("TRM Labs",           "greenhouse", "trmlabs"),
    ("Nansen",             "lever",      "nansen"),
    ("Dune Analytics",     "lever",      "dune"),
    ("Messari",            "greenhouse", "messari"),
    ("CoinGecko",          "lever",      "coingecko"),
    ("CoinMarketCap",      "greenhouse", "coinmarketcap"),
    ("The Block",          "lever",      "theblock"),
    ("Blockworks",         "lever",      "blockworks"),
    ("Decrypt",            "lever",      "decrypt"),
    ("Bankless",           "lever",      "bankless"),
    ("Milk Road",          "lever",      "milkroad"),
    ("Morning Brew",       "greenhouse", "morningbrew"),
    ("The Hustle",         "greenhouse", "thehustle"),
    ("TLDR",               "lever",      "tldr"),
    ("Beehiiv",            "greenhouse", "beehiiv"),
    ("Ghost",              "lever",      "ghost"),
    ("ConvertKit",         "greenhouse", "convertkit"),
    ("Mailchimp",          "greenhouse", "mailchimp"),
    ("ActiveCampaign",     "greenhouse", "activecampaign"),
    ("Drip",               "lever",      "drip"),
    ("Omnisend",           "lever",      "omnisend"),
    ("Sendgrid",           "greenhouse", "sendgrid"),
    ("Mailgun",            "greenhouse", "mailgun"),
    ("Postmark",           "lever",      "postmark"),
    ("Resend",             "lever",      "resend"),
    ("Loops",              "lever",      "loops"),
    ("Buttondown",         "lever",      "buttondown"),
    ("Listmonk",           "lever",      "listmonk"),
    ("Mailtrap",           "lever",      "mailtrap"),
    ("Twilio",             "greenhouse", "twilio"),
    ("Vonage",             "greenhouse", "vonage"),
    ("MessageBird",        "greenhouse", "messagebird"),
    ("Bandwidth",          "greenhouse", "bandwidth"),
    ("Telnyx",             "greenhouse", "telnyx"),
    ("Plivo",              "lever",      "plivo"),
    ("Sinch",              "greenhouse", "sinch"),
    ("Nexmo",              "greenhouse", "vonage"),
    ("LiveKit",            "lever",      "livekit"),
    ("Agora",              "greenhouse", "agora"),
    ("Daily.co",           "lever",      "daily"),
    ("100ms",              "lever",      "100ms"),
    ("Stream",             "greenhouse", "stream"),
    ("PubNub",             "greenhouse", "pubnub"),
    ("Ably",               "lever",      "ably"),
    ("Pusher",             "greenhouse", "pusher"),
    ("Socket.io",          "lever",      "socketio"),
    ("Cloudinary",         "greenhouse", "cloudinary"),
    ("imgix",              "greenhouse", "imgix"),
    ("ImageKit",           "lever",      "imagekit"),
    ("Uploadcare",         "lever",      "uploadcare"),
    ("Mux",                "greenhouse", "mux"),
    ("JW Player",          "greenhouse", "jwplayer"),
    ("Wistia",             "greenhouse", "wistia"),
    ("Vimeo",              "greenhouse", "vimeo"),
    ("Loom",               "greenhouse", "loom"),
    ("Grain",              "lever",      "grain"),
    ("Gong",               "greenhouse", "gong"),
    ("Chorus.ai",          "greenhouse", "chorus"),
    ("Clari",              "greenhouse", "clari"),
    ("Outreach",           "greenhouse", "outreach"),
    ("Salesloft",          "greenhouse", "salesloft"),
    ("Apollo",             "greenhouse", "apollo"),
    ("ZoomInfo",           "greenhouse", "zoominfo"),
    ("Clearbit",           "greenhouse", "clearbit"),
    ("Lusha",              "greenhouse", "lusha"),
    ("Hunter.io",          "lever",      "hunterio"),
    ("Phantombuster",      "lever",      "phantombuster"),
    ("Make (Integromat)",  "greenhouse", "make"),
    ("n8n",                "lever",      "n8n"),
    ("Zapier",             "greenhouse", "zapier"),
    ("IFTTT",              "greenhouse", "ifttt"),
    ("Automate.io",        "lever",      "automateio"),
    ("Workato",            "greenhouse", "workato"),
    ("Tray.io",            "greenhouse", "tray"),
    ("Boomi",              "greenhouse", "boomi"),
    ("MuleSoft",           "greenhouse", "mulesoft"),
    ("Celigo",             "greenhouse", "celigo"),
    ("Jitterbit",          "greenhouse", "jitterbit"),
    ("Informatica",        "greenhouse", "informatica"),
    ("Talend",             "greenhouse", "talend"),
    ("Stitch",             "greenhouse", "stitch"),
    ("Matillion",          "greenhouse", "matillion"),
    ("Rivery",             "lever",      "rivery"),
    ("Airbyte",            "greenhouse", "airbyte"),
    ("Fivetran",           "greenhouse", "fivetran"),
    ("Hevo",               "greenhouse", "hevo"),
    ("Singer",             "lever",      "singer"),
    ("Meltano",            "greenhouse", "meltano"),
    ("Keboola",            "lever",      "keboola"),
    ("Xplenty",            "lever",      "xplenty"),
    ("Alooma",             "lever",      "alooma"),
    ("Segment",            "greenhouse", "segment"),
    ("RudderStack",        "lever",      "rudderstack"),
    ("Snowplow",           "greenhouse", "snowplow"),
    ("Heap",               "greenhouse", "heap"),
    ("Amplitude",          "greenhouse", "amplitude"),
    ("Mixpanel",           "greenhouse", "mixpanel"),
    ("FullStory",          "greenhouse", "fullstory"),
    ("LogRocket",          "greenhouse", "logrocket"),
    ("Hotjar",             "lever",      "hotjar"),
    ("Microsoft",          "greenhouse", "microsoft"),
    ("Google",             "greenhouse", "google"),
    ("Amazon",             "greenhouse", "amazon"),
    ("Meta",               "greenhouse", "facebook"),
    ("Apple",              "greenhouse", "apple"),
    ("Netflix",            "greenhouse", "netflix"),
    ("Spotify",            "greenhouse", "spotify"),
    ("Twitter / X",        "greenhouse", "twitter"),
    ("LinkedIn",           "greenhouse", "linkedin"),
    ("Salesforce",         "greenhouse", "salesforce"),
    ("SAP",                "greenhouse", "sap"),
    ("Oracle",             "greenhouse", "oracle"),
    ("IBM",                "greenhouse", "ibm"),
    ("Cisco",              "greenhouse", "cisco"),
    ("Dell",               "greenhouse", "dell"),
    ("HP",                 "greenhouse", "hp"),
    ("Intel",              "greenhouse", "intel"),
    ("Nvidia",             "greenhouse", "nvidia"),
    ("AMD",                "greenhouse", "amd"),
    ("Qualcomm",           "greenhouse", "qualcomm"),
    ("ARM",                "greenhouse", "arm"),
    ("TSMC",               "greenhouse", "tsmc"),
    ("Palantir",           "greenhouse", "palantir"),
    ("Snowflake",          "greenhouse", "snowflake"),
    ("MongoDB",            "greenhouse", "mongodb"),
    ("Databricks",         "greenhouse", "databricks"),
    ("Confluent",          "greenhouse", "confluent"),
    ("dbt Labs",           "lever",      "dbtlabs"),
    ("Astronomer",         "greenhouse", "astronomer"),
    ("Prefect",            "greenhouse", "prefect"),
    ("Dagster",            "lever",      "dagster"),
    ("Great Expectations", "greenhouse", "superconductive"),
    ("OpenLineage",        "lever",      "openlineage"),
    ("Apache Spark",       "greenhouse", "apachespark"),
    ("Flink",              "greenhouse", "apacheflink"),
    ("Kafka",              "greenhouse", "confluent"),
    ("Pulsar",             "greenhouse", "streamnative"),
    ("RabbitMQ",           "greenhouse", "cloudamqp"),
    ("NATS",               "lever",      "nats"),
    ("Redis",              "greenhouse", "redis"),
    ("Memcached",          "greenhouse", "memcached"),
    ("ScyllaDB",           "greenhouse", "scylladb"),
    ("YugabyteDB",         "greenhouse", "yugabyte"),
    ("CockroachDB",        "greenhouse", "cockroachlabs"),
    ("PlanetScale",        "lever",      "planetscale"),
    ("Neon",               "greenhouse", "neon"),
    ("Supabase",           "greenhouse", "supabase"),
    ("TiDB",               "greenhouse", "pingcap"),
    ("DoltHub",            "lever",      "dolthub"),
    ("Motherduck",         "lever",      "motherduck"),
    ("ClickHouse",         "greenhouse", "clickhouse"),
    ("StarRocks",          "greenhouse", "starrocks"),
    ("Doris",              "greenhouse", "doris"),
    ("Druid",              "greenhouse", "druid"),
    ("Pinot",              "greenhouse", "pinot"),
    ("Trino",              "greenhouse", "trino"),
    ("Presto",             "greenhouse", "presto"),
    ("duckdb",             "lever",      "duckdblabs"),
    ("Hive",               "greenhouse", "hive"),
    ("Impala",             "greenhouse", "impala"),
    ("Kylin",              "greenhouse", "kylin"),
    ("Doris",              "greenhouse", "doris"),
]

# Deduplicate CURATED_REMOTE by name (keep first occurrence)
_seen_names = set()
CURATED_REMOTE_DEDUPED = []
for entry in CURATED_REMOTE:
    if entry[0].lower() not in _seen_names:
        _seen_names.add(entry[0].lower())
        CURATED_REMOTE_DEDUPED.append(entry)
CURATED_REMOTE = CURATED_REMOTE_DEDUPED

# ------------------------------------------------------------------ #
#  Remote GitHub Repo Parsers
# ------------------------------------------------------------------ #

def _get(url: str, timeout: int = 15):
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "VisaJobBot/1.0"})
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  GET {url} failed: {e}")
        return None


def parse_yanirs():
    """yanirs/established-remote — table-based markdown of established remote companies."""
    print("Fetching yanirs/established-remote...")
    url = "https://raw.githubusercontent.com/yanirs/established-remote/master/README.md"
    r = _get(url)
    if not r:
        return []

    companies = []
    for line in r.text.splitlines():
        # lines look like: [CompanyName](url) | industry | tech stack | ...
        m = re.match(r"^\[([^\]]+)\]\((https?://[^\)]+)\)\s*\|", line)
        if m:
            name = m.group(1).strip()
            site_url = m.group(2).strip()
            # Extract Jobs link if present
            jobs_m = re.search(r"Jobs\]\((https?://[^\)]+)\)", line)
            careers_url = jobs_m.group(1) if jobs_m else site_url
            ats, slug = classify_ats(careers_url)
            companies.append({"name": name, "careers_url": careers_url, "ats": ats, "slug": slug, "source": "yanirs"})
    print(f"  Found {len(companies)} companies in yanirs")
    return companies


def parse_adherb():
    """adherb/remote-tech-companies — table with company name, industry, region, careers link."""
    print("Fetching adherb/remote-tech-companies...")
    url = "https://raw.githubusercontent.com/adherb/remote-tech-companies/main/README.md"
    r = _get(url)
    if not r:
        return []

    companies = []
    for line in r.text.splitlines():
        if "|" not in line or "---" in line or "Company" in line:
            continue
        # Extract markdown links from cells
        links = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", line)
        if links:
            name = links[0][0].strip("*").strip()
            # Try to find a direct careers/jobs link
            careers_url = ""
            for _, link_url in links:
                if any(kw in link_url.lower() for kw in ["careers", "jobs", "greenhouse", "lever", "ashby"]):
                    careers_url = link_url
                    break
            if not careers_url and links:
                careers_url = links[0][1]  # fallback to first link
            ats, slug = classify_ats(careers_url)
            companies.append({"name": name, "careers_url": careers_url, "ats": ats, "slug": slug, "source": "adherb"})
    print(f"  Found {len(companies)} companies in adherb")
    return companies


def parse_lukasz_awesome():
    """lukasz-madon/awesome-remote-job — curated list with company links."""
    print("Fetching lukasz-madon/awesome-remote-job...")
    url = "https://raw.githubusercontent.com/lukasz-madon/awesome-remote-job/master/README.md"
    r = _get(url)
    if not r:
        return []

    companies = []
    in_companies = False
    for line in r.text.splitlines():
        if "## Companies with" in line or "## Remote-First Companies" in line:
            in_companies = True
        elif in_companies and line.startswith("## "):
            in_companies = False
        if not in_companies:
            continue
        # Matches both "- [name](url)" and "  1. [name](url)" formats
        m = re.search(r"^\s*(?:\d+\.|-|\*)\s*\[([^\]]+)\]\((https?://[^\)]+)\)", line)
        if m:
            name = m.group(1).strip()
            careers_url = m.group(2).strip()
            ats, slug = classify_ats(careers_url)
            companies.append({"name": name, "careers_url": careers_url, "ats": ats, "slug": slug, "source": "lukasz_awesome"})
    print(f"  Found {len(companies)} companies in lukasz_awesome")
    return companies


def parse_andrews1022():
    """andrews1022/remote-tech-companies — markdown table."""
    print("Fetching andrews1022/remote-tech-companies...")
    url = "https://raw.githubusercontent.com/andrews1022/remote-tech-companies/main/README.md"
    r = _get(url)
    if not r:
        return []

    companies = []
    for line in r.text.splitlines():
        if "|" not in line or "---" in line:
            continue
        links = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", line)
        if links:
            name = links[0][0].strip("*").strip()
            careers_url = links[-1][1] if len(links) > 1 else links[0][1]
            ats, slug = classify_ats(careers_url)
            companies.append({"name": name, "careers_url": careers_url, "ats": ats, "slug": slug, "source": "andrews1022"})
    print(f"  Found {len(companies)} companies in andrews1022")
    return companies


def parse_remote_repos():
    """Parse additional remote-company GitHub repos as markdown bullet/numbered lists."""
    repos = [
        # Note: only listing repos verified to be alive
        ("hugo53",  "https://raw.githubusercontent.com/hugo53/awesome-RemoteWork/master/README.md"),
    ]

    companies = []
    for source_name, url in repos:
        r = _get(url)
        if not r:
            continue
        found = 0
        for line in r.text.splitlines():
            # Table rows with |
            if "|" in line and "---" not in line:
                links = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", line)
                if links:
                    name = links[0][0].strip("*").strip()
                    careers_url = links[-1][1] if len(links) > 1 else links[0][1]
                    if name and len(name) > 1:
                        ats, slug = classify_ats(careers_url)
                        companies.append({"name": name, "careers_url": careers_url, "ats": ats, "slug": slug, "source": source_name})
                        found += 1
            # Bullet or numbered list items
            elif re.match(r"^\s*(?:\d+\.|-|\*)\s*\[", line):
                m = re.search(r"^\s*(?:\d+\.|-|\*)\s*\[([^\]]+)\]\((https?://[^\)]+)\)", line)
                if m:
                    name = m.group(1).strip()
                    careers_url = m.group(2).strip()
                    if name and len(name) > 1:
                        ats, slug = classify_ats(careers_url)
                        companies.append({"name": name, "careers_url": careers_url, "ats": ats, "slug": slug, "source": source_name})
                        found += 1
        print(f"  [{source_name}] Found {found} companies")

    return companies


# ------------------------------------------------------------------ #
#  Deduplication
# ------------------------------------------------------------------ #
def deduplicate(companies: list) -> list:
    priority = {
        "greenhouse": 6, "lever": 6, "ashby": 6,
        "smartrecruiters": 5, "personio": 5, "workable": 4,
        "workday": 2, "custom": 1, "unknown": 0,
    }
    seen = {}
    for co in companies:
        name_clean = co.get("name", "").strip()
        if not name_clean or len(name_clean) < 2:
            continue
        key = name_clean.lower()
        if key not in seen:
            seen[key] = dict(co)
        else:
            existing = seen[key]
            if priority.get(existing.get("ats"), 0) < priority.get(co.get("ats"), 0):
                seen[key] = dict(co)
            elif not existing.get("careers_url") and co.get("careers_url"):
                existing["careers_url"] = co["careers_url"]
                existing["ats"] = co.get("ats", existing["ats"])
                existing["slug"] = co.get("slug", existing["slug"])
    return list(seen.values())


# ------------------------------------------------------------------ #
#  Main Execution
# ------------------------------------------------------------------ #
def main():
    all_companies = []

    # 1. Curated list (manually verified ATS slugs — highest priority)
    print("Adding curated remote companies...")
    for name, ats, slug in CURATED_REMOTE:
        if ats == "greenhouse":
            url = f"https://boards.greenhouse.io/{slug}"
        elif ats == "lever":
            url = f"https://jobs.lever.co/{slug}"
        elif ats == "ashby":
            url = f"https://{slug}.ashbyhq.com"
        elif ats == "smartrecruiters":
            url = f"https://careers.smartrecruiters.com/{slug}"
        elif ats == "workable":
            url = f"https://apply.workable.com/{slug}"
        elif ats == "personio":
            url = f"https://{slug}.jobs.personio.de"
        else:
            url = slug if (slug and str(slug).startswith("http")) else ""
            slug = None if (slug and str(slug).startswith("http")) else slug
        
        if url:
            u_lower = url.lower()
            if any(b in u_lower for b in BLACKLISTED_DOMAINS):
                continue

        all_companies.append({
            "name": name,
            "careers_url": url,
            "ats": ats,
            "slug": slug,
            "source": "curated_remote",
        })
    print(f"  Added {len(CURATED_REMOTE)} curated remote companies")

    # 2. Fetch live remote GitHub repos
    time.sleep(0.2)
    all_companies.extend(parse_yanirs())
    time.sleep(0.2)
    all_companies.extend(parse_adherb())
    time.sleep(0.2)
    all_companies.extend(parse_lukasz_awesome())
    time.sleep(0.2)
    all_companies.extend(parse_andrews1022())
    time.sleep(0.2)
    all_companies.extend(parse_remote_repos())

    # 3. Deduplicate
    all_companies = deduplicate(all_companies)

    # 4. Classify into API-scrapable vs custom
    API_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "personio", "workable"}
    scrapable = [c for c in all_companies if c.get("ats") in API_ATS]
    custom = [
        c for c in all_companies
        if c.get("ats") not in API_ATS and c.get("careers_url")
        and not any(b in c.get("careers_url", "").lower() for b in BLACKLISTED_DOMAINS)
    ]
    scrapable_names = {c["name"].lower() for c in scrapable}
    custom = [c for c in custom if c["name"].lower() not in scrapable_names]

    print(f"\n{'='*60}")
    print(f"Total unique remote companies: {len(all_companies)}")
    print(f"API-scrapable (Greenhouse/Lever/Ashby/etc): {len(scrapable)}")
    print(f"Custom ATS (needs Playwright / direct fetch): {len(custom)}")

    ats_counts: dict[str, int] = {}
    for c in scrapable:
        ats_counts[c["ats"]] = ats_counts.get(c["ats"], 0) + 1
    print("\nAPI ATS breakdown:")
    for ats, count in sorted(ats_counts.items(), key=lambda x: -x[1]):
        print(f"  {ats}: {count}")

    output = {
        "scrapable": scrapable,
        "custom_ats": custom,
        "last_updated": time.strftime("%Y-%m-%d"),
    }
    with open("remote_companies.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved remote_companies.json ✓")


if __name__ == "__main__":
    main()
