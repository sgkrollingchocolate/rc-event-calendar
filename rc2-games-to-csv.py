import csv
import re
from urllib.parse import urljoin

import icalendar
import requests
from bs4 import BeautifulSoup

all_location_names = {}
events = []
locations = {}

"""
DBB Spielplan calendar export doesn't contain location name (e.g. Halle 1 Sportzentrum Süd), only a shortname (e.g. RBB-SZS)
in the event summary. This funtion scraps the mapping from location shortname to name from the paged HTML.
"""
def map_all_location_names():
    session = requests.Session()  # navigation only works with session cookie
    html_url = "https://www.basketball-bund.net/index.jsp?Action=101&liga_id=36203"
    location_description_pattern = re.compile(
        "^ShowBubble.*Bezeichnung:</td><td>(?P<location>.*?)</td>.*Kurzname:</td><td>(?P<locationshortname>.*?)</td>")
    while html_url != None:
        print("\nReading HTML:", html_url)
        html_doc = session.get(html_url).text
        soup = BeautifulSoup(html_doc, 'html.parser')

        elements_with_mouse_over = soup.findAll(onmouseover=True)
        for element in elements_with_mouse_over:
            match = location_description_pattern.match(
                element.get("onmouseover"))
            if match != None:
                # remove duplicate spaces
                location = " ".join(match.group("location").split())
                print("Location found:", match.group(
                    "locationshortname"), "=>", location)
                all_location_names[match.group("locationshortname")] = location

        next_page_image = soup.find(title="Seite vor")
        next_page_link = next_page_image.find_parent().get("href")
        if next_page_link != None:
            html_url = urljoin(html_url, next_page_link)
        else:
            html_url = None

"""
Parse the DBB Spielplan calendar export, filtered to RC2 team.
"""
def parse_calendar():
    ical_url = "https://www.basketball-bund.net/servlet/KalenderDienst?typ=2&liga_id=36203&ms_liga_id=322147&spt=-2"
    print("\nReading iCal:", ical_url)
    cal = icalendar.Calendar.from_ical(requests.get(ical_url).text)
    for component in cal.walk():
        if component.name == "VEVENT":
            event_and_locationshortname = component.get("summary").rsplit(
                ",", 1)  # format: "event, location_shortname"
            event_name = event_and_locationshortname[0].replace(
                "SGK Rolling Chocolate 2", "RC2").replace("-", " - ")
            location_name = all_location_names[event_and_locationshortname[1].strip(
            )]
            location_address = component.get("location")

            events.append({
                "event": event_name,
                "start": component.decoded("dtstart"),
                "end": component.decoded("dtend"),
                "location": location_name,
                "category": "rc2"
            }
            )
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
