#!/usr/bin/env python3
"""guesty-cli — Universal Command-Line Interface for Guesty"""

import os
import sys
import argparse
from guesty_cli import __version__
from guesty_cli.core.exit_codes import (
    EXIT_SUCCESS, EXIT_ERROR, EXIT_INTERRUPTED, exit_for_error,
)
from guesty_cli.core.output import OutputMode, set_output_mode, is_json, is_plain

# Known subcommands for shortcut handling
LISTING_ACTIONS = {'get', 'create', 'update', 'delete'}
RESERVATION_ACTIONS = {'get', 'create', 'update', 'cancel', 'approve', 'decline'}

def handle_shortcuts(argv):
    """Convert shortcut commands to full subcommand form.
    
    guesty listing "Name" -> guesty listing get "Name"
    guesty reservation "CODE" -> guesty reservation get "CODE"
    """
    # Find 'listing' or 'reservation' command position
    for i, arg in enumerate(argv):
        if arg == 'listing' and i + 1 < len(argv):
            next_arg = argv[i + 1]
            # If next arg is not a flag and not a known action, it's a listing name
            if not next_arg.startswith('--') and next_arg not in LISTING_ACTIONS:
                # Insert 'get' before the listing name
                argv.insert(i + 1, 'get')
                break
        elif arg == 'reservation' and i + 1 < len(argv):
            next_arg = argv[i + 1]
            # If next arg is not a flag and not a known action, it's a reservation code
            if not next_arg.startswith('--') and next_arg not in RESERVATION_ACTIONS:
                # Insert 'get' before the reservation code
                argv.insert(i + 1, 'get')
                break
    return argv

def main():
    # Process shortcuts before argparse
    sys.argv = handle_shortcuts(sys.argv)
    
    parser = argparse.ArgumentParser(
        prog='guesty',
        description='Universal CLI for Guesty PMS — manage your vacation rental operations from the terminal.',
        epilog='Run "guesty <command> --help" for details on each command.'
    )
    parser.add_argument('--version', action='version', version=f'guesty-cli v{__version__}')
    parser.add_argument('--no-color', action='store_true', help='Disable colored output')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--plain', '-p', '--tsv', action='store_true', help='Output stable TSV (no colors, pipe-friendly)')
    parser.add_argument('--select', type=str, help='Comma-separated fields to select in JSON mode (supports dot.paths)')
    parser.add_argument('--results-only', action='store_true', help='In JSON mode, emit only primary results')
    parser.add_argument('--dry-run', '-n', action='store_true', help='Preview changes without executing them')
    parser.add_argument('--force', '-y', action='store_true', help='Skip confirmations')
    parser.add_argument('--access-token', type=str, help='Use provided access token directly (bypasses OAuth flow)',
                        default=os.environ.get('GUESTY_ACCESS_TOKEN'))
    parser.add_argument('--no-input', '--non-interactive', action='store_true',
                        help='Never prompt; fail instead (for CI/agents)')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Register all commands with graceful fallback for missing modules
    command_modules = [
        ('auth', 'Authentication and setup'),
        ('status', 'Dashboard overview'),
        ('listings', 'Property management'),
        ('photos', 'Listing photo management (upload, reorder, delete)'),
        ('reservations', 'Reservation management'),
        ('views', 'Guesty built-in reports and views'),
        ('guests', 'Guest profiles'),
        ('owners', 'Owner management'),
        ('integrations', 'OTA integrations'),
        ('users', 'Team user management'),
        ('calendar_sync', 'Calendar sync operations'),
        ('tasks', 'Task management'),
        ('reviews', 'Review management'),
        ('financials', 'Financial analytics'),
        ('occupancy', 'Occupancy analytics and metrics'),
        ('search', 'Full-text search'),
        ('sync', 'Data synchronization'),
        ('export', 'Data export'),
        ('schema', 'CLI schema introspection'),
        ('completion', 'Shell completion scripts'),
        ('agent', 'Agent-friendly helpers'),
        ('raw', 'Raw access to documented Guesty Open API endpoints'),
        ('set_custom_field', 'Merge-safe, verified listing custom-field writes'),
    ]
    
    registered_count = 0
    for module_name, description in command_modules:
        try:
            module = __import__(f'guesty_cli.commands.{module_name}', fromlist=['register'])
            module.register(subparsers)
            registered_count += 1
        except ImportError as e:
            # Module not yet implemented — skip gracefully
            if os.environ.get('GUESTY_DEBUG'):
                print(f"Warning: Could not load command '{module_name}': {e}", file=sys.stderr)
    
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(EXIT_SUCCESS)

    # Set global no-color (also forced on for plain mode)
    if args.no_color or args.plain:
        os.environ['NO_COLOR'] = '1'

    # Determine output mode
    if args.json:
        mode = OutputMode.JSON
    elif args.plain:
        mode = OutputMode.PLAIN
    else:
        # Auto-JSON when piped (agent-friendly, like gogcli)
        if os.environ.get('GUESTY_AUTO_JSON') and not sys.stdout.isatty():
            mode = OutputMode.JSON
        else:
            mode = OutputMode.HUMAN

    select_fields = None
    if getattr(args, 'select', None):
        select_fields = [f.strip() for f in args.select.split(',')]

    set_output_mode(
        mode,
        select=select_fields,
        results_only=getattr(args, 'results_only', False),
    )

    # Store access token override for commands
    if getattr(args, 'access_token', None):
        os.environ['_GUESTY_ACCESS_TOKEN'] = args.access_token

    # Store no-input mode for commands
    if getattr(args, 'no_input', None):
        os.environ['GUESTY_NO_INPUT'] = '1'

    # Check if command was registered
    if not hasattr(args, 'func'):
        print(f"Error: Command '{args.command}' is not yet implemented.", file=sys.stderr)
        sys.exit(EXIT_ERROR)

    # Run the command
    try:
        args.func(args)
    except KeyboardInterrupt:
        print('\nAborted.')
        sys.exit(EXIT_INTERRUPTED)
    except Exception as e:
        code = exit_for_error(e)
        if is_json():
            import json as _json
            print(_json.dumps({"error": str(e), "exit_code": code}))
        elif is_plain():
            print(f"error\t{e}")
        else:
            from guesty_cli.core.output import red
            print(red(f'\nError: {e}'))
        sys.exit(code)

if __name__ == '__main__':
    main()
