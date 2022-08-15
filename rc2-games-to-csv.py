import csv
import re
from urllib.parse import urljoin

import icalendar
import requests
from bs4 import BeautifulSoup

base_url = "https://www.basketball-bund.net"
league = "36203" # RBB Oberliga Süd
team = "322147" # SGK Rolling Chocolate 2
all_games = -1 # -2 would skip past games
html_url = f"{base_url}/index.jsp?Action=101&liga_id={league}"
ical_url = f"{base_url}/servlet/KalenderDienst?typ=2&liga_id={league}&ms_liga_id={team}&spt={all_games}"
category = "rc2"

def shorten_rc_team_name(str):
    return str.replace("SGK Rolling Chocolate 2", "RC2")

all_location_names = {}
events = []
locations = {}

"""
DBB Spielplan calendar export doesn't contain location name (e.g. Halle 1 Sportzentrum Süd), only a shortname (e.g. RBB-SZS)
in the event summary. This funtion scraps the mapping from location shortname to name from the paged HTML.
"""
def map_all_location_names():
    session = requests.Session()  # navigation to next page only works with session cookie
    current_url = html_url
    while current_url != None:
        print("\nReading HTML:", current_url)
        html_doc = session.get(current_url).text
        html_dom = BeautifulSoup(html_doc, 'html.parser')

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
    find_and_map_location_names_in_elements_with_mouseover(elements_with_mouse_over)

def find_and_map_location_names_in_elements_with_mouseover(elements):
    location_description_pattern = re.compile(
        "^ShowBubble.*Bezeichnung:</td><td>(?P<location>.*?)</td>.*Kurzname:</td><td>(?P<locationshortname>.*?)</td>")
    for element in elements:
        match = location_description_pattern.match(element.get("onmouseover"))
        if match != None:
            location = strip_multiple_spaces_to_single_space(match.group("location"))
            print("Location found:", match.group(
                "locationshortname"), "=>", location)
            all_location_names[match.group("locationshortname")] = location

def strip_multiple_spaces_to_single_space(str):
    return " ".join(str.split())

"""
Parse the DBB Spielplan calendar export
"""
def parse_calendar():
    print("\nReading iCal:", ical_url)
    cal = icalendar.Calendar.from_ical(requests.get(ical_url).text)
    for component in cal.walk():
        if component.name == "VEVENT":
            parse_calendar_event(component)

def parse_calendar_event(event):
    event_and_locationshortname = event.get("summary").rsplit(",", 1)  # format: "event, location_shortname"
    event_name = shorten_rc_team_name(event_and_locationshortname[0]).replace("-", " - ")
    location_name = all_location_names[event_and_locationshortname[1].strip()]
    location_address = event.get("location")

    events.append({
        "event": event_name,
        "start": event.decoded("dtstart"),
        "end": event.decoded("dtend"),
        "location": location_name,
        "category": category
    })
    locations[location_name] = location_address

    print("Event found:", event_and_locationshortname[0], "@",
            location_name + " (" + location_address + ")")

def create_locations_csv():
    with open('locations.csv', 'w') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(["location", "address"])
        for location, address in locations.items():
            csvwriter.writerow([location, address])

def create_events_csv():
    with open('events.csv', 'w') as csvfile:
        csvwriter = csv.DictWriter(
            csvfile, ["event", "start", "end", "location", "category"])
        csvwriter.writeheader()
        for event in events:
            csvwriter.writerow(event)

map_all_location_names()
parse_calendar()
create_locations_csv()
create_events_csv()
