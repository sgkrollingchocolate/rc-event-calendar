import base64
import html
import json
import re
from argparse import ArgumentParser
from urllib.parse import urljoin

import icalendar
import requests
from bs4 import BeautifulSoup

# game data
games_base_url = "https://www.basketball-bund.net"
league = "36203"  # RBB Oberliga Süd
team = "322147"  # SGK Rolling Chocolate 2
all_games = -1  # -2 would skip past games
games_html_url = f"{games_base_url}/index.jsp?Action=101&liga_id={league}"
games_ical_url = f"{games_base_url}/servlet/KalenderDienst?typ=2&liga_id={league}&ms_liga_id={team}&spt={all_games}"

# wordpress
wp_events_api = "https://relaunch.rolling-chocolate.de/wp-json/tribe/events/v1/"
wp_auth = None
event_categories = ["rc2", "spieltag", "runde-22-23"]


def shorten_rc_team_name(str):
    return str.replace("SGK Rolling Chocolate 2", "RC2")


# global data
all_location_names = {}
games = []
locations = {}
venues = {}


def main():
    args = parse_arguments()
    init_wp_auth(args.wp_user.strip(), args.wp_pass.strip())
    map_all_location_names()
    parse_calendar()
    create_or_update_venues()
    create_or_update_events()


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


# DBB Spielplan calendar export doesn't contain location name (e.g. Halle 1 Sportzentrum Süd), only a shortname (e.g. RBB-SZS)
# in the event summary. This funtion scraps the mapping from location shortname to name from the paged HTML.
def map_all_location_names():
    session = requests.Session()  # navigation to next page only works with session cookie
    current_url = games_html_url
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
def parse_calendar():
    print("\nReading iCal:", games_ical_url)
    response = requests.get(games_ical_url)
    response.raise_for_status()
    cal = icalendar.Calendar.from_ical(response.text)
    for component in cal.walk():
        if component.name == "VEVENT":
            parse_calendar_event(component)


def parse_calendar_event(event):
    event_and_locationshortname = event.get("summary").rsplit(
        ",", 1)  # format: "event, location_shortname"
    event_title = shorten_rc_team_name(
        event_and_locationshortname[0]).replace("-", " - ")
    location_name = all_location_names[event_and_locationshortname[1].strip()]
    location_address = event.get("location")

    games.append({
        "title": event_title,
        "start": event.decoded("dtstart"),
        "end": event.decoded("dtend"),
        "venue": location_name,
    })
    locations[location_name] = location_address

    print("Event found:", event_title, "@",
          location_name + " (" + location_address + ")")


def create_or_update_venues():
    print("\nCreating or updating venues")
    for location, address in locations.items():
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


def create_or_update_events():
    print("\nCreating or updating events")

    existing_events = get_existing_events()
    for game in games:
        if game["title"] in existing_events:
            update_event(game, existing_events[game["title"]])
        else:
            create_event(game)


def get_existing_events():
    headers = {
        'Authorization': wp_auth
    }

    response = requests.request("GET", urljoin(
        wp_events_api, "events?per_page=9999999"), headers=headers)
    response.raise_for_status()

    events = response.json()["events"]

    existing_events = {}
    for event in events:
        normalized_title = html.unescape(event["title"]).replace(
            "–", "-")  # wordpress changes to a slightly different hyphen
        existing_events[normalized_title] = event["id"]
        print("Existing event found:", normalized_title, "=>", event["id"])

    return existing_events


def update_event(game, event_id):
    print(f"Updating event: {game['title']} ({event_id})")

    payload, headers = get_event_payload_and_headers(game)

    response = requests.request("POST", urljoin(
        wp_events_api, "events/" + str(event_id)), headers=headers, data=payload)
    response.raise_for_status()


def create_event(game):
    print("Creating event:", game["title"])

    payload, headers = get_event_payload_and_headers(game)

    response = requests.request("POST", urljoin(
        wp_events_api, "events"), headers=headers, data=payload)
    response.raise_for_status()


def get_event_payload_and_headers(game):
    payload = json.dumps({
        "title": game["title"],
        "start_date": game["start"].strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": game["end"].strftime("%Y-%m-%d %H:%M:%S"),
        "venue": venues[game["venue"]],
        "categories": event_categories,
        "show_map": True,
        "website": games_html_url
    })
    headers = {
        'Authorization': wp_auth,
        'Content-Type': 'application/json'
    }

    return payload, headers


main()
