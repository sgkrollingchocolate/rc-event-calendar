import base64
import html
import json
from urllib.parse import urljoin

import requests


class WordPressEventManager:
    """Manages WordPress event and venue operations."""
    
    def __init__(self, wp_base_url, username, password, league_website):
        # Build the events API URL from the provided base URL
        self.wp_events_api = urljoin(wp_base_url, "wp-json/tribe/events/v1/")
        self.league_website = league_website
        self.venues = {}
        self.wp_auth = self.create_auth_token(username, password)
    
    def create_auth_token(self, username, password):
        """Create WordPress Basic Auth token from username and password."""
        credentials = f"{username}:{password}".encode("utf-8")
        return "Basic " + base64.b64encode(credentials).decode("utf-8")

    def create_or_update_venues(self, locations):
        """Create or update venues in WordPress."""
        print("\nCreating or updating venues")
        for location, address in locations.items():
            if location is not None:
                self._create_or_update_venue(location, address)

    def _create_or_update_venue(self, location, address):
        print("Creating or updating venue:", location)

        payload = json.dumps({
            "venue": location,
            "address": address
        })
        headers = {
            'Authorization': self.wp_auth,
            'Content-Type': 'application/json'
        }

        # venue is implicitly updated if it already exists
        response = requests.request("POST", urljoin(
            self.wp_events_api, "venues"), headers=headers, data=payload)
        response.raise_for_status()

        # save venues so that they can be referenced by event
        venue_id = response.json()["id"]
        self.venues[location] = venue_id

    def create_events(self, games, event_categories):
        """Create events in WordPress."""
        print("\nCreating events")

        for game in games:
            self._create_event(game, event_categories)

    def _create_event(self, game, event_categories):
        print("Creating event:", self._format_event_title(game))

        payload, headers = self._get_create_event_payload_and_headers(
            game, event_categories)

        response = requests.request("POST", urljoin(
            self.wp_events_api, "events"), headers=headers, data=payload)
        response.raise_for_status()

    def _get_create_event_payload_and_headers(self, game, event_categories):
        payload = json.dumps({
            "title": self._format_event_title(game),
            "start_date": game["start"].strftime("%Y-%m-%d %H:%M:%S"),
            "end_date": game["end"].strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": "UTC",  # times are given in UTC
            "venue": self.venues.get(game["venue"]),
            "categories": event_categories,
            "show_map": True,
            "website": self.league_website
        })
        headers = {
            'Authorization': self.wp_auth,
            'Content-Type': 'application/json'
        }

        return payload, headers

    def _format_event_title(self, game):
        """Return the event title, prefixed when cancelled."""
        return game["title"] if not game.get("cancelled") else "[ABGESAGT] " + game["title"]

    def delete_events(self):
        """Delete all events for the configured league."""
        print("\nDeleting events")

        events = self._get_events_for_league()
        for event in events:
            self._delete_event(event)

    def _get_events_for_league(self):
        """Get all events for the configured league."""
        events = self._get_all_events()
        return [event for event in events if html.unescape(event["website"]) == self.league_website]

    def _get_all_events(self):
        """Get all events from WordPress with pagination."""
        events = []
        
        page = 1
        while True:
            response = self._get_events_per_page(page)
            events.extend(response.json()["events"])
            if not response.json().get("next_rest_url"):
                break
            else:
                # not using next_rest_url directly because it produces a 400 error
                page += 1

        return events

    def _get_events_per_page(self, page):
        """Get events from a specific page."""
        headers = {
            'Authorization': self.wp_auth
        }

        response = requests.request("GET", urljoin(
            self.wp_events_api, "events?per_page=50&starts_after=1900-01-01&page=" + str(page)), headers=headers)
        response.raise_for_status()

        return response

    def _delete_event(self, event):
        """Delete a specific event."""
        print(f"Deleting event: {html.unescape(event['title'])} ({event['id']})")

        headers = {
            'Authorization': self.wp_auth
        }

        response = requests.request("DELETE", urljoin(
            self.wp_events_api, "events/" + str(event["id"])), headers=headers)
        response.raise_for_status()
