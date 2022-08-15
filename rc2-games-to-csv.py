from bs4 import BeautifulSoup
import csv
import icalendar
import re
import requests
import sys
from urllib.parse import urlparse, urljoin

events = []
location_names = {}
locations = {}

session = requests.Session() # navigation only works with session cookie
html_url = "https://www.basketball-bund.net/index.jsp?Action=101&liga_id=36203"
location_description_pattern = re.compile("^ShowBubble.*Bezeichnung:</td><td>(?P<location>.*?)</td>.*Kurzname:</td><td>(?P<locationshortname>.*?)</td>")
while html_url != None:
    print("\nReading HTML:", html_url)
    html_doc = session.get(html_url).text
    soup = BeautifulSoup(html_doc, 'html.parser')

    elements_with_mouse_over = soup.findAll(onmouseover=True)
    for element in elements_with_mouse_over:
        match = location_description_pattern.match(element.get("onmouseover"))
        if match != None:
            location = " ".join(match.group("location").split()) # remove duplicate spaces
            print("Location found:", match.group("locationshortname"), "=>", location)
            location_names[match.group("locationshortname")] = location
    
    next_page_image = soup.find(title="Seite vor")
    next_page_link = next_page_image.find_parent().get("href")
    if next_page_link != None:
        html_url = urljoin(html_url, next_page_link)
    else:
        html_url = None

ical_url = "https://www.basketball-bund.net/servlet/KalenderDienst?typ=2&liga_id=36203&ms_liga_id=322147&spt=-2"
print("\nReading iCal:", ical_url)
cal = icalendar.Calendar.from_ical(requests.get(ical_url).text)

for component in cal.walk():
    if component.name == "VEVENT":
        event_location = component.get("summary").rsplit(",", 1)
        
        location_name = location_names[event_location[1].strip()]
        location_address = component.get("location")
        locations[location_name] = location_address

        events.append({
            "event": event_location[0].replace("SGK Rolling Chocolate 2", "RC2").replace("-", " - "),
            "start": component.decoded("dtstart"),
            "end": component.decoded("dtend"),
            "location": location_name,
            "category": "rc2"
            }
        )

        print("Event found:", event_location[0], "@", location_name + " (" + location_address + ")")

with open('locations.csv', 'w') as csvfile:
    csvwriter = csv.writer(csvfile)
    csvwriter.writerow(["location", "address"])
    for location, address in locations.items():
        csvwriter.writerow([location, address])

with open('events.csv', 'w') as csvfile:
    csvwriter = csv.DictWriter(csvfile, ["event", "start", "end", "location", "category"])
    csvwriter.writeheader()
    for event in events:
        csvwriter.writerow(event)