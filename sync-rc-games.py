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

# Enabled with --dry-run argument to only simulate, e.g. don't write changes for testing
dry_run = False

# wordpress
wp_events_api = "https://www.rolling-chocolate.de/wp-json/tribe/events/v1/"
wp_auth = None


# global data
all_location_names = {}
games = []
locations = {}
venues = {}


def main():
    parse_arguments_and_init_wp_auth()

    sync_team_games(
        league_id="48078",
        team_id="401699",
        team_name="SGK Rolling Chocolate",
        team_shortname="RC1",
        event_categories=["rc1", "spieltag", "runde-25-26"]
    )
    
    sync_team_games(
        league_id="48083",
        team_id="401735",
        team_name="SGK Rolling Chocolate 2",
        team_shortname="RC2",
        event_categories=["rc2", "spieltag", "runde-25-26"]
    )


def parse_arguments_and_init_wp_auth():
    args = parse_arguments()
    init_wp_auth(args.wp_user.strip(), args.wp_pass.strip())
    init_dry_run_flag(args.dry_run)


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


def init_dry_run_flag(dry_run_arg):
    global dry_run
    dry_run = dry_run_arg


def sync_team_games(*, league_id, team_id, team_name, team_shortname, event_categories):
    clear_global_state()
    map_all_location_names(league_id)
    parse_calendar(league_id, team_id, team_name, team_shortname)
    if not dry_run:
        create_or_update_venues()
        delete_events(league_id)
        create_events(league_id, event_categories)
    else:
        print("[DRY-RUN] Would create venues and events for league: %s", league_id)


def clear_global_state():
    all_location_names.clear()
    games.clear()
    locations.clear()
    venues.clear()


# DBB Spielplan calendar export doesn't contain location name (e.g. Halle 1 Sportzentrum Süd), only a shortname (e.g. RBB-SZS)
# in the event summary. This funtion scraps the mapping from location shortname to name from the paged HTML.
def map_all_location_names(league):
    session = requests.Session()  # navigation to next page only works with session cookie
    current_url = f"https://www.basketball-bund.net/index.jsp?Action=101&liga_id={league}"

    while current_url != None:
        print("\nReading HTML:", current_url)
        response = session.get(current_url)
        response.raise_for_status()
        html_dom = BeautifulSoup(response.text, 'html.parser')

        find_and_map_location_names_in_html(html_dom)

        next_page_link = find_next_page_link(html_dom)
        if next_page_link != None:
            current_url = urljoin(current_url, next_page_link)
        else:
            current_url = None


def find_next_page_link(html_dom):
    next_page_image = html_dom.find(title="Seite vor")
    return next_page_image.find_parent().get("href")


def find_and_map_location_names_in_html(html_dom):
    elements_with_mouse_over = html_dom.findAll(onmouseover=True)
    find_and_map_location_names_in_elements_with_mouseover(
        elements_with_mouse_over)


def find_and_map_location_names_in_elements_with_mouseover(elements):
    location_description_pattern = re.compile(
        "^ShowBubble.*Bezeichnung:</td><td>(?P<location>.*?)</td>.*Kurzname:</td><td>(?P<locationshortname>.*?)</td>")
    for element in elements:
        match = location_description_pattern.match(element.get("onmouseover"))
        if match != None:
            location = strip_multiple_spaces_to_single_space(
                match.group("location"))
            print("Location found:", match.group(
                "locationshortname"), "=>", location)
            all_location_names[match.group("locationshortname")] = location


def strip_multiple_spaces_to_single_space(str):
    return " ".join(str.split())


# Parse the DBB Spielplan calendar export
def parse_calendar(league, team, teamname, teamshortname):
    all_games = -1  # -2 would skip past games
    games_ical_url = f"https://www.basketball-bund.net/servlet/KalenderDienst?typ=2&liga_id={league}&ms_liga_id={team}&spt={all_games}"
    print("\nReading iCal:", games_ical_url)
    response = requests.get(games_ical_url)
    response.raise_for_status()
    cal = icalendar.Calendar.from_ical(response.text)
    for component in cal.walk():
        if component.name == "VEVENT":
            parse_calendar_event(component, teamname, teamshortname)


def parse_calendar_event(event, teamname, teamshortname):
    # format: "event, location_shortname (SpNr. xx)"
    match = re.match(r'^(?P<event>.+),\s+(?P<location_shortname>\S+)', event.get("summary"))
    if not match:
        print("Skipping event with unrecognized format:", event.get("summary"))
    
    event_title = shorten_team_name(
        match.group('event'), teamname, teamshortname).replace("-", " - ").replace("Lahn - Dill", "Lahn-Dill")
    location_shortname = match.group('location_shortname')
    location_name = all_location_names.get(location_shortname)
    location_address = event.get("location")

    games.append({
        "title": event_title,
        "start": event.decoded("dtstart"),
        "end": event.decoded("dtend"),
        "venue": location_name,
    })
    locations[location_name] = location_address

    print("Event found:", event_title, "@",
          (location_name + " (" + location_address + ")" if location_name is not None else "Unknown"))


def shorten_team_name(event_title, teamname, team_shortname):
    return event_title.replace(teamname, team_shortname)


def create_or_update_venues():
    print("\nCreating or updating venues")
    for location, address in locations.items():
        if location is not None:
            create_or_update_venue(location, address)


def create_or_update_venue(location, address):
    print("Creating or updating venue:", location)

    payload = json.dumps({
        "venue": location,
        "address": address
    })
    headers = {
        'Authorization': wp_auth,
        'Content-Type': 'application/json'
    }

    # venue is implicitly updated if it already exists
    response = requests.request("POST", urljoin(
        wp_events_api, "venues"), headers=headers, data=payload)
    response.raise_for_status()

    # save venues so that they can be referenced by event
    venue_id = response.json()["id"]
    venues[location] = venue_id


def delete_events(league):
    print("\nDeleting events")

    events = get_events_for_league(league)
    for event in events:
        delete_event(event)


def get_events_for_league(league):
    events = get_events()
    return [event for event in events if html.unescape(event["website"]) == get_website_for_league(league)]


def get_events():
    events = []
    
    page = 1
    while True:
        response = get_events_per_page(page)
        events.extend(response.json()["events"])
        if not response.json().get("next_rest_url"):
            break
        else:
            # not using next_rest_url directly because it produces a 400 error
            page += 1

    return events


def get_events_per_page(page):
    headers = {
        'Authorization': wp_auth
    }

    response = requests.request("GET", urljoin(
        wp_events_api, "events?per_page=50&starts_after=1900-01-01&page=" + str(page)), headers=headers)
    response.raise_for_status()

    return response


def delete_event(event):
    print(f"Deleting event: {html.unescape(event['title'])} ({event['id']})")

    headers = {
        'Authorization': wp_auth
    }

    response = requests.request("DELETE", urljoin(
        wp_events_api, "events/" + str(event["id"])), headers=headers)
    response.raise_for_status()


def create_events(league, event_categories):
    print("\nCreating events")

    for game in games:
        create_event(game, league, event_categories)


def create_event(game, league, event_categories):
    print("Creating event:", game["title"])

    payload, headers = get_create_event_payload_and_headers(
        game, league, event_categories)

    response = requests.request("POST", urljoin(
        wp_events_api, "events"), headers=headers, data=payload)
    response.raise_for_status()


def get_create_event_payload_and_headers(game, league, event_categories):
    payload = json.dumps({
        "title": game["title"],
        "start_date": game["start"].strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": game["end"].strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "UTC",  # times are given in UTC
        "venue": venues.get(game["venue"]),
        "categories": event_categories,
        "show_map": True,
        "website": get_website_for_league(league)
    })
    headers = {
        'Authorization': wp_auth,
        'Content-Type': 'application/json'
    }

    return payload, headers

def get_website_for_league(league):
    return f"https://www.basketball-bund.net/index.jsp?Action=101&liga_id={league}"

main()
