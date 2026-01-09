import re
from urllib.parse import urljoin

import icalendar
import requests
from bs4 import BeautifulSoup


class LeagueData:
    """Holds data and scraping/parsing operations for a single league."""
    def __init__(self, league):
        self.league = league
        self.website = f"https://www.basketball-bund.net/index.jsp?Action=101&liga_id={league}"
        self.all_location_names = {}
        self.cancelled_games = {}
        self.games = []
        self.locations = {}

    def scrape_league_data(self):
        """Scrape location names and cancelled game info from the paged HTML."""
        self._for_each_html_page_in_league(self.league, self._process_html_page)

    def _for_each_html_page_in_league(self, league, page_processor):
        """Navigate through paginated HTML pages for a league and call page_processor for each page."""
        session = requests.Session()  # navigation to next page only works with session cookie
        current_url = self.website

        while current_url != None:
            print("\nReading HTML:", current_url)
            response = session.get(current_url)
            response.raise_for_status()
            html_dom = BeautifulSoup(response.text, 'html.parser')

            page_processor(html_dom)

            next_page_link = self._find_next_page_link(html_dom)
            if next_page_link != None:
                current_url = urljoin(current_url, next_page_link)
            else:
                current_url = None

    def _process_html_page(self, html_dom):
        """Process a single HTML page to extract location names and cancelled games."""
        self._find_and_map_location_names_in_html(html_dom)
        self._find_and_map_cancelled_games_in_html(html_dom)

    def _find_next_page_link(self, html_dom):
        next_page_image = html_dom.find(title="Seite vor")
        return next_page_image.find_parent().get("href")

    def _find_and_map_location_names_in_html(self, html_dom):
        elements_with_mouse_over = html_dom.findAll(onmouseover=True)
        self._find_and_map_location_names_in_elements_with_mouseover(elements_with_mouse_over)

    def _find_and_map_location_names_in_elements_with_mouseover(self, elements):
        location_description_pattern = re.compile(
            "^ShowBubble.*Bezeichnung:</td><td>(?P<location>.*?)</td>.*Kurzname:</td><td>(?P<locationshortname>.*?)</td>")
        for element in elements:
            match = location_description_pattern.match(element.get("onmouseover"))
            if match != None:
                location = self._strip_multiple_spaces_to_single_space(
                    match.group("location"))
                print("Location found:", match.group(
                    "locationshortname"), "=>", location)
                self.all_location_names[match.group("locationshortname")] = location

    def _find_and_map_cancelled_games_in_html(self, html_dom):
        """Extract cancelled games from HTML and map them by game number."""
        # Find all table rows in the sports view table
        table_rows = html_dom.findAll('tr')
        for row in table_rows:
            # Check if this row contains a cancelled game indicator
            cancelled_img = row.find('img', {'title': 'Spiel abgesagt'})
            if cancelled_img:
                # Extract the game number from the first cell
                cells = row.findAll('td')
                if len(cells) > 0:
                    game_number_text = cells[0].get_text(strip=True)
                    if game_number_text:
                        self.cancelled_games[game_number_text] = True
                        print("Cancelled game found: Nr.", game_number_text)

    def parse_calendar(self, team, teamname, teamshortname):
        """Parse the DBB Spielplan calendar export."""
        all_games = -1  # -2 would skip past games
        games_ical_url = f"https://www.basketball-bund.net/servlet/KalenderDienst?typ=2&liga_id={self.league}&ms_liga_id={team}&spt={all_games}"
        print("\nReading iCal:", games_ical_url)
        response = requests.get(games_ical_url)
        response.raise_for_status()
        cal = icalendar.Calendar.from_ical(response.text)
        for component in cal.walk():
            if component.name == "VEVENT":
                self._parse_calendar_event(component, teamname, teamshortname)
        

    def _parse_calendar_event(self, event, teamname, teamshortname):
        # format: "event, location_shortname (SpNr. xx)"
        match = re.match(r'^(?P<event>.+?),\s+(?P<location_shortname>\S+)\s+\(SpNr\.\s*(?P<game_number>\d+)\)$', event.get("summary"))
        if not match:
            print("Skipping event with unrecognized format:", event.get("summary"))
        
        event_title = self._shorten_team_name(
            match.group('event'), teamname, teamshortname).replace("-", " - ").replace("Lahn - Dill", "Lahn-Dill")
        location_shortname = match.group('location_shortname')
        game_number = match.group('game_number')
        location_name = self.all_location_names.get(location_shortname)
        location_address = event.get("location")

        self.games.append({
            "title": event_title,
            "start": event.decoded("dtstart"),
            "end": event.decoded("dtend"),
            "venue": location_name,
            "cancelled": self.cancelled_games.get(game_number, False),
        })
        self.locations[location_name] = location_address

        status_str = "(CANCELLED)" if self.cancelled_games.get(game_number, False) else ""
        print("Event found:", event_title, "@",
              (location_name + " (" + location_address + ")" if location_name is not None else "Unknown"), status_str)

    def _strip_multiple_spaces_to_single_space(self, str):
        return " ".join(str.split())

    def _shorten_team_name(self, event_title, teamname, team_shortname):
        return event_title.replace(teamname, team_shortname)
