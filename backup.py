import os
import shutil
import datetime
import glob
import argparse
import sys
import time
import json
import subprocess
import threading
import tempfile
import hashlib
import errno
from pathlib import Path
from typing import List, Optional, Dict, Any
import ctypes
from ctypes import wintypes

# Color codes for better terminal output
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def print_colored(text: str, color: str = Colors.WHITE, bold: bool = False, end: str = "\n"):
    """Print colored text to terminal"""
    prefix = Colors.BOLD if bold else ""
    print(f"{prefix}{color}{text}{Colors.END}", end=end)

def print_header(text: str):
    """Print a formatted header"""
    print_colored(f"\n{'='*50}", Colors.CYAN)
    print_colored(f" {text} ", Colors.CYAN, bold=True)
    print_colored(f"{'='*50}", Colors.CYAN)

def print_success(text: str):
    """Print success message"""
    print_colored(f"✓ {text}", Colors.GREEN, bold=True)

def print_error(text: str):
    """Print error message"""
    print_colored(f"✗ {text}", Colors.RED, bold=True)

def print_warning(text: str):
    """Print warning message"""
    print_colored(f"⚠ {text}", Colors.YELLOW, bold=True)

def print_info(text: str):
    """Print info message"""
    print_colored(f"ℹ {text}", Colors.BLUE)

def show_progress(current: int, total: int, prefix: str = "Progress"):
    """Show a simple progress indicator"""
    percent = (current / total) * 100
    bar_length = 30
    filled_length = int(bar_length * current // total)
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    print(f"\r{prefix}: |{bar}| {percent:.1f}% ({current}/{total})", end='', flush=True)

def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    if size_bytes == 0:
        return "0B"
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024.0 and i < len(size_names) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.1f}{size_names[i]}"

def get_directory_size(path: Path) -> int:
    """Calculate total size of directory"""
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                if os.path.exists(file_path):
                    total_size += os.path.getsize(file_path)
    except (OSError, FileNotFoundError):
        pass
    return total_size


def compute_directory_sha256(path: Path) -> str:
    """Compute a SHA256 hash for all files under a directory in a deterministic order."""
    h = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        # Sort to ensure deterministic order
        dirs.sort()
        files.sort()
        for fname in files:
            file_path = os.path.join(root, fname)
            try:
                # Update with relative file path to make hash path-independent
                rel_path = os.path.relpath(file_path, start=str(path)).replace('\\', '/')
                h.update(rel_path.encode('utf-8'))
                # Update with file size and content
                stat = os.stat(file_path)
                h.update(str(stat.st_size).encode('utf-8'))
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        h.update(chunk)
            except Exception:
                # If a file can't be read, include an error marker
                h.update(b'__unreadable__')
    return h.hexdigest()

def load_games_config(config_path: Path) -> Dict[str, Any]:
    """Load games configuration from JSON file"""
    try:
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            # Create default config
            default_config = {
                "games": {
                    "example_game": {
                        "name": "Example Game",
                        "save_path": "C:\\Users\\{username}\\Documents\\Example Game\\Saves",
                        "backup_path": "C:\\Users\\{username}\\Documents\\Example Game\\Backups",
                        "description": "Example game configuration"
                    }
                },
                "settings": {
                    "default_max_backups": 10,
                    "auto_expand_paths": True,
                    "default_backup_path": "./backups"
                }
            }
            save_games_config(config_path, default_config)
            return default_config
    except Exception as e:
        print_error(f"Failed to load config file: {e}")
        return {"games": {}, "settings": {"default_max_backups": 10}}

def save_games_config(config_path: Path, config: Dict[str, Any]):
    """Save games configuration to JSON file"""
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print_error(f"Failed to save config file: {e}")

def expand_path(path_str: str) -> str:
    """Expand environment variables and user paths"""
    # Expand environment variables
    expanded = os.path.expandvars(path_str)
    # Expand user home directory
    expanded = os.path.expanduser(expanded)
    return expanded

def list_games(config: Dict[str, Any]) -> List[tuple]:
    """List available games from config"""
    games = []
    for game_id, game_info in config.get("games", {}).items():
        games.append((game_id, game_info))
    return games

def select_game(config: Dict[str, Any]) -> Optional[tuple]:
    """Interactive game selection"""
    games = list_games(config)
    
    if not games:
        print_warning("No games configured. Please add games to the config file first.")
        return None
    
    print_header("Select Game")
    
    for i, (game_id, game_info) in enumerate(games, 1):
        name = game_info.get("name", game_id)
        save_path = game_info.get("save_path", "Unknown")
        backup_path = game_info.get("backup_path", "")
        description = game_info.get("description", "")
        
        print_colored(f"{i:2d}. ", Colors.CYAN, bold=True, end="")
        print_colored(f"{name}", Colors.WHITE, bold=True)
        print_colored(f"    📁 Save: {save_path}", Colors.BLUE)
        if backup_path:
            print_colored(f"    💾 Backup: {backup_path}", Colors.GREEN)
        if description:
            print_colored(f"    📝 {description}", Colors.MAGENTA)
    
    try:
        choice = input(f"\n{Colors.YELLOW}Select game number (1-{len(games)}) or 'q' to quit: {Colors.END}")
        if choice.lower() == 'q':
            return None
        
        choice = int(choice) - 1
        if 0 <= choice < len(games):
            return games[choice]
        else:
            print_error("Invalid choice.")
            return None
    except (ValueError, IndexError):
        print_error("Invalid input.")
        return None

def add_game_to_config(config_path: Path, config: Dict[str, Any]):
    """Interactive function to add a new game to config"""
    print_header("Add New Game")
    
    game_id = get_user_input_with_prompt("Game ID (short name, no spaces)")
    if not game_id or ' ' in game_id:
        print_error("Invalid game ID. Must not contain spaces.")
        return
    
    if game_id in config.get("games", {}):
        print_error(f"Game '{game_id}' already exists in config.")
        return
    
    name = get_user_input_with_prompt("Game name")
    if not name:
        print_error("Game name is required.")
        return
    
    save_path = get_user_input_with_prompt("Save directory path")
    if not save_path:
        print_error("Save path is required.")
        return
    
    backup_path = get_user_input_with_prompt("Backup directory path (optional)")
    
    description = get_user_input_with_prompt("Description (optional)")
    
    # Validate path exists (after expansion)
    expanded_path = expand_path(save_path)
    if not os.path.exists(expanded_path):
        print_warning(f"Path does not exist: {expanded_path}")
        confirm = input(f"{Colors.YELLOW}Add anyway? (y/N): {Colors.END}")
        if confirm.lower() != 'y':
            print_info("Game not added.")
            return
    
    # Add to config
    if "games" not in config:
        config["games"] = {}
    
    config["games"][game_id] = {
        "name": name,
        "save_path": save_path,
        "backup_path": backup_path,
        "description": description
    }
    
    save_games_config(config_path, config)
    print_success(f"Game '{name}' added to config!")

def edit_game_config(config_path: Path, config: Dict[str, Any]):
    """Interactive function to edit a game in config"""
    games = list_games(config)
    if not games:
        print_warning("No games configured.")
        return
    
    print_header("Edit Game Configuration")
    
    # Show games and let user select
    for i, (game_id, game_info) in enumerate(games, 1):
        name = game_info.get("name", game_id)
        print_colored(f"{i:2d}. {name}", Colors.WHITE)
    
    try:
        choice = input(f"\n{Colors.YELLOW}Select game to edit (1-{len(games)}) or 'q' to quit: {Colors.END}")
        if choice.lower() == 'q':
            return
        
        choice = int(choice) - 1
        if not (0 <= choice < len(games)):
            print_error("Invalid choice.")
            return
        
        game_id, game_info = games[choice]
        
        print_info(f"Editing: {game_info.get('name', game_id)}")
        
        # Edit fields
        new_name = get_user_input_with_prompt("Game name", game_info.get("name"))
        new_path = get_user_input_with_prompt("Save directory path", game_info.get("save_path"))
        new_backup_path = get_user_input_with_prompt("Backup directory path", game_info.get("backup_path", ""))
        new_desc = get_user_input_with_prompt("Description", game_info.get("description", ""))
        
        # Update config
        config["games"][game_id].update({
            "name": new_name,
            "save_path": new_path,
            "backup_path": new_backup_path,
            "description": new_desc
        })
        
        save_games_config(config_path, config)
        print_success(f"Game '{new_name}' updated!")
        
    except (ValueError, IndexError):
        print_error("Invalid input.")

def remove_game_from_config(config_path: Path, config: Dict[str, Any]):
    """Interactive function to remove a game from config"""
    games = list_games(config)
    if not games:
        print_warning("No games configured.")
        return
    
    print_header("Remove Game")
    
    # Show games and let user select
    for i, (game_id, game_info) in enumerate(games, 1):
        name = game_info.get("name", game_id)
        print_colored(f"{i:2d}. {name}", Colors.WHITE)
    
    try:
        choice = input(f"\n{Colors.YELLOW}Select game to remove (1-{len(games)}) or 'q' to quit: {Colors.END}")
        if choice.lower() == 'q':
            return
        
        choice = int(choice) - 1
        if not (0 <= choice < len(games)):
            print_error("Invalid choice.")
            return
        
        game_id, game_info = games[choice]
        game_name = game_info.get("name", game_id)
        
        confirm = input(f"\n{Colors.RED}Are you sure you want to remove '{game_name}'? (y/N): {Colors.END}")
        if confirm.lower() != 'y':
            print_info("Removal cancelled.")
            return
        
        del config["games"][game_id]
        save_games_config(config_path, config)
        print_success(f"Game '{game_name}' removed from config!")
        
    except (ValueError, IndexError):
        print_error("Invalid input.")

class SaveBackupManager:
    def __init__(self, save_dir=None, backup_dir=None, max_backups=10, game_name=None,
                 skip_locked_files: bool = False, pre_backup_cmd: Optional[str] = None,
                 post_backup_cmd: Optional[str] = None, retries: int = 3, retry_delay: float = 0.5):
        # Default to current directory if not specified
        self.save_dir = Path(save_dir) if save_dir else Path.cwd()
        # Ensure we use a consistent default backup directory location for both
        # the CLI and the programmatic API: use the repository/script root
        # 'backups' folder if the caller doesn't supply one.
        if backup_dir:
            self.backup_dir = Path(backup_dir)
        else:
            self.backup_dir = Path(__file__).parent / "backups"
        self.max_backups = max_backups
        self.game_name = game_name
        # New options for handling locked files and hooks
        self.skip_locked_files = skip_locked_files
        self.pre_backup_cmd = pre_backup_cmd
        self.post_backup_cmd = post_backup_cmd
        self.retries = retries
        self.retry_delay = retry_delay
        
        # Create backup directory if it doesn't exist (create any missing parent dirs)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # On startup, attempt to recover or clean up any leftover temp dirs
        try:
            self._recover_or_cleanup_tmp_dirs()
        except Exception as e:
            # Non-fatal: just log
            print_warning(f"Failed to cleanup leftover temp dirs: {e}")

        print_info(f"Game: {self.game_name or 'Custom'}")
        print_info(f"Save directory: {self.save_dir}")
        print_info(f"Backup directory: {self.backup_dir}")
        print_info(f"Maximum backups: {self.max_backups}")
    
    def _safe_rmtree(self, path):
        """Safely remove directory tree with Windows compatibility"""
        def handle_remove_readonly(func, path, exc_info):
            """Error handler for Windows read-only files"""
            exc = exc_info[1] if isinstance(exc_info, tuple) else exc_info
            if hasattr(exc, 'errno') and exc.errno == 13:  # Permission denied
                os.chmod(path, 0o777)
                func(path)
            else:
                raise exc
        
        # Use onexc for Python 3.12+ or onerror for older versions
        try:
            shutil.rmtree(path, onexc=handle_remove_readonly)
        except TypeError:
            # Fallback to onerror for Python < 3.12
            def handle_remove_readonly_old(func, path, exc_info):
                handle_remove_readonly(func, path, exc_info)
            shutil.rmtree(path, onerror=handle_remove_readonly_old)

    def _run_hook(self, cmd: Optional[str], when: str = "pre"):
        """Run a pre/post backup command if configured."""
        if not cmd:
            return
        try:
            print_info(f"Running {when}-backup hook: {cmd}")
            subprocess.run(cmd, shell=True, check=False)
        except Exception as e:
            print_warning(f"Hook '{when}' failed: {e}")

    def _win_read_file_to_path(self, src: str, dst_path: str) -> bool:
        """Try to read file using Win32 CreateFile with generous sharing to copy locked files.
        Returns True on success, False on failure.
        """
        # Only available on Windows
        if os.name != 'nt':
            return False

        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        FILE_SHARE_DELETE = 0x00000004
        OPEN_EXISTING = 3

        CreateFileW = ctypes.windll.kernel32.CreateFileW
        ReadFile = ctypes.windll.kernel32.ReadFile
        CloseHandle = ctypes.windll.kernel32.CloseHandle

        handle = CreateFileW(wintypes.LPCWSTR(src), GENERIC_READ,
                             FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                             None, OPEN_EXISTING, 0, None)
        if handle == wintypes.HANDLE(-1).value:
            return False

        try:
            with open(dst_path, 'wb') as out_f:
                buf_size = 8192
                buf = ctypes.create_string_buffer(buf_size)
                bytes_read = wintypes.DWORD(0)
                while True:
                    ok = ReadFile(handle, buf, buf_size, ctypes.byref(bytes_read), None)
                    if not ok:
                        break
                    if bytes_read.value == 0:
                        break
                    out_f.write(buf.raw[:bytes_read.value])
        finally:
            CloseHandle(handle)
        try:
            shutil.copystat(src, dst_path)
        except Exception:
            pass
        return True

    def _safe_copy(self, src: str, dst: str, follow_symlinks=True) -> None:
        """Copy a single file with retries and Windows fallback for locked files."""
        last_err = None
        for attempt in range(1, max(1, self.retries) + 1):
            try:
                shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
                return
            except (PermissionError, OSError) as e:
                last_err = e
                # Try Windows-specific fallback to read locked files
                if os.name == 'nt':
                    try:
                        ok = self._win_read_file_to_path(src, dst)
                        if ok:
                            return
                    except Exception:
                        pass

                if attempt < self.retries:
                    time.sleep(self.retry_delay * attempt)
                    continue
                # If configured to skip locked files, warn and return without raising
                if self.skip_locked_files:
                    print_warning(f"Skipping locked file: {src} -> {dst} ({last_err})")
                    return
                # Re-raise the last error if we exhausted retries
                raise
    
    def _get_save_size(self) -> str:
        """Get the size of the save directory"""
        try:
            size = get_directory_size(self.save_dir)
            return format_file_size(size)
        except Exception:
            return "Unknown"
    
    def _cleanup_old_backups(self):
        """Remove old backups if we exceed max_backups"""
        backups = self._get_backup_list()
        if len(backups) > self.max_backups:
            backups_to_delete = backups[self.max_backups:]
            print_warning(f"Cleaning up {len(backups_to_delete)} old backup(s)...")
            for backup_path in backups_to_delete:
                try:
                    self._safe_rmtree(backup_path)
                    backup_name = Path(backup_path).name
                    print_info(f"Deleted old backup: {backup_name}")
                except Exception as e:
                    print_error(f"Failed to delete {backup_path}: {e}")
    
    def _get_backup_list(self) -> List[str]:
        """Get sorted list of backup directories"""
        backup_pattern = self.backup_dir / "backup_*"
        return sorted(glob.glob(str(backup_pattern)), reverse=True)

    def _recover_or_cleanup_tmp_dirs(self):
        """Detect leftover temp backup dirs (created with mkdtemp prefix '.backup_...') and
        either recover them by renaming to the final backup name or remove them if incomplete.
        """
        if not self.backup_dir.exists():
            return

        for entry in self.backup_dir.iterdir():
            try:
                if not entry.is_dir():
                    continue
                name = entry.name
                # Temp dirs created by mkdtemp use prefix f".{backup_name}."
                if not name.startswith('.backup_'):
                    continue

                print_info(f"Found leftover temp backup dir: {name}")

                # Heuristic: if directory has no files, remove it; otherwise attempt recovery
                file_count = sum(len(files) for _, _, files in os.walk(entry))
                if file_count == 0:
                    print_info(f"Removing empty temp dir: {name}")
                    self._safe_rmtree(entry)
                    continue

                # Derive final backup base name: strip leading dot and suffix
                tmp_name = name[1:]
                final_base = tmp_name.split('.', 1)[0]
                final_path = self.backup_dir / final_base

                if final_path.exists():
                    # A final directory already exists; remove the temp dir
                    print_warning(f"Final backup already exists for {final_base}; removing temp dir")
                    self._safe_rmtree(entry)
                    continue

                # Attempt to move temp dir to final name; handle cross-device similarly to create_backup
                try:
                    os.replace(str(entry), str(final_path))
                    move_method = "recovered_atomic"
                except OSError as ex:
                    if getattr(ex, 'errno', None) == errno.EXDEV:
                        try:
                            shutil.move(str(entry), str(final_path))
                            move_method = "recovered_copied"
                        except Exception as move_err:
                            print_warning(f"Failed to move temp dir {name} to {final_base}: {move_err}")
                            # Remove the temp dir to avoid clutter
                            self._safe_rmtree(entry)
                            continue
                    else:
                        print_warning(f"Failed to rename temp dir {name}: {ex}")
                        self._safe_rmtree(entry)
                        continue

                # Write metadata for recovered backup
                try:
                    checksum = compute_directory_sha256(final_path)
                    total_size = get_directory_size(final_path)
                    total_files = sum(len(files) for _, _, files in os.walk(final_path))
                    meta = {
                        "completed_at": datetime.datetime.now().isoformat(),
                        "checksum": checksum,
                        "files": total_files,
                        "size_bytes": total_size,
                        "move_method": move_method,
                        "recovered": True
                    }
                    meta_file = final_path / ".backup_meta.json"
                    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
                    print_success(f"Recovered backup: {final_base}")
                except Exception as meta_err:
                    print_warning(f"Failed to write metadata for recovered backup {final_base}: {meta_err}")
            except Exception:
                # Ignore errors per-directory and continue
                continue
    
    def create_backup(self, description: Optional[str] = None) -> Optional[Path]:
        """Create a timestamped backup of the save directory"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{timestamp}"
        backup_path = self.backup_dir / backup_name
        
        save_size = self._get_save_size()
        
        try:
            print_info(f"Creating backup: {backup_name}")
            print_info(f"Save directory size: {save_size}")
            
            if description:
                print_info(f"Description: {description}")
            
            # Count files for progress
            file_count = sum(len(files) for _, _, files in os.walk(self.save_dir))
            if file_count == 0:
                print_warning("No files found in save directory")
                return None
            
            print_info(f"Backing up {file_count} files...")
            
            # Show progress during backup
            start_time = time.time()
            
            def copy_with_progress(src, dst, *, follow_symlinks=True):
                files_copied = getattr(copy_with_progress, 'counter', 0)
                copy_with_progress.counter = files_copied + 1
                show_progress(copy_with_progress.counter, file_count, "Copying files")
                # Use safe copy that handles locked files and retries
                try:
                    self._safe_copy(src, dst, follow_symlinks=follow_symlinks)
                    return dst
                except Exception:
                    # Re-raise to allow higher-level handler to catch and cleanup
                    raise
            
            # Perform copy into a temporary directory inside the backups folder so
            # incomplete backups are never visible to listing/restore operations.
            tmp_dir = None
            try:
                # Create a temp directory path (shutil.copytree requires dest to not exist)
                # Use a hidden prefix so it's ignored by normal listings
                tmp_dir = Path(tempfile.mkdtemp(prefix=f".{backup_name}.", dir=str(self.backup_dir)))

                # Copy into the temp directory
                shutil.copytree(
                    self.save_dir,
                    tmp_dir,
                    ignore=shutil.ignore_patterns("backups", "*.pyc", "__pycache__", "*.tmp"),
                    copy_function=copy_with_progress,
                    dirs_exist_ok=True
                )

                print()  # New line after progress bar
                elapsed_time = time.time() - start_time

                # Save description if provided (write into tmp dir before rename)
                if description:
                    desc_file = tmp_dir / ".backup_description"
                    desc_file.write_text(description, encoding='utf-8')

                # Atomically move the completed temp dir to the final name.
                # os.replace is atomic on the same filesystem; if we get EXDEV
                # (cross-device link), fall back to shutil.move which copies
                # across filesystems.
                move_method = "atomic"
                try:
                    if backup_path.exists():
                        # Shouldn't happen, but ensure no collision
                        self._safe_rmtree(backup_path)
                    os.replace(str(tmp_dir), str(backup_path))
                except OSError as ex:
                    if getattr(ex, 'errno', None) == errno.EXDEV:
                        # Cross-device link: fallback to shutil.move (copy+remove)
                        move_method = "copied"
                        try:
                            if backup_path.exists():
                                self._safe_rmtree(backup_path)
                            shutil.move(str(tmp_dir), str(backup_path))
                        except Exception:
                            # If move fails, re-raise original exception to be handled
                            raise
                    else:
                        raise
                tmp_dir = None  # transferred ownership to final location

                # After successful atomic move, compute checksum and write metadata
                try:
                    checksum = compute_directory_sha256(backup_path)
                    total_size = get_directory_size(backup_path)
                    total_files = sum(len(files) for _, _, files in os.walk(backup_path))
                    meta = {
                        "completed_at": datetime.datetime.now().isoformat(),
                        "checksum": checksum,
                        "files": total_files,
                        "size_bytes": total_size,
                        "move_method": move_method
                    }
                    if description:
                        meta["description"] = description
                    meta_file = backup_path / ".backup_meta.json"
                    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
                except Exception as meta_err:
                    # Don't fail the backup if metadata write fails; log and continue
                    print_warning(f"Failed to write backup metadata: {meta_err}")

                print_success(f"Backup created successfully in {elapsed_time:.1f}s")
                print_info(f"Location: {backup_path}")

            finally:
                # Cleanup temp dir if something went wrong and it still exists
                if tmp_dir and tmp_dir.exists():
                    try:
                        self._safe_rmtree(tmp_dir)
                    except Exception:
                        pass
            
            # Cleanup old backups
            self._cleanup_old_backups()
            
            return backup_path
            
        except Exception as e:
            print_error(f"Failed to create backup: {e}")
            return None
    
    def list_backups(self) -> List[str]:
        """List all available backups with enhanced formatting"""
        backups = self._get_backup_list()
        
        if not backups:
            print_warning("No backups found.")
            return []
        
        print_header("Available Backups")
        
        for i, backup in enumerate(backups, 1):
            backup_path = Path(backup)
            backup_name = backup_path.name
            
            # Extract timestamp from backup name
            timestamp_str = backup_name.replace("backup_", "")
            try:
                timestamp = datetime.datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                
                # Calculate age
                age = datetime.datetime.now() - timestamp
                if age.days > 0:
                    age_str = f"{age.days} days ago"
                elif age.seconds > 3600:
                    age_str = f"{age.seconds // 3600} hours ago"
                elif age.seconds > 60:
                    age_str = f"{age.seconds // 60} minutes ago"
                else:
                    age_str = "Just now"
                
                # Get backup size
                backup_size = format_file_size(get_directory_size(backup_path))
                
                # Check for description
                desc_file = backup_path / ".backup_description"
                description = ""
                if desc_file.exists():
                    try:
                        description = f" - {desc_file.read_text(encoding='utf-8').strip()}"
                    except Exception:
                        pass
                
                print_colored(f"{i:2d}. ", Colors.CYAN, bold=True, end="")
                print_colored(f"{backup_name}", Colors.WHITE, bold=True)
                print_colored(f"    📅 {formatted_time} ({age_str})", Colors.BLUE, end="")
                print_colored(f" - {backup_size}{description}", Colors.MAGENTA)
                
            except ValueError:
                print_colored(f"{i:2d}. {backup_name}", Colors.WHITE)
        
        return backups
    
    def restore_backup(self, backup_choice: Optional[int] = None, skip_confirmation: bool = False) -> bool:
        """Restore a backup to the save directory"""
        backups = self._get_backup_list()
        
        if not backups:
            print_warning("No backups available to restore.")
            return False
        
        if backup_choice is None:
            self.list_backups()
            try:
                choice = input(f"\n{Colors.YELLOW}Enter backup number to restore (1-{len(backups)}) or 'q' to quit: {Colors.END}")
                if choice.lower() == 'q':
                    print_info("Restore cancelled.")
                    return False
                    
                choice = int(choice) - 1
                if choice < 0 or choice >= len(backups):
                    print_error("Invalid choice.")
                    return False
                backup_path = backups[choice]
            except (ValueError, IndexError):
                print_error("Invalid input.")
                return False
        else:
            if backup_choice < 1 or backup_choice > len(backups):
                print_error("Invalid backup number.")
                return False
            backup_path = backups[backup_choice - 1]
        
        backup_name = Path(backup_path).name
        
        # Show backup info
        print_header("Restore Backup")
        print_info(f"Selected backup: {backup_name}")
        
        # Check for description
        desc_file = Path(backup_path) / ".backup_description"
        if desc_file.exists():
            try:
                description = desc_file.read_text(encoding='utf-8').strip()
                print_info(f"Description: {description}")
            except Exception:
                pass
        
        # Confirm restoration (skip if requested)
        if not skip_confirmation:
            print_warning("This will overwrite your current save files!")
            confirm = input(f"\n{Colors.YELLOW}Are you sure you want to restore '{backup_name}'? (y/N): {Colors.END}")
            if confirm.lower() != 'y':
                print_info("Restoration cancelled.")
                return False
        
        try:
            # Create a backup of current state before restoring
            #print_info("Creating safety backup of current state...")
            #current_backup = self.create_backup("Pre-restore safety backup")
            
            # Remove current save files (except backup folder)
            print_info("Removing current save files...")
            for item in self.save_dir.iterdir():
                if item.name != "backups" and item != Path(__file__):
                    try:
                        if item.is_dir():
                            self._safe_rmtree(item)
                        else:
                            # Handle read-only files
                            if not os.access(item, os.W_OK):
                                os.chmod(item, 0o777)
                            item.unlink()
                    except PermissionError as e:
                        print_warning(f"Could not remove {item.name}: {e}")
                        print_info("Trying alternative removal method...")
                        try:
                            # Try using system command as fallback
                            if item.is_dir():
                                subprocess.run(['rmdir', '/s', '/q', str(item)], shell=True, check=False)
                            else:
                                subprocess.run(['del', '/f', '/q', str(item)], shell=True, check=False)
                        except Exception as fallback_error:
                            print_error(f"Failed to remove {item.name}: {fallback_error}")
                            return False
            
            # Copy backup contents to save directory
            print_info("Restoring backup files...")
            backup_path_obj = Path(backup_path)
            files_to_restore = sum(len(files) for _, _, files in os.walk(backup_path_obj))
            
            files_restored = 0
            for item in backup_path_obj.iterdir():
                if item.name == ".backup_description":
                    continue
                    
                dest = self.save_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest)
                    # Count files in directory
                    files_restored += sum(len(files) for _, _, files in os.walk(item))
                else:
                    shutil.copy2(item, dest)
                    files_restored += 1
                
                show_progress(files_restored, files_to_restore, "Restoring")
            
            print()  # New line after progress bar
            print_success(f"Backup '{backup_name}' restored successfully!")
            #if current_backup:
            #    print_info(f"Previous state backed up as: {current_backup.name}")
            return True
            
        except Exception as e:
            print_error(f"Failed to restore backup: {e}")
            return False
    
    def delete_backup(self, backup_choice: Optional[int] = None, skip_confirmation: bool = False) -> bool:
        """Delete a specific backup"""
        backups = self._get_backup_list()
        
        if not backups:
            print_warning("No backups available to delete.")
            return False
        
        if backup_choice is None:
            self.list_backups()
            try:
                choice = input(f"\n{Colors.YELLOW}Enter backup number to delete (1-{len(backups)}) or 'q' to quit: {Colors.END}")
                if choice.lower() == 'q':
                    print_info("Delete cancelled.")
                    return False
                    
                choice = int(choice) - 1
                if choice < 0 or choice >= len(backups):
                    print_error("Invalid choice.")
                    return False
                backup_path = backups[choice]
            except (ValueError, IndexError):
                print_error("Invalid input.")
                return False
        else:
            if backup_choice < 1 or backup_choice > len(backups):
                print_error("Invalid backup number.")
                return False
            backup_path = backups[backup_choice - 1]
        
        backup_name = Path(backup_path).name
        
        # Show backup info
        print_header("Delete Backup")
        print_warning(f"Selected backup: {backup_name}")
        
        # Confirm deletion (skip if requested)
        if not skip_confirmation:
            confirm = input(f"\n{Colors.RED}Are you sure you want to permanently delete '{backup_name}'? (y/N): {Colors.END}")
            if confirm.lower() != 'y':
                print_info("Deletion cancelled.")
                return False
        
        try:
            self._safe_rmtree(backup_path)
            print_success(f"Backup '{backup_name}' deleted successfully!")
            return True
        except Exception as e:
            print_error(f"Failed to delete backup: {e}")
            return False
    
    def cleanup_backups(self, keep_count: Optional[int] = None):
        """Manual cleanup of old backups"""
        if keep_count is None:
            keep_count = self.max_backups
            
        backups = self._get_backup_list()
        if len(backups) <= keep_count:
            print_info(f"Only {len(backups)} backup(s) found. No cleanup needed.")
            return
        
        backups_to_delete = backups[keep_count:]
        print_warning(f"Will delete {len(backups_to_delete)} old backup(s), keeping the {keep_count} most recent.")
        
        confirm = input(f"\n{Colors.YELLOW}Continue? (y/N): {Colors.END}")
        if confirm.lower() != 'y':
            print_info("Cleanup cancelled.")
            return
        
        for backup_path in backups_to_delete:
            try:
                self._safe_rmtree(backup_path)
                backup_name = Path(backup_path).name
                print_success(f"Deleted: {backup_name}")
            except Exception as e:
                print_error(f"Failed to delete {backup_path}: {e}")

def get_user_input_with_prompt(prompt: str, default: Optional[str] = None) -> str:
    """Get user input with colored prompt"""
    if default:
        full_prompt = f"{Colors.CYAN}{prompt} [{default}]: {Colors.END}"
    else:
        full_prompt = f"{Colors.CYAN}{prompt}: {Colors.END}"
    
    response = input(full_prompt).strip()
    return response if response else (default or "")

def open_config_in_notepad(config_path: Path):
    """Open the config file in Notepad"""
    try:
        print_info(f"Opening config file in Notepad: {config_path}")
        subprocess.Popen(['notepad.exe', str(config_path)])
        print_success("Config file opened in Notepad")
    except Exception as e:
        print_error(f"Failed to open config file in Notepad: {e}")

def monitor_config_file(config_path: Path, callback_func):
    """Monitor config file for changes and call callback when modified"""
    if not config_path.exists():
        return
    
    last_modified = config_path.stat().st_mtime
    
    def monitor_loop():
        nonlocal last_modified
        while True:
            try:
                if config_path.exists():
                    current_modified = config_path.stat().st_mtime
                    if current_modified != last_modified:
                        last_modified = current_modified
                        print_info("Config file changed - reloading...")
                        callback_func()
                time.sleep(1)  # Check every second
            except Exception:
                pass  # Ignore errors during monitoring
    
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()
    return monitor_thread

def main():
    parser = argparse.ArgumentParser(
        description="🎮 Save Game Backup Manager - Keep your saves safe!",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=""":
Examples:
  python backup.py                          # Interactive mode with game selection
  python backup.py --game skyrim            # Use configured game 'skyrim'
  python backup.py --backup                 # Quick backup (current dir or selected game)
  python backup.py --backup -d "Before boss fight"  # Backup with description
  python backup.py --list                   # List all backups
  python backup.py --restore 1              # Restore backup #1
  python backup.py --config                 # Manage game configurations
        """
    )
    
    parser.add_argument("--save-dir", help="Path to save directory (overrides game config)")
    parser.add_argument("--backup-dir", help="Path to backup directory (default: ./backups)")
    parser.add_argument("--max-backups", type=int, help="Maximum number of backups to keep")
    parser.add_argument("--game", help="Game ID from config file")
    parser.add_argument("--config", action="store_true", help="Manage game configurations")
    parser.add_argument("--backup", action="store_true", help="Create a backup")
    parser.add_argument("--skip-locked", action="store_true", help="Skip locked files instead of failing")
    parser.add_argument("--copy-retries", type=int, help="Number of copy retries for locked files")
    parser.add_argument("--retry-delay", type=float, help="Base delay (seconds) between retries")
    parser.add_argument("-d", "--description", help="Description for the backup")
    parser.add_argument("--restore", type=int, help="Restore backup by number")
    parser.add_argument("--list", action="store_true", help="List all backups")
    parser.add_argument("--delete", type=int, help="Delete backup by number")
    parser.add_argument("--cleanup", action="store_true", help="Clean up old backups")
    parser.add_argument("--keep", type=int, help="Number of backups to keep during cleanup")
    
    args = parser.parse_args()
    
    # Print welcome message
    print_header("🎮 Save Game Backup Manager")
    
    # Load config file
    config_path = Path(__file__).parent / "games_config.json"
    config = load_games_config(config_path)
    
    # Set up config file monitoring
    def reload_config():
        nonlocal config
        try:
            config = load_games_config(config_path)
        except Exception as e:
            print_error(f"Failed to reload config: {e}")
    
    # Start monitoring config file for changes
    monitor_thread = monitor_config_file(config_path, reload_config)
    
    # Handle config management
    if args.config:
        while True:
            print_header("Game Configuration Manager")
            print_colored("1. 📋 List games", Colors.BLUE)
            print_colored("2. ➕ Add game", Colors.GREEN)
            print_colored("3. ✏️  Edit game", Colors.YELLOW)
            print_colored("4. 🗑️  Remove game", Colors.RED)
            print_colored("5. � Open config in Notepad", Colors.MAGENTA)
            print_colored("6. �🚪 Back to main menu", Colors.WHITE)
            
            choice = input(f"\n{Colors.CYAN}Enter your choice (1-6): {Colors.END}").strip()
            
            if choice == "1":
                games = list_games(config)
                if games:
                    print_header("Configured Games")
                    for i, (game_id, game_info) in enumerate(games, 1):
                        name = game_info.get("name", game_id)
                        save_path = game_info.get("save_path", "Unknown")
                        backup_path = game_info.get("backup_path", "")
                        description = game_info.get("description", "")
                        
                        print_colored(f"{i:2d}. {name} (ID: {game_id})", Colors.WHITE, bold=True)
                        print_colored(f"    📁 Save: {save_path}", Colors.BLUE)
                        if backup_path:
                            print_colored(f"    💾 Backup: {backup_path}", Colors.GREEN)
                        if description:
                            print_colored(f"    📝 {description}", Colors.MAGENTA)
                else:
                    print_warning("No games configured.")
            elif choice == "2":
                add_game_to_config(config_path, config)
                config = load_games_config(config_path)  # Reload
            elif choice == "3":
                edit_game_config(config_path, config)
                config = load_games_config(config_path)  # Reload
            elif choice == "4":
                remove_game_from_config(config_path, config)
                config = load_games_config(config_path)  # Reload
            elif choice == "5":
                open_config_in_notepad(config_path)
                print_info("Tip: The config file will be automatically reloaded when you save changes in Notepad")
            elif choice == "6":
                break
            else:
                print_error("Invalid choice. Please enter 1-6.")
            
            if choice in ["1", "2", "3", "4", "5"]:
                input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.END}")
    
    # Determine save directory and game info
    save_dir = args.save_dir
    backup_dir = args.backup_dir
    game_name = None
    max_backups = args.max_backups or config.get("settings", {}).get("default_max_backups", 10)
    
    if args.game:
        # Use specified game from config
        game_info = config.get("games", {}).get(args.game)
        if game_info:
            save_dir = expand_path(game_info["save_path"])
            game_name = game_info["name"]
            # Use backup path from config if not specified in command line
            if not backup_dir and "backup_path" in game_info and game_info["backup_path"]:
                backup_dir = expand_path(game_info["backup_path"])
            print_success(f"Using configured game: {game_name}")
        else:
            print_error(f"Game '{args.game}' not found in config.")
            return
    elif not save_dir and not args.config:
        # Interactive game selection if no save dir specified
        selected = select_game(config)
        if selected:
            game_id, game_info = selected
            save_dir = expand_path(game_info["save_path"])
            game_name = game_info["name"]
            # Use backup path from config if not specified in command line
            if not backup_dir and "backup_path" in game_info and game_info["backup_path"]:
                backup_dir = expand_path(game_info["backup_path"])
            print_success(f"Selected game: {game_name}")
        else:
            print_info("No game selected, using current directory.")
    
    # If no backup_dir set yet, try default from settings
    if not backup_dir:
        default_backup_path = config.get("settings", {}).get("default_backup_path")
        if default_backup_path:
            backup_dir = expand_path(default_backup_path)

    # Ensure we standardize to using './backups' (plural) as the default backup
    # directory next to the script if none was provided.
    try:
        script_dir = Path(__file__).parent
        if not backup_dir:
            default_backup_dir = script_dir / "backups"
            # If the default doesn't exist yet, create it (non-fatal)
            default_backup_dir.mkdir(parents=True, exist_ok=True)
            backup_dir = str(default_backup_dir)
            print_info(f"Using default backups directory: {default_backup_dir}")
    except Exception as e:
        # Non-fatal, just warn
        print_warning(f"Failed to ensure default './backups' directory: {e}")
    
    # Validate save directory exists
    if save_dir and not os.path.exists(save_dir):
        print_error(f"Save directory does not exist: {save_dir}")
        return
    
    # Determine skip_locked_files and retry settings from args or config
    settings = config.get("settings", {})
    skip_locked = args.skip_locked or settings.get("skip_locked_files", False)
    copy_retries = args.copy_retries if args.copy_retries is not None else settings.get("copy_retries", 3)
    retry_delay = args.retry_delay if args.retry_delay is not None else settings.get("retry_delay", 0.5)

    # Initialize backup manager
    try:
        manager = SaveBackupManager(save_dir, backup_dir, max_backups, game_name,
                                    skip_locked_files=skip_locked,
                                    retries=copy_retries,
                                    retry_delay=retry_delay)
    except Exception as e:
        print_error(f"Failed to initialize backup manager: {e}")
        sys.exit(1)
    
    # Handle command line arguments
    try:
        if args.backup:
            manager.create_backup(args.description)
        elif args.restore:
            manager.restore_backup(args.restore)
        elif args.list:
            manager.list_backups()
        elif args.delete:
            manager.delete_backup(args.delete)
        elif args.cleanup:
            manager.cleanup_backups(args.keep)
        elif not args.config:
            # Interactive mode
            while True:
                print_header("Main Menu")
                if game_name:
                    print_colored(f"🎮 Current Game: ", Colors.CYAN, bold=True, end="")
                    print_colored(f"{game_name}\n", Colors.WHITE, bold=True)
                print_colored("1. 💾 Create backup", Colors.GREEN)
                print_colored("2. 📋 List backups", Colors.BLUE)
                print_colored("3. 🔄 Restore backup", Colors.YELLOW)
                print_colored("4. 🗑️ Delete backup", Colors.RED)
                print_colored("5. 🧹 Cleanup old backups", Colors.MAGENTA)
                print_colored("6. 🎮 Switch game", Colors.CYAN)
                print_colored("7. ⚙️ Manage games config", Colors.WHITE)
                print_colored("8. 🚪 Exit", Colors.WHITE)
                
                try:
                    choice = input(f"\n{Colors.CYAN}Enter your choice (1-8): {Colors.END}").strip()
                    
                    if choice == "1":
                        description = get_user_input_with_prompt("Backup description (optional)")
                        manager.create_backup(description if description else None)
                    elif choice == "2":
                        manager.list_backups()
                    elif choice == "3":
                        manager.restore_backup()
                    elif choice == "4":
                        manager.delete_backup()
                    elif choice == "5":
                        keep_count = get_user_input_with_prompt("Number of backups to keep", str(manager.max_backups))
                        try:
                            keep_count = int(keep_count)
                            manager.cleanup_backups(keep_count)
                        except ValueError:
                            print_error("Invalid number entered.")
                    elif choice == "6":
                        selected = select_game(config)
                        if selected:
                            game_id, game_info = selected
                            new_save_dir = expand_path(game_info["save_path"])
                            new_game_name = game_info["name"]
                            # Determine new backup directory
                            new_backup_dir = args.backup_dir
                            if not new_backup_dir and "backup_path" in game_info and game_info["backup_path"]:
                                new_backup_dir = expand_path(game_info["backup_path"])
                            elif not new_backup_dir:
                                default_backup_path = config.get("settings", {}).get("default_backup_path")
                                if default_backup_path:
                                    new_backup_dir = expand_path(default_backup_path)
                            
                            if os.path.exists(new_save_dir):
                                manager = SaveBackupManager(new_save_dir, new_backup_dir, max_backups, new_game_name)
                                print_success(f"Switched to: {new_game_name}")
                            else:
                                print_error(f"Save directory does not exist: {new_save_dir}")
                    elif choice == "7":
                        # Jump to config management
                        while True:
                            print_header("Game Configuration Manager")
                            print_colored("1. 📋 List games", Colors.BLUE)
                            print_colored("2. ➕ Add game", Colors.GREEN)
                            print_colored("3. ✏️  Edit game", Colors.YELLOW)
                            print_colored("4. 🗑️  Remove game", Colors.RED)
                            print_colored("5. 📝 Open config in Notepad", Colors.MAGENTA)
                            print_colored("6. 🚪 Back to main menu", Colors.WHITE)
                            
                            config_choice = input(f"\n{Colors.CYAN}Enter your choice (1-6): {Colors.END}").strip()
                            
                            if config_choice == "1":
                                games = list_games(config)
                                if games:
                                    print_header("Configured Games")
                                    for i, (game_id, game_info) in enumerate(games, 1):
                                        name = game_info.get("name", game_id)
                                        save_path = game_info.get("save_path", "Unknown")
                                        backup_path = game_info.get("backup_path", "")
                                        description = game_info.get("description", "")
                                        
                                        print_colored(f"{i:2d}. {name} (ID: {game_id})", Colors.WHITE, bold=True)
                                        print_colored(f"    📁 Save: {save_path}", Colors.BLUE)
                                        if backup_path:
                                            print_colored(f"    💾 Backup: {backup_path}", Colors.GREEN)
                                        if description:
                                            print_colored(f"    📝 {description}", Colors.MAGENTA)
                                else:
                                    print_warning("No games configured.")
                            elif config_choice == "2":
                                add_game_to_config(config_path, config)
                                config = load_games_config(config_path)  # Reload
                            elif config_choice == "3":
                                edit_game_config(config_path, config)
                                config = load_games_config(config_path)  # Reload
                            elif config_choice == "4":
                                remove_game_from_config(config_path, config)
                                config = load_games_config(config_path)  # Reload
                            elif config_choice == "5":
                                open_config_in_notepad(config_path)
                                print_info("Tip: The config file will be automatically reloaded when you save changes in Notepad")
                            elif config_choice == "6":
                                break
                            else:
                                print_error("Invalid choice. Please enter 1-6.")
                            
                            if config_choice in ["1", "2", "3", "4", "5"]:
                                input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.END}")
                    elif choice == "8":
                        print_success("Thanks for using Save Game Backup Manager! 👋")
                        break
                    else:
                        print_error("Invalid choice. Please enter 1-8.")
                        
                except KeyboardInterrupt:
                    print_success("\nThanks for using Save Game Backup Manager! 👋")
                    break
                except Exception as e:
                    print_error(f"An error occurred: {e}")
                
                # Pause before showing menu again
                if choice not in ["7", "8"]:
                    input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.END}")
                
    except KeyboardInterrupt:
        print_success("\nThanks for using Save Game Backup Manager! 👋")
    except Exception as e:
        print_error(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()