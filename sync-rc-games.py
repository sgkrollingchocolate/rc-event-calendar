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

# wordpress
wp_events_api = "https://www.rolling-chocolate.de/wp-json/tribe/events/v1/"
wp_auth = None


# global data
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
    parse_arguments_and_init_wp_auth()

    rc1_league_id = "43699"
    rc1_team_id = "378599"
    rc1_team_name = "SGK Rolling Chocolate"
    rc1_team_shortname = "RC1"
    rc1_event_categories = ["rc1", "spieltag", "runde-24-25"]
    sync_team_games(rc1_league_id, rc1_team_id, rc1_team_name,
                    rc1_team_shortname, rc1_event_categories)

    #rc1pokal_league_id = "47050"
    #rc1pokal_team_id = "392047"
    #rc1pokal_team_name = "SGK Rolling Chocolate"
    #rc1pokal_team_shortname = "RC1"
    #rc1pokal_event_categories = ["rc1", "spieltag", "runde-24-25"]
    #sync_team_games(rc1pokal_league_id, rc1pokal_team_id, rc1pokal_team_name,
    #                rc1pokal_team_shortname, rc1pokal_event_categories)


    rc2_league_id = "45183"
    rc2_team_id = "376784"
    rc2_team_name = "SGK Rolling Chocolate 2"
    rc2_team_shortname = "RC2"
    rc2_event_categories = ["rc2", "spieltag", "runde-24-25"]
    sync_team_games(rc2_league_id, rc2_team_id, rc2_team_name,
                    rc2_team_shortname, rc2_event_categories)


def parse_arguments_and_init_wp_auth():
    args = parse_arguments()
    init_wp_auth(args.wp_user.strip(), args.wp_pass.strip())


def parse_arguments():
    parser = ArgumentParser()
    parser.add_argument("-u", "--wp-user", dest="wp_user",
                        help="WordPress user", required=True)
    parser.add_argument("-p", "--wp-password", dest="wp_pass",
                        help="WordPress password", required=True)
    return parser.parse_args()


def init_wp_auth(wp_user, wp_pass):
    global wp_auth
    wp_auth = "Basic " + \
        base64.b64encode(
            bytes(wp_user + ":" + wp_pass, "utf-8")).decode("utf-8")


def sync_team_games(league_id, team_id, team_name, team_shortname, event_categories):
    clear_global_state()
    map_all_location_names(league_id)
    parse_calendar(league_id, team_id, team_name, team_shortname)
    create_or_update_venues()
    create_or_update_events(league_id, event_categories)


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
    event_and_locationshortname = event.get("summary").rsplit(
        ",", 1)  # format: "event, location_shortname"
    event_title = shorten_team_name(
        event_and_locationshortname[0], teamname, teamshortname).replace("-", " - ").replace("Lahn - Dill", "Lahn-Dill")
    location_name = all_location_names.get(event_and_locationshortname[1].strip())
    location_address = event.get("location")

    games.append({
        "title": event_title,
        "start": event.decoded("dtstart"),
        "end": event.decoded("dtend"),
        "venue": location_name,
    })
    locations[location_name] = location_address

    print("Event found:", event_title, "@",
          (location_name + " (" + location_address + ")" if location_name is not None else "Unbekannt"))


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


def create_or_update_events(league, event_categories):
    print("\nCreating or updating events")

    existing_events = get_existing_events()
    for game in games:
        if game["title"] in existing_events:
            update_event(
                game, existing_events[game["title"]], league, event_categories)
        else:
            create_event(game, league, event_categories)


def get_existing_events():
    events = request_events()
    existing_events = {}
    for event in events:
        normalized_title = html.unescape(event["title"]).replace(
            "–", "-")  # wordpress changes to a slightly different hyphen
        existing_events[normalized_title] = event["id"]
        print("Existing event found:", normalized_title, "=>", event["id"])

    return existing_events

def request_events():
    events = []
    
    page = 1
    while True:
        response = request_events_per_page(page)
        events.extend(response.json()["events"])
        if not response.json().get("next_rest_url"):
            break
        else:
            # not using next_rest_url directly because it produces a 400 error
            page += 1

    return events


def request_events_per_page(page):
    headers = {
        'Authorization': wp_auth
    }

    response = requests.request("GET", urljoin(
        wp_events_api, "events?per_page=50&starts_after=1900-01-01&page=" + str(page)), headers=headers)
    response.raise_for_status()

    return response


def update_event(game, event_id, league, event_categories):
    print(f"Updating event: {game['title']} ({event_id})")

    payload, headers = create_event_payload_and_headers(
        game, league, event_categories)

    response = requests.request("POST", urljoin(
        wp_events_api, "events/" + str(event_id)), headers=headers, data=payload)
    response.raise_for_status()


def create_event(game, league, event_categories):
    print("Creating event:", game["title"])

    payload, headers = create_event_payload_and_headers(
        game, league, event_categories)

    response = requests.request("POST", urljoin(
        wp_events_api, "events"), headers=headers, data=payload)
    response.raise_for_status()


def create_event_payload_and_headers(game, league, event_categories):
    payload = json.dumps({
        "title": game["title"],
        "start_date": game["start"].strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": game["end"].strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "UTC",  # times are given in UTC
        "venue": venues.get(game["venue"]),
        "categories": event_categories,
        "show_map": True,
        "website": getWebsiteForLeague(league)
    })
    headers = {
        'Authorization': wp_auth,
        'Content-Type': 'application/json'
    }

    return payload, headers

def getWebsiteForLeague(league):
    return f"https://www.basketball-bund.net/index.jsp?Action=101&liga_id={league}"


main()
