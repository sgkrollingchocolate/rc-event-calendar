from argparse import ArgumentParser

from game_syncer import GameSyncer

# WordPress base URL
WP_BASE_URL = "https://www.rolling-chocolate.de/"

# RC teams configuration
RC_TEAMS = [
    {
        "league_id": "48078",
        "team_id": "401699",
        "team_name": "SGK Rolling Chocolate",
        "team_shortname": "RC1",
        "event_categories": ["rc1", "spieltag", "runde-25-26"]
    },
    {
        "league_id": "48083",
        "team_id": "401735",
        "team_name": "SGK Rolling Chocolate 2",
        "team_shortname": "RC2",
        "event_categories": ["rc2", "spieltag", "runde-25-26"]
    }
]


def main():
    args = parse_arguments()
    
    syncer = GameSyncer(WP_BASE_URL, args.wp_user.strip(), args.wp_pass.strip(), args.dry_run)
    
    for team_config in RC_TEAMS:
        syncer.sync_team_games(**team_config)


def parse_arguments():
    parser = ArgumentParser()
    parser.add_argument("-u", "--wp-user", dest="wp_user", help="WordPress username", required=True)
    parser.add_argument("-p", "--wp-password", dest="wp_pass", help="WordPress password", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Only simulate, don't write changes")
    return parser.parse_args()


if __name__ == "__main__":
    main()
