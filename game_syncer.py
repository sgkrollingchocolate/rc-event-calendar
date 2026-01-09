from league_data import LeagueData
from wordpress_event_manager import WordPressEventManager


class GameSyncer:
    """Syncs basketball games to WordPress event calendar."""
    
    def __init__(self, wp_base_url, wp_username, wp_password, dry_run=False):
        self.wp_base_url = wp_base_url
        self.wp_username = wp_username
        self.wp_password = wp_password
        self.dry_run = dry_run
    
    def sync_team_games(self, *, league_id, team_id, team_name, team_shortname, event_categories):
        """Sync games for a team from DBB to WordPress."""
        league_data = LeagueData(league_id)
        league_data.scrape_league_data()
        league_data.parse_calendar(team_id, team_name, team_shortname)
        
        if not self.dry_run:
            wp_manager = WordPressEventManager(
                self.wp_base_url, 
                self.wp_username,
                self.wp_password,
                league_data.website
            )
            wp_manager.create_or_update_venues(league_data.locations)
            wp_manager.delete_events()
            wp_manager.create_events(league_data.games, event_categories)
        else:
            print("[DRY-RUN] Would create venues and events for league:", league_id)