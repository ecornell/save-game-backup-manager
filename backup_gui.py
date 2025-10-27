#!/usr/bin/env python3
"""
Save Game Backup Manager - Textual TUI Version
A terminal user interface for the backup.py CLI tool using Textual
"""

import os
import sys
import threading
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Text
import asyncio

from rich.text import Text

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header, Footer, Button, Select, Static, Input, TextArea, 
    DataTable, Label,
    TabbedContent, TabPane
)
from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen
from textual import on
from textual.validation import Number
from textual.reactive import reactive

# Import the CLI functionality
from backup import (
    SaveBackupManager, 
    load_games_config, 
    save_games_config, 
    expand_path,
    list_games,
    format_file_size,
    get_directory_size
)


class ConfirmDialog(ModalScreen[bool]):
    """A modal confirmation dialog."""
    
    BINDINGS = [
        ("r", "confirm", "Confirm"),
        ("escape", "cancel", "Cancel"),
        ("left", "focus_cancel", "Focus Cancel"),
        ("right", "focus_confirm", "Focus Confirm"),
    ]
    
    def __init__(self, title: str, message: str, confirm_text: str = "Yes", cancel_text: str = "No"):
        super().__init__()
        self.title = title
        self.message = message
        self.confirm_text = confirm_text
        self.cancel_text = cancel_text
    
    def compose(self) -> ComposeResult:
        yield Container(
            Static(self.title or "Dialog", classes="dialog-title"),
            Static(self.message, classes="dialog-message"),
            Horizontal(
                Button(self.cancel_text, variant="default", id="cancel"),
                Button(self.confirm_text, variant="error", id="confirm"),
                classes="dialog-buttons"
            ),
            classes="dialog"
        )
    
    @on(Button.Pressed, "#confirm")
    def on_confirm(self):
        self.dismiss(True)
    
    @on(Button.Pressed, "#cancel") 
    def on_cancel(self):
        self.dismiss(False)
    
    def action_confirm(self):
        """Confirm action via keyboard shortcut."""
        self.dismiss(True)
    
    def action_cancel(self):
        """Cancel action via keyboard shortcut."""
        self.dismiss(False)
    
    def action_focus_cancel(self):
        """Focus the cancel button."""
        try:
            cancel_button = self.query_one("#cancel", Button)
            cancel_button.focus()
        except Exception:
            pass
    
    def action_focus_confirm(self):
        """Focus the confirm button."""
        try:
            confirm_button = self.query_one("#confirm", Button)
            confirm_button.focus()
        except Exception:
            pass


class GameConfigDialog(ModalScreen[Optional[tuple]]):
    """Modal dialog for adding/editing game configuration."""
    
    def __init__(self, title: str, game_id: str = "", game_info: Optional[Dict] = None):
        super().__init__()
        self.dialog_title = title
        self.game_id = game_id
        self.game_info = game_info or {}
    
    def compose(self) -> ComposeResult:
        yield Container(
            Static(self.dialog_title, classes="dialog-title"),
            
            Label("Game ID (short name, no spaces):"),
            Input(
                value=self.game_id,
                placeholder="e.g., grim_dawn",
                id="game_id"
            ),
            
            Label("Game Name:"),
            Input(
                value=self.game_info.get("name", ""),
                placeholder="e.g., Grim Dawn",
                id="game_name"
            ),
            
            Label("Save Directory Path:"),
            Input(
                value=self.game_info.get("save_path", ""),
                placeholder="e.g., C:/Users/Username/Documents/My Games/Grim Dawn/save",
                id="save_path"
            ),
            
            Label("Backup Directory Path (optional):"),
            Input(
                value=self.game_info.get("backup_path", ""),
                placeholder="Leave empty to use default",
                id="backup_path"
            ),
            
            Label("Description (optional):"),
            TextArea(
                text=self.game_info.get("description", ""),
                id="description"
            ),
            # Per-game override settings
            Label("Per-game settings (leave blank to use global):"),
            Horizontal(
                Label("Skip locked files:"),
                Select(
                    options=[("Default", ""), ("False", "false"), ("True", "true")],
                    id="game_skip_locked",
                    prompt="Inherit or override"
                ),
                classes="setting-row"
            ),
            Horizontal(
                Label("Copy retries:"),
                Input(
                    value=str(self.game_info.get("copy_retries", "")) if self.game_info.get("copy_retries") is not None else "",
                    placeholder="e.g., 3",
                    id="game_copy_retries",
                    validators=[Number(minimum=0, maximum=20)]
                ),
                classes="setting-row"
            ),
            Horizontal(
                Label("Retry delay (s):"),
                Input(
                    value=str(self.game_info.get("retry_delay", "")) if self.game_info.get("retry_delay") is not None else "",
                    placeholder="e.g., 0.5",
                    id="game_retry_delay",
                ),
                classes="setting-row"
            ),
            
            Horizontal(
                Button("Cancel", variant="default", id="cancel"),
                Button("OK", variant="primary", id="ok"),
                classes="dialog-buttons"
            ),
            classes="dialog config-dialog"
        )
    
    @on(Button.Pressed, "#ok")
    def on_ok(self):
        game_id = self.query_one("#game_id", Input).value.strip()
        name = self.query_one("#game_name", Input).value.strip()
        save_path = self.query_one("#save_path", Input).value.strip()
        backup_path = self.query_one("#backup_path", Input).value.strip()
        description = self.query_one("#description", TextArea).text.strip()

        # Per-game overrides (read inside method scope)
        game_skip_locked_val = self.query_one("#game_skip_locked", Select).value
        game_copy_retries_val = self.query_one("#game_copy_retries", Input).value.strip()
        game_retry_delay_val = self.query_one("#game_retry_delay", Input).value.strip()

        # Validate input
        if not game_id:
            self.notify("Game ID is required", severity="error")
            return

        if ' ' in game_id:
            self.notify("Game ID cannot contain spaces", severity="error")
            return

        if not name:
            self.notify("Game name is required", severity="error")
            return

        if not save_path:
            self.notify("Save path is required", severity="error")
            return

        result = (game_id, {
            "name": name,
            "save_path": save_path,
            "backup_path": backup_path,
            "description": description,
            # Only set overrides if provided
            **({"skip_locked_files": True} if game_skip_locked_val == "true" else ({"skip_locked_files": False} if game_skip_locked_val == "false" else {})),
            **({"copy_retries": int(game_copy_retries_val)} if game_copy_retries_val else {}),
            **({"retry_delay": float(game_retry_delay_val)} if game_retry_delay_val else {})
        })

        self.dismiss(result)
    
    @on(Button.Pressed, "#cancel")
    def on_cancel(self):
        self.dismiss(None)


class BackupManagerApp(App):
    """Main Textual application for backup management."""
    CSS_PATH = "backup_gui.tcss"
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "restore_backup", "Restore Selected"),
        Binding("c", "create_backup", "Create Backup"),
        Binding("x", "delete_backup", "Delete Backup"),
        Binding("1", "select_backup(1)", "Select Backup 1", show=False),
        Binding("2", "select_backup(2)", "Select Backup 2", show=False),
        Binding("3", "select_backup(3)", "Select Backup 3", show=False),
        Binding("4", "select_backup(4)", "Select Backup 4", show=False),
        Binding("5", "select_backup(5)", "Select Backup 5", show=False),
        Binding("6", "select_backup(6)", "Select Backup 6", show=False),
        Binding("7", "select_backup(7)", "Select Backup 7", show=False),
        Binding("8", "select_backup(8)", "Select Backup 8", show=False),
        Binding("9", "select_backup(9)", "Select Backup 9", show=False),
        Binding("0", "select_backup(10)", "Select Backup 10", show=False),
    ]
    
    def __init__(self):
        super().__init__()
        self.title = "🎮 Save Game Backup Manager 🎮 "
        self.sub_title = ""

        # Load configuration
        self.config_path = Path(__file__).parent / "games_config.json"
        self.config = load_games_config(self.config_path)

        # Current state
        self.manager = None
        self.current_game_id = None
        self.current_game_info = None
        # Auto-refresh task handle
        self._auto_refresh_task = None
    
    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="backup_tab", id="tabs"):
            with TabPane("🎮 Backup Manager", id="backup_tab"):
                yield Vertical(
                    # Game Selection Section
                    Static("🎮 Game Selection", classes="section-header"),
                    Horizontal(
                        Label("Game:", classes="game-label"),
                        Select(
                            options=[("No games configured", None)],
                            prompt="Choose a game...",
                            id="game_select",
                            allow_blank=True
                        ),
                        classes="game-selection-row"
                    ),
                    Static("", id="game_info"),
                    
                    # Backup Actions Section  
                    # Static("📁 Backup Actions", classes="section-header"),
                    Horizontal(
                        Button("💾  Create Backup  ", variant="success", id="create_backup", classes="action-buttons"),
                        Vertical(
                            # Label("Backup Description (optional):", classes="backup-desc-label"),
                            Input(placeholder="Enter backup description (optional)...", id="backup_description"),
                            classes="backup-desc-container"
                        ),
                        classes="backup-actions-container"
                    ),
                    Static(""),
                    # Backup List Section                    
                    Static("📋 Available Backups", classes="section-header"),
                    DataTable(id="backup_table", zebra_stripes=True),                    
                    Horizontal(
                        Button("🔄 Restore Selected", variant="warning", id="restore_backup"),
                        Static(""),  # Spacer to push right buttons to the right
                        Button("🔄 Refresh", variant="primary", id="refresh_backups"),                        
                        Button("🧹 Cleanup Old Backups", variant="primary", id="cleanup_backups"),
                        Button("x Delete Selected", variant="error", id="delete_backup"),
                        classes="backup-buttons-split"
                    ),
                    Static(""),
                    classes="backup-tab"
                )
            with TabPane("⚙  Configuration", id="config_tab"):
                yield Vertical(
                    # Games Configuration Section
                    Static("🎮 Configured Games", classes="section-header"),
                    DataTable(id="games_table"),
                    Horizontal(
                        Button("➕ Add Game", variant="success", id="add_game"),
                        Button("✎ Edit Selected", variant="primary", id="edit_game"),
                        Button("X Remove Selected", variant="error", id="remove_game"),
                        Button("🔄 Refresh", variant="default", id="refresh_games"),
                        classes="config-buttons"
                    ),
                    
                    # Global Settings Section
                    Static("⚙  Global Settings", classes="section-header"),
                    Horizontal(
                        Label("Default Max Backups:"),
                        Input(
                            value="10",
                            placeholder="10",
                            id="max_backups",
                            validators=[Number(minimum=1, maximum=100)],
                            compact=True
                        ),
                        classes="setting-row"
                    ),
                    Horizontal(
                        Label("Default Backup Path:"),
                        Input(
                            placeholder="Leave empty for default",
                            id="backup_path",                                                        
                            compact=True
                        ),
                        classes="setting-row"
                    ),
                    Horizontal(
                        Label("Skip locked files:"),
                        Select(
                            options=[("False", "false"), ("True", "true")],
                            id="skip_locked",
                            prompt="Skip locked files?",
                            compact=True
                        ),
                        classes="setting-row"
                    ),
                    Horizontal(
                        Label("Copy retries:"),
                        Input(
                            value="3",
                            placeholder="3",
                            id="copy_retries",
                            validators=[Number(minimum=0, maximum=20)],
                            compact=True
                        ),
                        classes="setting-row"
                    ),
                    Horizontal(
                        Label("Retry delay (s):"),
                        Input(
                            value="0.5",
                            placeholder="0.5",
                            id="retry_delay",
                            compact=True
                        ),
                        classes="setting-row"
                    ),
                    Horizontal(
                        Label("Auto-refresh:"),
                        Select(
                            options=[("Disabled", "false"), ("Enabled", "true")],
                            id="auto_refresh_enabled",
                            prompt="Enable automatic refresh",
                            compact=True
                        ),
                        Label("Interval (min):"),
                        Input(
                            value="1",
                            placeholder="Minutes",
                            id="auto_refresh_interval",
                            validators=[Number(minimum=1, maximum=1440)],
                            compact=True
                        ),
                        classes="setting-row"
                    ),
                    Button("💾 Save Settings", variant="primary", id="save_settings"),
                    
                    classes="config-tab"
                )
        yield Footer()
    
    def on_mount(self):
        """Initialize the application on mount."""
        # Setup table columns
        backup_table = self.query_one("#backup_table", DataTable)
        backup_table.add_columns("Backup Name", "Date", "Time", "Age", "Size", "Description")
        backup_table.cursor_type = "row"
        
        games_table = self.query_one("#games_table", DataTable)
        games_table.add_columns("Game ID", "Name", "Save Path", "Backup Path", "Description")
        games_table.cursor_type = "row"
    
        # Load data
        self.update_game_list()
        self.update_games_table()
        self.load_settings()
    
    def update_game_list(self):
        """Update the game selection dropdown."""
        select = self.query_one("#game_select", Select)
        games = list_games(self.config)
        
        if games:
            options = [(f"{game_info.get('name', game_id)} ({game_id})", game_id) 
                      for game_id, game_info in games]
            select.set_options(options)
            
            # Try to select the last selected game, or first game if none remembered
            last_game = self.get_last_selected_game()
            if last_game and last_game in [game_id for _, game_id in options]:
                select.value = last_game
            elif not select.value and options:
                select.value = options[0][1]
        else:
            # No games configured
            select.set_options([("No games configured - Add games in Configuration tab", None)])
            select.value = None
    
    @on(Select.Changed, "#game_select")
    def on_game_selected(self, event: Select.Changed):
        """Handle game selection change."""
        if event.value and event.value != None:  # Check for valid game selection
            self.current_game_id = event.value
            self.current_game_info = self.config.get("games", {}).get(event.value)
            
            # Save the last selected game to configuration
            self.save_last_selected_game(str(event.value))
            
            self.update_game_info()
            self.initialize_backup_manager()
            self.refresh_backup_list()
        else:
            # Clear selection
            self.current_game_id = None
            self.current_game_info = None
            self.manager = None
            self.update_game_info()
            # Clear backup list
            table = self.query_one("#backup_table", DataTable)
            table.clear()
    
    def save_last_selected_game(self, game_id: str):
        """Save the last selected game to configuration."""
        try:
            if "settings" not in self.config:
                self.config["settings"] = {}
            
            self.config["settings"]["last_selected_game"] = game_id
            save_games_config(self.config_path, self.config)
        except Exception as e:
            # Don't show error to user, just log it silently
            pass
    
    def get_last_selected_game(self) -> str | None:
        """Get the last selected game from configuration."""
        return self.config.get("settings", {}).get("last_selected_game")
    
    def update_game_info(self):
        """Update the game information display."""
        info_widget = self.query_one("#game_info", Static)
        
        if not self.current_game_info:
            info_widget.update("")
            return
        
        save_path = self.current_game_info.get("save_path", "Not set")
        backup_path = self.current_game_info.get("backup_path", "Default")
        
        info_text = f"""[chartreuse]Save Path   :[/] {save_path}
[chartreuse]Backup Path :[/] {backup_path}"""
        
        info_widget.update(info_text)
    
    def initialize_backup_manager(self):
        """Initialize the backup manager for the selected game."""
        if not self.current_game_id or not self.current_game_info:
            self.manager = None
            return
        
        try:
            game_config = self.current_game_info.copy()
            
            # Use default backup path if not specified
            if not game_config.get("backup_path"):
                default_backup_path = self.config.get("settings", {}).get("default_backup_path", "")
                if default_backup_path and self.current_game_id:
                    game_config["backup_path"] = os.path.join(default_backup_path, str(self.current_game_id))
            
            # Get max backups setting
            max_backups = self.config.get("settings", {}).get("default_max_backups", 10)
            # Read locking and retry settings
            settings = self.config.get("settings", {})
            skip_locked = settings.get("skip_locked_files", False)
            copy_retries = settings.get("copy_retries", 3)
            retry_delay = settings.get("retry_delay", 0.5)

            self.manager = SaveBackupManager(
                save_dir=game_config["save_path"],
                backup_dir=game_config.get("backup_path"),
                max_backups=max_backups,
                game_name=self.current_game_info.get("name"),
                skip_locked_files=skip_locked,
                retries=copy_retries,
                retry_delay=retry_delay
            )
            
        except Exception as e:
            self.notify(f"Failed to initialize backup manager: {e}", severity="error")
            self.manager = None
    
    def refresh_backup_list(self):
        """Refresh the backup list display."""
        table = self.query_one("#backup_table", DataTable)
        table.clear()
        
        if not self.manager:
            return
        
        try:
            backups = self.manager._get_backup_list()
            
            for index, backup_path in enumerate(backups):
                backup_path_obj = Path(backup_path)
                backup_name = backup_path_obj.name            
                               
                # Parse timestamp from backup name
                try:
                    timestamp_str = backup_name.replace("backup_", "")
                    timestamp = datetime.datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    date_str = timestamp.strftime("%Y-%m-%d")
                    time_str = timestamp.strftime("%H:%M:%S")
                    
                    # Calculate age
                    age = datetime.datetime.now() - timestamp
                    if age.days > 0:
                        age_str = f"{age.days}d ago"
                    elif age.seconds > 3600:
                        hours = age.seconds // 3600
                        age_str = f"{hours}h ago"
                    else:
                        minutes = age.seconds // 60
                        age_str = f"{minutes}m ago"
                        
                except ValueError:
                    date_str = "Unknown"
                    time_str = "Unknown"
                    age_str = "Unknown"
                
                # Get size
                try:
                    size = get_directory_size(backup_path_obj)
                    size_str = format_file_size(size)
                except Exception:
                    size_str = "Unknown"
                
                # Get description
                desc_file = backup_path_obj / ".backup_description"
                description = ""
                if desc_file.exists():
                    try:
                        description = desc_file.read_text(encoding='utf-8').strip()
                    except Exception:
                        pass


                 # Add position number for first 10 backups in separate column
                if index < 9:
                    position = str(index + 1)
                elif index == 9:
                    position = "0"
                else:
                    position = ""
                label = Text(str(position), style="#B0FC38 italic")  # type: ignore

                # Add row to table
                table.add_row(backup_name, date_str, time_str, age_str, size_str, description,
                              label=label)
            
            # Set focus to first backup if available
            if len(backups) > 0:
                # Use call_after_refresh to ensure the table is fully rendered
                self.call_after_refresh(self._set_backup_focus)
        
        except Exception as e:
            self.notify(f"Failed to refresh backup list: {e}", severity="error")
    
    def _set_backup_focus(self):
        """Set focus to the first backup in the table."""
        try:
            table = self.query_one("#backup_table", DataTable)
            if table.row_count > 0:
                table.move_cursor(row=0, column=0)
                table.focus()
        except Exception:
            # Silently ignore if table isn't ready
            pass
    
    @on(Button.Pressed, "#create_backup")
    def on_create_backup(self):
        """Create a new backup."""
        if not self.manager:
            self.notify("No game selected", severity="error")
            return
        
        description_input = self.query_one("#backup_description", Input)
        description = description_input.value.strip() or None
        
        def backup_worker():
            try:
                if not self.manager:
                    return
                result = self.manager.create_backup(description)
                self.call_from_thread(self.on_backup_complete, result is not None, description_input)
            except Exception as e:
                self.call_from_thread(self.on_backup_error, str(e))
        
        thread = threading.Thread(target=backup_worker, daemon=True)
        thread.start()
    
    def on_backup_complete(self, result: bool, description_input: Input):
        """Handle backup completion."""
        
        if result:
            self.notify("Backup created successfully!", severity="information")
            description_input.value = ""
            self.refresh_backup_list()
        else:
            self.notify("Failed to create backup", severity="error")
    
    def on_backup_error(self, error: str):
        """Handle backup error."""
        self.notify(f"Backup failed: {error}", severity="error")
    
    @on(Button.Pressed, "#restore_backup")
    def on_restore_backup(self):
        """Restore the selected backup."""
        table = self.query_one("#backup_table", DataTable)
        
        if table.cursor_row is None or table.cursor_row >= table.row_count:
            self.notify("Please select a backup to restore", severity="warning")
            return
        
        if not self.manager:
            self.notify("No game selected", severity="error")
            return
        
        # Get selected backup name
        row_key = table.get_row_at(table.cursor_row)
        backup_name = row_key[1]  # Backup name is now in column 1 (second column)
        
        # Show confirmation dialog
        def handle_restore_confirmation(confirmed: bool | None):
            if confirmed:
                self.perform_restore(backup_name, table.cursor_row)
        
        self.push_screen(
            ConfirmDialog(
                "Confirm Restore",
                f"This will overwrite your current save files with '{backup_name}'.\n\nAre you sure you want to continue?",
                "Restore",
                "Cancel"
            ),
            handle_restore_confirmation
        )
    
    def perform_restore(self, backup_name: str, cursor_row: int):
        """Perform the actual restore operation."""
        
        def restore_worker():
            try:
                if not self.manager:
                    return
                backups = self.manager._get_backup_list()
                backup_index = cursor_row + 1  # Convert to 1-based index
                
                success = self.manager.restore_backup(backup_index, skip_confirmation=True)
                self.call_from_thread(self.on_restore_complete, success)
            except Exception as e:
                self.call_from_thread(self.on_restore_error, str(e))
        
        thread = threading.Thread(target=restore_worker, daemon=True)
        thread.start()
    
    def on_restore_complete(self, success: bool):
        """Handle restore completion."""
        if success:
            self.notify("Backup restored successfully!", severity="information")
        else:
            self.notify("Failed to restore backup", severity="error")
    
    def on_restore_error(self, error: str):
        """Handle restore error."""
        self.notify(f"Restore failed: {error}", severity="error")
    
    @on(Button.Pressed, "#delete_backup")
    def on_delete_backup(self):
        """Delete the selected backup."""
        table = self.query_one("#backup_table", DataTable)
        
        if table.cursor_row is None or table.cursor_row >= table.row_count:
            self.notify("Please select a backup to delete", severity="warning")
            return
        
        if not self.manager:
            self.notify("No game selected", severity="error")
            return
        
        # Get selected backup name
        row_key = table.get_row_at(table.cursor_row)
        backup_name = row_key[1]  # Backup name is now in column 1 (second column)
        
        # Show confirmation dialog
        def handle_delete_confirmation(confirmed: bool | None):
            if confirmed:
                self.perform_delete(backup_name, table.cursor_row)
        
        self.push_screen(
            ConfirmDialog(
                "Confirm Delete",
                f"Are you sure you want to delete backup '{backup_name}'?\n\nThis action cannot be undone.",
                "Delete",
                "Cancel"
            ),
            handle_delete_confirmation
        )
    
    def perform_delete(self, backup_name: str, cursor_row: int):
        """Perform the actual delete operation."""
        if not self.manager:
            self.notify("No backup manager available", severity="error")
            return
            
        try:
            backup_index = cursor_row + 1  # Convert to 1-based index
            success = self.manager.delete_backup(backup_index, skip_confirmation=True)
            
            if success:
                self.notify("Backup deleted successfully!", severity="information")
                self.refresh_backup_list()
            else:
                self.notify("Failed to delete backup", severity="error")
                
        except Exception as e:
            self.notify(f"Delete failed: {e}", severity="error")
    
    @on(Button.Pressed, "#cleanup_backups")
    def on_cleanup_backups(self):
        """Cleanup old backups."""
        if not self.manager:
            self.notify("No game selected", severity="error")
            return
        
        # Show confirmation dialog
        def handle_cleanup_confirmation(confirmed: bool | None):
            if confirmed:
                self.perform_cleanup()
        
        self.push_screen(
            ConfirmDialog(
                "Confirm Cleanup",
                f"This will remove old backups beyond the configured limit.\n\nContinue?",
                "Cleanup",
                "Cancel"
            ),
            handle_cleanup_confirmation
        )
    
    def perform_cleanup(self):
        """Perform the actual cleanup operation."""
        if not self.manager:
            self.notify("No backup manager available", severity="error")
            return
            
        try:
            # Call the private cleanup method
            initial_count = len(self.manager._get_backup_list())
            self.manager._cleanup_old_backups()
            final_count = len(self.manager._get_backup_list())
            removed_count = initial_count - final_count
            
            if removed_count > 0:
                self.notify(f"Cleaned up {removed_count} old backup(s)", severity="information")
                self.refresh_backup_list()
            else:
                self.notify("No old backups to clean up", severity="information")
                
        except Exception as e:
            self.notify(f"Cleanup failed: {e}", severity="error")
    
    @on(Button.Pressed, "#refresh_backups")
    def on_refresh_backups(self):
        """Refresh the backup list."""
        self.refresh_backup_list()
    
    def update_games_table(self):
        """Update the games configuration table."""
        table = self.query_one("#games_table", DataTable)
        table.clear()
        
        games = self.config.get("games", {})
        
        for game_id, game_info in games.items():
            name = game_info.get("name", "")
            save_path = game_info.get("save_path", "")
            backup_path = game_info.get("backup_path", "Default")
            description = game_info.get("description", "")
            
            table.add_row(game_id, name, save_path, backup_path, description)
    
    @on(Button.Pressed, "#add_game")
    def on_add_game(self):
        """Add a new game configuration."""
        def handle_add_game_result(result: tuple | None):
            if result:
                game_id, game_info = result
                
                if game_id in self.config.get("games", {}):
                    self.notify(f"Game '{game_id}' already exists", severity="error")
                    return
                
                if "games" not in self.config:
                    self.config["games"] = {}
                
                self.config["games"][game_id] = game_info
                save_games_config(self.config_path, self.config)
                
                self.notify(f"Game '{game_info['name']}' added successfully!", severity="information")
                self.update_games_table()
                self.update_game_list()
        
        self.push_screen(
            GameConfigDialog("Add New Game"),
            handle_add_game_result
        )
    
    @on(Button.Pressed, "#edit_game")
    def on_edit_game(self):
        """Edit the selected game configuration."""
        table = self.query_one("#games_table", DataTable)
        
        if table.cursor_row is None or table.cursor_row >= table.row_count:
            self.notify("Please select a game to edit", severity="warning")
            return
        
        # Get selected game
        row_key = table.get_row_at(table.cursor_row)
        game_id = row_key[0]
        game_info = self.config.get("games", {}).get(game_id, {})
        
        def handle_edit_game_result(result: tuple | None):
            if result:
                new_game_id, new_game_info = result
                
                # If game ID changed, remove old and add new
                if new_game_id != game_id:
                    if new_game_id in self.config.get("games", {}):
                        self.notify(f"Game '{new_game_id}' already exists", severity="error")
                        return
                    
                    del self.config["games"][game_id]
                    self.config["games"][new_game_id] = new_game_info
                else:
                    self.config["games"][game_id] = new_game_info
                
                save_games_config(self.config_path, self.config)
                
                self.notify(f"Game '{new_game_info['name']}' updated successfully!", severity="information")
                self.update_games_table()
                self.update_game_list()
        
        self.push_screen(
            GameConfigDialog("Edit Game", game_id, game_info),
            handle_edit_game_result
        )
    
    @on(Button.Pressed, "#remove_game")
    def on_remove_game(self):
        """Remove the selected game configuration."""
        table = self.query_one("#games_table", DataTable)
        
        if table.cursor_row is None or table.cursor_row >= table.row_count:
            self.notify("Please select a game to remove", severity="warning")
            return
        
        # Get selected game
        row_key = table.get_row_at(table.cursor_row)
        game_id = row_key[0]
        game_info = self.config.get("games", {}).get(game_id, {})
        game_name = game_info.get("name", game_id)
        
        # Show confirmation dialog
        def handle_remove_confirmation(confirmed: bool | None):
            if confirmed:
                del self.config["games"][game_id]
                save_games_config(self.config_path, self.config)
                
                self.notify(f"Game '{game_name}' removed successfully!", severity="information")
                self.update_games_table()
                self.update_game_list()
        
        self.push_screen(
            ConfirmDialog(
                "Confirm Remove",
                f"Are you sure you want to remove '{game_name}' from the configuration?",
                "Remove",
                "Cancel"
            ),
            handle_remove_confirmation
        )
    
    @on(Button.Pressed, "#refresh_games")
    def on_refresh_games(self):
        """Refresh the games table."""
        self.update_games_table()
    
    def load_settings(self):
        """Load global settings into the UI."""
        settings = self.config.get("settings", {})
        
        max_backups_input = self.query_one("#max_backups", Input)
        max_backups_input.value = str(settings.get("default_max_backups", 10))
        
        backup_path_input = self.query_one("#backup_path", Input)
        backup_path_input.value = settings.get("default_backup_path", "")

        # New settings
        skip_locked_select = self.query_one("#skip_locked", Select)
        skip_locked_val = settings.get("skip_locked_files", False)
        skip_locked_select.value = "true" if skip_locked_val else "false"

        copy_retries_input = self.query_one("#copy_retries", Input)
        copy_retries_input.value = str(settings.get("copy_retries", 3))

        retry_delay_input = self.query_one("#retry_delay", Input)
        retry_delay_input.value = str(settings.get("retry_delay", 0.5))

        # Auto-refresh settings
        auto_refresh_enabled = settings.get("auto_refresh_enabled", True)
        auto_refresh_interval = settings.get("auto_refresh_interval", 5)

        auto_refresh_select = self.query_one("#auto_refresh_enabled", Select)
        auto_refresh_select.value = "true" if auto_refresh_enabled else "false"

        auto_refresh_interval_input = self.query_one("#auto_refresh_interval", Input)
        auto_refresh_interval_input.value = str(auto_refresh_interval)

        # Start auto-refresh if enabled
        try:
            if auto_refresh_enabled:
                # use integer minutes
                minutes = int(auto_refresh_interval) if auto_refresh_interval else 5
                self.start_auto_refresh(minutes)
        except Exception:
            # Ignore startup errors for auto-refresh
            pass
    
    @on(Button.Pressed, "#save_settings")
    def on_save_settings(self):
        """Save global settings."""
        try:
            max_backups_input = self.query_one("#max_backups", Input)
            backup_path_input = self.query_one("#backup_path", Input)
            
            max_backups = int(max_backups_input.value) if max_backups_input.value else 10
            backup_path = backup_path_input.value.strip()
            # Read new settings
            skip_locked_select = self.query_one("#skip_locked", Select)
            skip_locked = True if (skip_locked_select.value == "true") else False

            copy_retries = int(self.query_one("#copy_retries", Input).value or 3)
            try:
                retry_delay = float(self.query_one("#retry_delay", Input).value or 0.5)
            except ValueError:
                retry_delay = 0.5
            
            if "settings" not in self.config:
                self.config["settings"] = {}
            
            self.config["settings"]["default_max_backups"] = max_backups
            self.config["settings"]["default_backup_path"] = backup_path
            self.config["settings"]["skip_locked_files"] = skip_locked
            self.config["settings"]["copy_retries"] = copy_retries
            self.config["settings"]["retry_delay"] = retry_delay
            # Auto-refresh settings
            auto_refresh_select = self.query_one("#auto_refresh_enabled", Select)
            auto_refresh_enabled = True if (auto_refresh_select.value == "true") else False
            auto_refresh_interval = int(self.query_one("#auto_refresh_interval", Input).value or 5)

            self.config["settings"]["auto_refresh_enabled"] = auto_refresh_enabled
            self.config["settings"]["auto_refresh_interval"] = auto_refresh_interval
            
            save_games_config(self.config_path, self.config)
            
            self.notify("Settings saved successfully!", severity="information")
            
            # Reinitialize backup manager if needed
            if self.manager:
                self.manager.max_backups = max_backups
                # Update runtime options on manager instance
                self.manager.skip_locked_files = skip_locked
                self.manager.retries = copy_retries
                self.manager.retry_delay = retry_delay
            # Start/stop auto-refresh based on new settings
            try:
                if auto_refresh_enabled:
                    self.start_auto_refresh(auto_refresh_interval)
                else:
                    self.stop_auto_refresh()
            except Exception:
                pass
            
        except ValueError:
            self.notify("Invalid value for max backups", severity="error")
        except Exception as e:
            self.notify(f"Failed to save settings: {e}", severity="error")

    
    def action_select_backup(self, backup_number: int):
        """Select a backup by number (1-9)."""
        try:
            table = self.query_one("#backup_table", DataTable)
            
            # Check if the backup exists (backup_number is 1-indexed)
            if backup_number > len(table.rows) or backup_number < 1:
                return  # Ignore if backup number doesn't exist
            
            # Convert to 0-indexed for table cursor
            row_index = backup_number - 1
            
            # Move cursor to the specified row
            table.move_cursor(row=row_index, column=0)
            
            # Show a brief notification
            # self.notify(f"Selected backup #{backup_number}", timeout=1.0)
            
        except Exception:
            # Silently ignore errors (table might not be ready)
            pass

    def action_refresh(self):
        """Refresh current view."""
        self.refresh_backup_list()

    # Auto-refresh helpers
    def start_auto_refresh(self, minutes: int):
        """Start the background auto-refresh task. Minutes must be >= 1."""
        try:
            minutes = max(1, int(minutes))
        except Exception:
            minutes = 5

        # If existing task running, cancel it first
        if self._auto_refresh_task and not self._auto_refresh_task.done():
            try:
                self._auto_refresh_task.cancel()
            except Exception:
                pass

        # Create asyncio task
        loop = asyncio.get_event_loop()
        self._auto_refresh_task = loop.create_task(self._auto_refresh_loop(minutes))

    def stop_auto_refresh(self):
        """Stop the background auto-refresh task if running."""
        if self._auto_refresh_task and not self._auto_refresh_task.done():
            try:
                self._auto_refresh_task.cancel()
            except Exception:
                pass
        self._auto_refresh_task = None

    async def _auto_refresh_loop(self, minutes: int):
        """Async loop that refreshes backups every `minutes` minutes."""
        try:
            while True:
                # Wait for the configured interval (in seconds)
                await asyncio.sleep(max(1, int(minutes)) * 60)
                # Call refresh on the main thread/context
                try:
                    # Use call_from_thread to safely update UI if running in different thread
                    self.call_from_thread(self.refresh_backup_list)
                except Exception:
                    # Fallback to direct call
                    try:
                        self.refresh_backup_list()
                    except Exception:
                        pass
        except asyncio.CancelledError:
            # Task was cancelled; just exit
            return
    
    def action_create_backup(self):
        """Create backup via keyboard shortcut."""
        self.on_create_backup()
    
    def action_delete_backup(self):
        """Delete backup via keyboard shortcut."""
        self.on_delete_backup()
    
    def action_restore_backup(self):
        """Restore backup via keyboard shortcut."""
        self.on_restore_backup()


def main():
    """Run the Textual backup manager application."""
    app = BackupManagerApp()
    app.run()


if __name__ == "__main__":
    main()
