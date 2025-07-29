import sys
import logging

# importing external dependencies with error reporting
try:
    import base64
    import html
    import json
    import re
    from argparse import ArgumentParser
    from datetime import datetime
    from urllib.parse import urljoin

    import icalendar
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Missing required module: {e.name}. Install with pip.", file=sys.stderr)
    sys.exit(1)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# WordPress event API configuration
wp_events_api = "https://www.rolling-chocolate.de/wp-json/tribe/events/v1/"
wp_auth = None

# Global data containers
all_location_names = {}
games = []
locations = {}
venues = {}

def clear_global_state():
    all_location_names.clear()
    games.clear()
    locations.clear()
    venues.clear()

def main():
    args = parse_arguments()
    init_wp_auth(args.wp_user.strip(), args.wp_pass.strip())

    rc_teams = [
        {
            "league_id": "43699",
            "team_id": "378599",
            "team_name": "SGK Rolling Chocolate",
            "shortname": "RC1",
            "categories": ["rc1", "spieltag", "runde-24-25"]
        },
        {
            "league_id": "45183",
            "team_id": "376784",
            "team_name": "SGK Rolling Chocolate 2",
            "shortname": "RC2",
            "categories": ["rc2", "spieltag", "runde-24-25"]
        }
    ]

    for team in rc_teams:
        try:
            sync_team_games(
                league_id=team["league_id"],
                team_id=team["team_id"],
                team_name=team["team_name"],
                team_shortname=team["shortname"],
                event_categories=team["categories"],
                dry_run=args.dry_run
            )
        except Exception as e:
            logger.exception(f"Failed to sync team {team['shortname']}: {e}")

def parse_arguments():
    parser = ArgumentParser()
    parser.add_argument("-u", "--wp-user", dest="wp_user", help="WordPress username", required=True)
    parser.add_argument("-p", "--wp-password", dest="wp_pass", help="WordPress password", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Only simulate, don't write changes")
    return parser.parse_args()

def init_wp_auth(wp_user, wp_pass):
    global wp_auth
    credentials = f"{wp_user}:{wp_pass}".encode("utf-8")
    wp_auth = "Basic " + base64.b64encode(credentials).decode("utf-8")

def sync_team_games(league_id, team_id, team_name, team_shortname, event_categories, dry_run=False):
    clear_global_state()
    map_all_location_names(league_id)
    parse_calendar(league_id, team_id, team_name, team_shortname)
    if not dry_run:
        create_or_update_venues()
        delete_events(league_id)
        create_events(league_id, event_categories)
    else:
        logger.info("[DRY-RUN] Would create venues and events for league: %s", league_id)

def map_all_location_names(league):
    session = requests.Session()
    current_url = f"https://www.basketball-bund.net/index.jsp?Action=101&liga_id={league}"

    while current_url:
        logger.info("Reading HTML: %s", current_url)
        response = session.get(current_url)
        response.raise_for_status()
        html_dom = BeautifulSoup(response.text, 'html.parser')

        elements = html_dom.findAll(onmouseover=True)
        for el in elements:
            match = re.match(
                r"^ShowBubble.*Bezeichnung:</td><td>(.*?)</td>.*Kurzname:</td><td>(.*?)</td>",
                el.get("onmouseover", "")
            )
            if match:
                name, shortname = match.groups()
                name = " ".join(name.split())
                logger.debug("Mapped %s => %s", shortname, name)
                all_location_names[shortname] = name

        next_link = html_dom.find(title="Seite vor")
        current_url = urljoin(current_url, next_link.find_parent()["href"]) if next_link else None

def parse_calendar(league, team, teamname, teamshortname):
    url = f"https://www.basketball-bund.net/servlet/KalenderDienst?typ=2&liga_id={league}&ms_liga_id={team}&spt=-1"
    logger.info("Reading iCal: %s", url)
    response = requests.get(url)
    response.raise_for_status()
    cal = icalendar.Calendar.from_ical(response.text)

    for component in cal.walk():
        if component.name == "VEVENT":
            summary = component.get("summary")
            if not summary:
                continue
            parts = summary.rsplit(",", 1)
            title = shorten_team_name(parts[0], teamname, teamshortname)
            location_key = parts[1].strip() if len(parts) > 1 else None
            venue_name = all_location_names.get(location_key)
            venue_addr = component.get("location")

            games.append({
                "title": title,
                "start": component.decoded("dtstart"),
                "end": component.decoded("dtend"),
                "venue": venue_name
            })
            if venue_name:
                locations[venue_name] = venue_addr
            logger.debug("Parsed event: %s @ %s", title, venue_name)

def shorten_team_name(title, teamname, shortname):
    return title.replace(teamname, shortname).replace("-", " - ").replace("Lahn - Dill", "Lahn-Dill")

def create_or_update_venues():
    logger.info("Creating or updating venues")
    for location, address in locations.items():
        if location:
            create_or_update_venue(location, address)

def create_or_update_venue(location, address):
    logger.info("Creating or updating venue: %s", location)
    payload = json.dumps({"venue": location, "address": address})
    headers = {"Authorization": wp_auth, "Content-Type": "application/json"}
    response = requests.post(urljoin(wp_events_api, "venues"), headers=headers, data=payload)
    response.raise_for_status()
    venue_id = response.json().get("id")
    venues[location] = venue_id

def delete_events(league):
    logger.info("Deleting events")
    for event in get_events_for_league(league):
        delete_event(event)

def get_events_for_league(league):
    return [event for event in get_events() if html.unescape(event.get("website", "")) == get_website_for_league(league)]

def get_events():
    events = []
    page = 1
    while True:
        headers = {"Authorization": wp_auth}
        url = f"{wp_events_api}events?per_page=50&starts_after=1900-01-01&page={page}"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        page_data = response.json()
        events.extend(page_data.get("events", []))
        if not page_data.get("next_rest_url"):
            break
        page += 1
    return events

def delete_event(event):
    logger.info("Deleting event: %s (%s)", html.unescape(event.get("title", "")), event.get("id"))
    headers = {"Authorization": wp_auth}
    response = requests.delete(urljoin(wp_events_api, f"events/{event['id']}"), headers=headers)
    response.raise_for_status()

def create_events(league, categories):
    logger.info("Creating events")
    for game in games:
        create_event(game, league, categories)

def create_event(game, league, categories):
    logger.info("Creating event: %s", game["title"])
    payload = json.dumps({
        "title": game["title"],
        "start_date": game["start"].strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": game["end"].strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "UTC",
        "venue": venues.get(game["venue"]),
        "categories": categories,
        "show_map": True,
        "website": get_website_for_league(league)
    })
    headers = {"Authorization": wp_auth, "Content-Type": "application/json"}
    response = requests.post(urljoin(wp_events_api, "events"), headers=headers, data=payload)
    response.raise_for_status()

def get_website_for_league(league):
    return f"https://www.basketball-bund.net/index.jsp?Action=101&liga_id={league}"

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception("Unhandled error in main execution")
        sys.exit(1)
