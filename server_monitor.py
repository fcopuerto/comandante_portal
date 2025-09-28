#!/usr/bin/env python3
"""
CobaltaX Server Monitor - Professional GUI Application
Monitor and manage Ubuntu servers on your local network.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
from typing import Dict, List, Any
import sys
import os
import locale
import json
from audit_logger import log_event, set_session_user, get_session_user, AUDIT_LOG_PATH

# --- New import (safe) for Telethon user-session fallback ---
try:
    from telethon import TelegramClient as TLUserClient  # user session fallback
except ImportError:
    TLUserClient = None

# Import local modules
try:
    from config import SERVERS, PING_TIMEOUT, REFRESH_INTERVAL, SSH_TIMEOUT, WINDOW_TITLE, WINDOW_WIDTH, WINDOW_HEIGHT, DEFAULT_LANGUAGE, TELEGRAM_ENABLED, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DEFAULT_THEME
    from server_utils import ServerMonitor, SSHManager, async_operation, TelegramClient
    from language_manager import get_language_manager, _
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Make sure all required files are in the same directory.")
    sys.exit(1)

# Attempt to load (and migrate) secure encrypted config store. If successful,
# it will replace the in-memory SERVERS list contents.
try:
    from secure_config_store import init_db as _secure_init_db, load_servers as _secure_load_servers, get_user_password as _secure_get_user_password
    _secure_init_db(migrate=True)
    _db_servers = _secure_load_servers()
    if _db_servers:
        # mutate SERVERS list in-place so all existing references remain valid
        try:
            SERVERS.clear(); SERVERS.extend(_db_servers)
            print(f"Loaded {len(SERVERS)} server definitions from encrypted store.")
        except Exception:
            pass
except Exception as _e:
    print(f"Secure config store not used: {_e}")


def detect_os_language() -> str:
    """Detect OS UI language and map to supported codes: 'es', 'en', 'ca'.
    Fallback to Spanish ('es') if detection is unknown.
    """
    try:
        # locale.getdefaultlocale() is deprecated in newer Python versions; prefer getlocale/getpreferredencoding
        lang, _ = locale.getlocale()
        if not lang:
            # Try alternative
            lang = locale.getdefaultlocale()[0] if hasattr(
                locale, 'getdefaultlocale') else None
    except Exception:
        lang = None

    code = (lang or '').lower()
    if code.startswith('es'):
        return 'es'
    if code.startswith('ca'):
        return 'ca'
    if code.startswith('en'):
        return 'en'

    # Default to Spanish as requested
    return 'es'


class ServerMonitorGUI:
    """Main GUI application for server monitoring."""

    def __init__(self):
        # Initialize language manager and set language based on OS, fallback 'es'
        self.lang_manager = get_language_manager()
        detected_lang = detect_os_language()
        self.lang_manager.set_language(detected_lang)

        self.root = tk.Tk()
        self.setup_window()
        # Theme system init
        self.current_theme = DEFAULT_THEME if 'DEFAULT_THEME' in globals() else 'modern'
        self._style = ttk.Style()
        self.apply_theme(self.current_theme)

        # Initialize monitoring components
        self.server_monitor = ServerMonitor(timeout=PING_TIMEOUT)
        self.ssh_manager = SSHManager(timeout=SSH_TIMEOUT)

        # Server status storage
        self.server_status = {}
        self.server_widgets = {}
        # Dependency map: parent_ip -> list of child server dicts
        self.dependency_children = {}
        self.server_by_ip = {s['ip']: s for s in SERVERS}
        self.build_dependency_index()
        # Track which parent groups are expanded (default: all)
        self.expanded_parents = set(self.dependency_children.keys())
        # Layout density mode (compact = smaller boxes)
        self.compact_mode = False
        # Ultra compact mode (even smaller + hides some labels)
        self.ultra_compact_mode = False
        # Option to hide action buttons for maximum density
        self.hide_buttons_mode = False
        # Condensed resources mode to shrink ESXi / resource strings
        self.condensed_resources_mode = True
        # View mode: 'card' (default) or future 'list'
        self.view_mode = 'card'
        self.server_rows = {}

        # Auto-refresh control
        self.auto_refresh = True
        self.refresh_job = None

        # Store widget references for language updates
        self.translatable_widgets = {}

        # Authentication gate (supports multi-user)
        from config import AUTH_ENABLED, AUTH_USERNAME, AUTH_PASSWORD, AUTH_USERS, AUTH_PASSWORDS
        if AUTH_ENABLED:
            if not self._run_login_dialog(AUTH_USERNAME, AUTH_PASSWORD, AUTH_USERS, AUTH_PASSWORDS):
                self.root.destroy()
                sys.exit(0)

        # Setup GUI components after successful auth (or if auth disabled)
        self.create_widgets()
        self.setup_bindings()

        # Start initial status check
        self.refresh_all_servers()
        self.schedule_auto_refresh()

    def _run_login_dialog(self, legacy_user: str, legacy_pass: str, users: List[str], user_passwords: Dict[str, str]) -> bool:
        """Modal login dialog supporting multiple users and per-user passwords.

        Resolution order for password:
          1. Per-user password (COBALTAX_PASS_<NAME>) if defined
          2. Legacy single-user password if user matches legacy_user
          3. Global AUTH_PASSWORD / legacy_pass fallback
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("Login")
        dialog.geometry("320x170")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.transient(self.root)

        # Determine available users
        effective_users = users[:] if users else (
            [] if not legacy_user else [legacy_user])
        if legacy_user and legacy_user not in effective_users:
            effective_users.append(legacy_user)
        effective_users = [u for u in effective_users if u]

        multi_mode = len(effective_users) > 1
        selected_user = tk.StringVar(
            value=effective_users[0] if effective_users else '')
        p_var = tk.StringVar()
        status_var = tk.StringVar(value="Enter credentials")

        ttk.Label(dialog, text="User:").pack(anchor='w', padx=12, pady=(12, 2))
        if multi_mode:
            user_combo = ttk.Combobox(
                dialog, textvariable=selected_user, values=effective_users, state='readonly')
            user_combo.pack(fill='x', padx=12)
            focus_widget = user_combo
        else:
            user_entry = ttk.Entry(dialog, textvariable=selected_user)
            user_entry.pack(fill='x', padx=12)
            focus_widget = user_entry

        ttk.Label(dialog, text="Password:").pack(
            anchor='w', padx=12, pady=(10, 2))
        p_entry = ttk.Entry(dialog, textvariable=p_var, show='*')
        p_entry.pack(fill='x', padx=12)
        status_lbl = ttk.Label(
            dialog, textvariable=status_var, foreground='grey')
        status_lbl.pack(anchor='w', padx=12, pady=(6, 4))

        result = {'ok': False}

        def resolve_expected(user: str) -> str:
            # Prefer encrypted store if available
            expected_secure = None
            try:
                expected_secure = _secure_get_user_password(user)  # type: ignore
            except Exception:
                expected_secure = None
            if expected_secure:
                return expected_secure
            if user in user_passwords:
                return user_passwords[user]
            if legacy_user and user == legacy_user and legacy_pass:
                return legacy_pass
            return legacy_pass  # fallback to global (may be None)

        def attempt(event=None):
            user = (selected_user.get() or '').strip()
            pw = p_var.get()
            expected = resolve_expected(user)
            if user and expected and pw == expected:
                result['ok'] = True
                set_session_user(user)
                log_event('login_success', {'user': user})
                dialog.destroy()
            else:
                status_var.set("Invalid credentials")
                status_lbl.config(foreground='red')
                p_var.set("")
                p_entry.focus_set()
                if user:
                    log_event('login_failed', {'user': user})

        def cancel():
            dialog.destroy()
            log_event('login_cancelled', {'user': selected_user.get()})

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill='x', padx=12, pady=(4, 8))
        ttk.Button(btn_frame, text="Login",
                   command=attempt).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Cancel", command=cancel).pack(
            side=tk.RIGHT, padx=(0, 6))

        dialog.bind('<Return>', attempt)
        focus_widget.focus_set()
        self.root.wait_window(dialog)
        return result['ok']

    def setup_window(self):
        """Configure the main window."""
        self.root.title(_('app_title'))
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(True, True)

        # Set minimum size
        self.root.minsize(500, 300)

        # Configure window icon (if available)
        try:
            # You can add an icon file here
            # self.root.iconbitmap('icon.ico')
            pass
        except:
            pass

        # Center window on screen
        self.center_window()

    def center_window(self):
        """Center the window on the screen."""
        self.root.update_idletasks()

        # Get screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        # Calculate position
        x = (screen_width - WINDOW_WIDTH) // 2
        y = (screen_height - WINDOW_HEIGHT) // 2

        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")

    def create_widgets(self):
        """Create and layout all GUI widgets."""
        # Create menu bar
        self.create_menu_bar()

        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure grid weights for responsiveness
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=2)  # servers area
        main_frame.rowconfigure(2, weight=1)  # telegram area now also expands

        # Title and controls frame
        header_frame = ttk.Frame(main_frame)
        header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        header_frame.columnconfigure(1, weight=1)

        # Title
        self.title_label = ttk.Label(
            header_frame,
            text=_('server_monitor'),
            font=('Arial', 16, 'bold')
        )
        self.title_label.grid(row=0, column=0, sticky=tk.W)
        self.translatable_widgets['title_label'] = self.title_label

        # Control buttons frame
        controls_frame = ttk.Frame(header_frame)
        controls_frame.grid(row=0, column=2, sticky=tk.E)

        # Language selector
        lang_frame = ttk.Frame(controls_frame)
        lang_frame.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(lang_frame, text=_('language') + ':').pack(side=tk.LEFT)

        self.language_var = tk.StringVar(
            value=self.lang_manager.current_language)
        self.language_combo = ttk.Combobox(
            lang_frame,
            textvariable=self.language_var,
            values=[lang[0]
                    for lang in self.lang_manager.get_available_languages()],
            state='readonly',
            width=5
        )
        self.language_combo.pack(side=tk.LEFT, padx=(5, 0))
        self.language_combo.bind(
            '<<ComboboxSelected>>', self.on_language_change)

        # Refresh button
        self.refresh_btn = ttk.Button(
            controls_frame,
            text=_('refresh'),
            command=self.refresh_all_servers
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=(0, 5))
        self.translatable_widgets['refresh_btn'] = self.refresh_btn

        # Auto-refresh toggle
        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.auto_refresh_cb = ttk.Checkbutton(
            controls_frame,
            text=_('auto_refresh'),
            variable=self.auto_refresh_var,
            command=self.toggle_auto_refresh
        )
        self.auto_refresh_cb.pack(side=tk.LEFT)
        self.translatable_widgets['auto_refresh_cb'] = self.auto_refresh_cb

        # Servers frame with scrollbar
        self.servers_frame = ttk.LabelFrame(
            main_frame, text=_('servers'), padding="5")
        self.servers_frame.grid(
            row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.servers_frame.columnconfigure(0, weight=1)
        self.servers_frame.rowconfigure(0, weight=1)
        self.translatable_widgets['servers_frame'] = self.servers_frame

        # Create scrollable canvas
        self.canvas = tk.Canvas(self.servers_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            self.servers_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window(
            (0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        # --- Added aliases required by switch_view_mode ---
        self.card_canvas = self.canvas
        self.card_scrollbar = scrollbar

        # Configure scrollable frame
        self.scrollable_frame.columnconfigure(0, weight=1)

        # Create server widgets
        self.create_server_widgets()
        # Initial layout distribution across columns
        self.update_server_grid(force=True)

        # Telegram panel (optional)
        self.telegram_frame = ttk.LabelFrame(
            main_frame, text="Telegram", padding="5")
        self.telegram_text = None
        self.telegram_auto_job = None
        self.telegram_filter_var = tk.StringVar()
        self.telegram_send_var = tk.StringVar()
        self.telegram_auto_var = tk.BooleanVar(value=True)
        if TELEGRAM_ENABLED:
            from config import TELEGRAM_DEFAULT_LIMIT, TELEGRAM_REFRESH_INTERVAL
            self.telegram_frame.grid(
                row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            self.telegram_frame.columnconfigure(0, weight=1)
            self.telegram_frame.rowconfigure(
                1, weight=1)  # make scrolled text expand
            controls = ttk.Frame(self.telegram_frame)
            controls.grid(row=0, column=0, sticky=(tk.W, tk.E))
            # Limit
            ttk.Label(controls, text="Limit:").pack(side=tk.LEFT)
            self.tel_limit_var = tk.IntVar(value=TELEGRAM_DEFAULT_LIMIT)
            limit_entry = ttk.Entry(
                controls, textvariable=self.tel_limit_var, width=5)
            limit_entry.pack(side=tk.LEFT, padx=(2, 6))
            # Filter
            ttk.Label(controls, text="Filter:").pack(side=tk.LEFT)
            filter_entry = ttk.Entry(
                controls, textvariable=self.telegram_filter_var, width=12)
            filter_entry.pack(side=tk.LEFT, padx=(2, 6))
            filter_entry.bind(
                '<Return>', lambda e: self.load_telegram_messages())
            # Buttons
            ttk.Button(controls, text="Load",
                       command=self.load_telegram_messages).pack(side=tk.LEFT)
            ttk.Button(controls, text="Full", command=self.load_telegram_full_history).pack(
                side=tk.LEFT, padx=(4, 0))
            ttk.Button(controls, text="Test", command=self.send_telegram_test).pack(
                side=tk.LEFT, padx=(4, 0))
            # Auto refresh
            ttk.Checkbutton(controls, text="Auto", variable=self.telegram_auto_var,
                            command=lambda: self.schedule_telegram_auto()).pack(side=tk.LEFT, padx=(8, 0))
            self.telegram_interval = TELEGRAM_REFRESH_INTERVAL
            # Status label
            self.telegram_status = ttk.Label(
                controls, text="idle", foreground='grey')
            self.telegram_status.pack(side=tk.LEFT, padx=(8, 0))
            # Message list
            self.telegram_text = scrolledtext.ScrolledText(
                self.telegram_frame, height=14, wrap=tk.WORD, font=('Courier', 10))
            self.telegram_text.grid(
                row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            # Send bar
            send_frame = ttk.Frame(self.telegram_frame)
            send_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(4, 0))
            send_entry = ttk.Entry(
                send_frame, textvariable=self.telegram_send_var)
            send_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            send_entry.bind('<Return>', lambda e: self.send_custom_telegram())
            ttk.Button(send_frame, text="Send", command=self.send_custom_telegram).pack(
                side=tk.LEFT, padx=(4, 0))
            # Initial load + schedule
            self.load_telegram_messages()
            self.schedule_telegram_auto()
        else:
            self.telegram_frame.grid(row=2, column=0, sticky=(tk.W, tk.E))
            ttk.Label(self.telegram_frame, text="Telegram disabled (missing TELEGRAM_* env vars)").grid(
                row=0, column=0, sticky=tk.W)

        # Status bar
        self.status_bar = ttk.Label(
            main_frame,
            text=_('ready'),
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        self.status_bar.grid(
            row=3, column=0, sticky=(tk.W, tk.E), pady=(10, 0))

        # Bind mouse wheel to canvas
        self.bind_mousewheel()
        # Track previous width for responsive reflow
        self._prev_width_class = None
        self.root.bind('<Configure>', self.on_window_resize)

    # --- Theme System ---
    THEMES: Dict[str, Dict[str, str]] = {
        'modern': {
            'bg': '#FFFFFF', 'fg': '#111827', 'panel_bg': '#F5F5F5',
            'primary': '#2563EB', 'primary_active': '#1D4ED8',
            'secondary': '#047857', 'secondary_active': '#065F46',
            'danger': '#DC2626', 'danger_active': '#B91C1C',
            'muted': '#4B5563', 'muted_text': '#9CA3AF'
        },
        'retro_green': {
            'bg': '#000000', 'fg': '#00FF66', 'panel_bg': '#002B14',
            'primary': '#00FF66', 'primary_active': '#00CC52',
            'secondary': '#00CC52', 'secondary_active': '#009940',
            'danger': '#FF3366', 'danger_active': '#CC0044',
            'muted': '#013319', 'muted_text': '#008844'
        },
        'retro_amber': {
            'bg': '#000000', 'fg': '#FFB000', 'panel_bg': '#332200',
            'primary': '#FFB000', 'primary_active': '#E69500',
            'secondary': '#FFCC40', 'secondary_active': '#E6B830',
            'danger': '#FF5E5E', 'danger_active': '#CC3232',
            'muted': '#5C4100', 'muted_text': '#AA7711'
        },
        'retro_gray': {
            'bg': '#111111', 'fg': '#DDDDDD', 'panel_bg': '#1E1E1E',
            'primary': '#AAAAAA', 'primary_active': '#888888',
            'secondary': '#CCCCCC', 'secondary_active': '#AAAAAA',
            'danger': '#FF5555', 'danger_active': '#CC3030',
            'muted': '#333333', 'muted_text': '#888888'
        },
        'norton_commander': {
            # Classic DOS blue style
            'bg': '#0000A8',          # base blue background
            'fg': '#FFFFFF',          # white foreground
            'panel_bg': '#000090',    # slightly darker panels
            'primary': '#FFD700',     # gold/yellow for primary actions
            'primary_active': '#FFC300',
            'secondary': '#87CEFA',   # light sky blue
            'secondary_active': '#5FB4E8',
            'danger': '#FF5555',
            'danger_active': '#CC3030',
            'muted': '#003070',
            'muted_text': '#B0C4DE'
        }
    }

    def apply_theme(self, theme_name: str):
        t = self.THEMES.get(theme_name, self.THEMES['modern'])
        style = self._style
        try:
            if style.theme_use() not in ("clam", "alt", "default", "classic"):
                style.theme_use('clam')
        except Exception:
            pass

        retro = theme_name.startswith('retro')
        base_font = ('Courier New', 10) if retro else ('Arial', 10)
        header_font = ('Courier New', 11, 'bold') if retro else (
            'Arial', 11, 'bold')
        title_font = ('Courier New', 16, 'bold') if retro else (
            'Arial', 16, 'bold')

        # Root
        try:
            self.root.configure(bg=t['bg'])
        except Exception:
            pass

        # Generic
        style.configure('TFrame', background=t['bg'])
        style.configure(
            'TLabel', background=t['bg'], foreground=t['fg'], font=base_font)
        style.configure('TLabelframe', background=t['bg'], foreground=t['fg'])
        style.configure('TLabelframe.Label',
                        background=t['bg'], foreground=t['fg'])
        style.configure('Server.TLabelframe',
                        background=t['panel_bg'], foreground=t['fg'])
        style.configure('Server.TLabelframe.Label',
                        background=t['panel_bg'], foreground=t['fg'], font=header_font)

        # Buttons
        style.configure('TButton', padding=6, font=base_font,
                        background=t['panel_bg'], foreground=t['fg'])
        style.map('TButton', background=[('active', t['secondary_active'])])
        style.configure('Primary.TButton',
                        background=t['primary'], foreground=t['bg'])
        style.map('Primary.TButton', background=[('active', t['primary_active']), ('disabled', t['muted'])],
                  foreground=[('disabled', t['muted_text'])])
        style.configure('Action.TButton',
                        background=t['secondary'], foreground=t['bg'])
        style.map('Action.TButton', background=[('active', t['secondary_active']), ('disabled', t['muted'])],
                  foreground=[('disabled', t['muted_text'])])
        style.configure('Danger.TButton',
                        background=t['danger'], foreground=t['bg'])
        style.map('Danger.TButton', background=[('active', t['danger_active']), ('disabled', t['muted'])],
                  foreground=[('disabled', t['muted_text'])])

        # Existing widgets adjustments
        if hasattr(self, 'title_label'):
            self.title_label.configure(
                font=title_font, background=t['bg'], foreground=t['fg'])
        if hasattr(self, 'server_widgets'):
            for w in self.server_widgets.values():
                try:
                    w['frame'].configure(style='Server.TLabelframe')
                except Exception:
                    pass
        if hasattr(self, 'telegram_text') and self.telegram_text is not None:
            if retro:
                self.telegram_text.configure(
                    background=t['bg'], foreground=t['fg'], insertbackground=t['fg'])
            else:
                self.telegram_text.configure(
                    background='#FFFFFF', foreground='#000000', insertbackground='#000000')

        # List (Treeview) styling if active
        if hasattr(self, 'list_tree') and self.list_tree is not None:
            try:
                row_h = 18 if getattr(self, 'compact_mode', False) else 20
                style.configure('Treeview',
                                background=t['panel_bg'],
                                fieldbackground=t['panel_bg'],
                                foreground=t['fg'],
                                rowheight=row_h,
                                font=base_font)
                style.configure('Treeview.Heading',
                                background=t['primary'],
                                foreground=t['bg'],
                                font=header_font)
            except Exception:
                pass

    # --- Added: status bar updater (restored) ---
    def update_status_bar(self, text: str):
        """Safely update status bar text."""
        self._last_status = text
        if hasattr(self, 'status_bar'):
            try:
                self.status_bar.config(text=text)
            except Exception:
                pass

    def change_theme(self, theme: str):
        """Switch theme and re-style UI."""
        if theme not in self.THEMES:
            messagebox.showwarning('Theme', f"Unknown theme: {theme}")
            return
        self.current_theme = theme
        self.apply_theme(theme)
        self.update_status_bar(f"Theme changed to {theme}")
        self.update_server_grid(force=True)

    def create_menu_bar(self):
        """Create the application menu bar."""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # Settings menu
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=_('settings'), menu=settings_menu)

        # Theme submenu
        theme_menu = tk.Menu(settings_menu, tearoff=0)
        settings_menu.add_cascade(label='Theme', menu=theme_menu)
        for tname in self.THEMES.keys():
            theme_menu.add_command(label=tname.replace('_', ' ').title(),
                                   command=lambda n=tname: self.change_theme(n))

        # View / layout submenu
        layout_menu = tk.Menu(settings_menu, tearoff=0)
        settings_menu.add_cascade(label='Layout', menu=layout_menu)
        self.compact_mode_var = tk.BooleanVar(value=self.compact_mode)
        layout_menu.add_checkbutton(
            label='Compact Mode', onvalue=True, offvalue=False,
            variable=self.compact_mode_var, command=self.toggle_compact_mode)
        self.ultra_compact_mode_var = tk.BooleanVar(
            value=self.ultra_compact_mode)
        layout_menu.add_checkbutton(
            label='Ultra Compact Mode', onvalue=True, offvalue=False,
            variable=self.ultra_compact_mode_var, command=self.toggle_ultra_compact_mode)
        self.hide_buttons_var = tk.BooleanVar(value=self.hide_buttons_mode)
        layout_menu.add_checkbutton(
            label='Hide Action Buttons', onvalue=True, offvalue=False,
            variable=self.hide_buttons_var, command=self.toggle_hide_buttons_mode)
        self.condensed_resources_var = tk.BooleanVar(
            value=self.condensed_resources_mode)
        layout_menu.add_checkbutton(
            label='Condensed Resources', onvalue=True, offvalue=False,
            variable=self.condensed_resources_var, command=self.toggle_condensed_resources_mode)
        # View mode submenu (ensure only once)
        view_menu = tk.Menu(settings_menu, tearoff=0)
        settings_menu.add_cascade(label='View Mode', menu=view_menu)
        self.view_mode_var = tk.StringVar(value=self.view_mode)
        view_menu.add_radiobutton(label='Card Grid', value='card', variable=self.view_mode_var,
                                  command=lambda: self.switch_view_mode('card'))
        view_menu.add_radiobutton(label='List Table', value='list', variable=self.view_mode_var,
                                  command=lambda: self.switch_view_mode('list'))

        # Language submenu
        language_menu = tk.Menu(settings_menu, tearoff=0)
        settings_menu.add_cascade(label=_('language'), menu=language_menu)

        # Add language options
        for lang_code, lang_name in self.lang_manager.get_available_languages():
            language_menu.add_command(
                label=lang_name,
                command=lambda code=lang_code: self.change_language(code)
            )
        # Admin-only: Audit log viewer
        try:
            from config import ADMIN_USERS
        except Exception:
            ADMIN_USERS = []
        current_user = get_session_user()
        if current_user and current_user in ADMIN_USERS:
            audit_menu = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label='Audit', menu=audit_menu)
            audit_menu.add_command(
                label='View Audit Log', command=self.view_audit_log)
            self.translatable_widgets['audit_menu'] = audit_menu

        self.translatable_widgets['menubar'] = menubar
        self.translatable_widgets['settings_menu'] = settings_menu
        self.translatable_widgets['language_menu'] = language_menu
        self.translatable_widgets['theme_menu'] = theme_menu
        self.translatable_widgets['layout_menu'] = layout_menu
        self.translatable_widgets['view_menu'] = view_menu

    def view_audit_log(self):
        """Open a window displaying the audit log in a table (admin only)."""
        try:
            from config import ADMIN_USERS
        except Exception:
            ADMIN_USERS = []
        user = get_session_user()
        if not (user and user in ADMIN_USERS):
            messagebox.showerror(
                'Audit', 'You are not authorized to view the audit log.')
            log_event('audit_view_denied', {'user': user})
            return

        win = tk.Toplevel(self.root)
        win.title('Audit Log')
        win.geometry('980x520')
        win.minsize(800, 400)

        container = ttk.Frame(win, padding=6)
        container.pack(fill='both', expand=True)

        # Filters
        filter_frame = ttk.Frame(container)
        filter_frame.pack(fill='x', pady=(0, 4))
        ttk.Label(filter_frame, text='Event:').pack(side='left')
        event_filter = ttk.Entry(filter_frame, width=18)
        event_filter.pack(side='left', padx=(4, 10))
        ttk.Label(filter_frame, text='User:').pack(side='left')
        user_filter = ttk.Entry(filter_frame, width=14)
        user_filter.pack(side='left', padx=(4, 10))
        ttk.Label(filter_frame, text='Contains:').pack(side='left')
        text_filter = ttk.Entry(filter_frame, width=24)
        text_filter.pack(side='left', padx=(4, 10))
        limit_var = tk.IntVar(value=1000)
        ttk.Label(filter_frame, text='Limit:').pack(side='left')
        ttk.Entry(filter_frame, textvariable=limit_var,
                  width=6).pack(side='left', padx=(4, 10))
        tail_only_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(filter_frame, text='Tail Mode',
                        variable=tail_only_var).pack(side='left')

        # Table + details split
        paned = ttk.Panedwindow(container, orient='vertical')
        paned.pack(fill='both', expand=True)

        table_frame = ttk.Frame(paned)
        detail_frame = ttk.Frame(paned)
        paned.add(table_frame, weight=3)
        paned.add(detail_frame, weight=2)

        columns = ('ts', 'user', 'event', 'server', 'ip', 'success')
        tree = ttk.Treeview(table_frame, columns=columns, show='headings')
        for col, w in [('ts', 150), ('user', 90), ('event', 160), ('server', 150), ('ip', 120), ('success', 70)]:
            tree.heading(col, text=col.upper())
            tree.column(col, width=w, anchor='w')
        vsb = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
        tree.configure(yscroll=vsb.set)
        tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='left', fill='y')

        # Detail panel
        ttk.Label(detail_frame, text='Details:').pack(anchor='w')
        detail_txt = scrolledtext.ScrolledText(
            detail_frame, wrap='word', height=8)
        detail_txt.pack(fill='both', expand=True)
        status_var = tk.StringVar(value='Ready')
        status_lbl = ttk.Label(container, textvariable=status_var, anchor='w')
        status_lbl.pack(fill='x', pady=(4, 0))

        records = []  # full parsed list
        filtered_ids = []

        def parse_line(line: str):
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return None
                return obj
            except Exception:
                return None

        def load_audit():
            # Load and parse file
            if not os.path.exists(AUDIT_LOG_PATH):
                status_var.set('No audit.log file found')
                return []
            try:
                with open(AUDIT_LOG_PATH, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except Exception as e:
                status_var.set(f'Read error: {e}')
                return []
            if tail_only_var.get() and len(lines) > limit_var.get():
                lines = lines[-limit_var.get():]
            parsed = []
            for ln in lines:
                p = parse_line(ln)
                if p:
                    parsed.append(p)
            return parsed

        def apply_filters():
            ev_f = event_filter.get().strip().lower()
            u_f = user_filter.get().strip().lower()
            t_f = text_filter.get().strip().lower()
            limit = limit_var.get()
            # Clear table
            for iid in tree.get_children():
                tree.delete(iid)
            count = 0
            filtered_ids.clear()
            for obj in reversed(records):  # show newest first
                ts = obj.get('ts', '')
                usr = str(obj.get('user', '') or '')
                event = obj.get('event', '')
                details = obj.get('details') or {}
                # Quick text aggregate for contains filter
                details_text = json.dumps(details, ensure_ascii=False)
                if ev_f and ev_f not in event.lower():
                    continue
                if u_f and u_f not in usr.lower():
                    continue
                if t_f and t_f not in details_text.lower():
                    continue
                server = details.get('server') or details.get('target') or ''
                ip = details.get('ip') or ''
                success = details.get('success')
                success_str = '' if success is None else (
                    '✔' if success else '✖')
                row_id = tree.insert('', 'end', values=(
                    ts, usr, event, server, ip, success_str))
                filtered_ids.append((row_id, obj))
                count += 1
                if count >= limit:
                    break
            status_var.set(f'{count} event(s) shown (limit {limit})')

        def refresh():
            nonlocal records
            records = load_audit()
            apply_filters()
            log_event('audit_refreshed', {'user': user, 'count': len(records)})

        def on_select(event):
            sel = tree.selection()
            if not sel:
                return
            iid = sel[0]
            for rid, obj in filtered_ids:
                if rid == iid:
                    detail_txt.delete('1.0', tk.END)
                    detail_txt.insert(tk.END, json.dumps(
                        obj, indent=2, ensure_ascii=False))
                    detail_txt.see('1.0')
                    break

        tree.bind('<<TreeviewSelect>>', on_select)

        btn_bar = ttk.Frame(container)
        btn_bar.pack(fill='x', pady=(4, 2))
        ttk.Button(btn_bar, text='Refresh', command=refresh).pack(
            side='right', padx=4)
        ttk.Button(btn_bar, text='Apply Filters',
                   command=apply_filters).pack(side='right')

        refresh()
        log_event('audit_view_opened', {'user': user})

    def change_language(self, language_code):
        """Change the application language."""
        if self.lang_manager.set_language(language_code):
            self.language_var.set(language_code)
            self.update_translations()

    def on_language_change(self, event=None):
        """Handle language change from combo box."""
        self.change_language(self.language_var.get())

    def update_translations(self):
        """Update all translatable widgets with new language."""
        # Update window title
        self.root.title(_('app_title'))

        # Update main widgets
        self.title_label.config(text=_('server_monitor'))
        self.refresh_btn.config(text=_('refresh'))
        self.auto_refresh_cb.config(text=_('auto_refresh'))
        self.servers_frame.config(text=_('servers'))
        self.status_bar.config(text=_('ready'))

        # Update server widgets
        for server_ip, widgets in self.server_widgets.items():
            if 'restart_btn' in widgets:
                widgets['restart_btn'].config(text=_('restart_server'))
            if 'test_ssh_btn' in widgets:
                widgets['test_ssh_btn'].config(text=_('test_ssh'))

            # Update status text if available
            if server_ip in self.server_status:
                status = self.server_status[server_ip]
                self.update_server_display(server_ip, status)

        # Recreate menu to update labels
        self.create_menu_bar()

    # --- Telegram integration (GUI actions) ---
    def load_telegram_messages(self, silent: bool = False):
        """Fetch and display recent Telegram messages via unified client."""
        if not TELEGRAM_ENABLED:
            if not silent:
                messagebox.showinfo("Telegram", "Telegram is not configured.")
            return

        def run_fetch():
            if not silent:
                self._set_tel_status("loading…", 'blue')
                self.root.after(0, lambda: self.update_status_bar(
                    "Loading Telegram messages"))
            try:
                client = TelegramClient(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
                ok, data = client.get_recent_messages(
                    limit=max(1, self.tel_limit_var.get()))
            except Exception as e:
                ok, data = False, str(e)

            if ok:
                msgs = self._filter_messages(data)
                lines = []
                for m in msgs:
                    ts = m['date'].strftime(
                        '%Y-%m-%d %H:%M:%S') if m.get('date') else ''
                    lines.append(f"[{ts}] {m.get('text','')}")
                if not lines:
                    lines = ["(no messages)"]
                text = "\n".join(lines)
                self.root.after(0, lambda: self._telegram_set_text(text))
                if not silent:
                    self._set_tel_status("ok", 'green')
                    self.root.after(0, lambda: self.update_status_bar(
                        "Telegram messages loaded"))
            else:
                if not silent:
                    self._set_tel_status("error", 'red')
                    self.root.after(0, lambda: messagebox.showerror(
                        "Telegram", f"Load failed: {data}"))
                    self.root.after(0, lambda: self.update_status_bar(
                        "Telegram load failed"))

        threading.Thread(target=run_fetch, daemon=True).start()

    def send_telegram_test(self):
        """Send a test message (bot first, fallback to user session)."""
        if not TELEGRAM_ENABLED:
            messagebox.showinfo("Telegram", "Telegram not configured.")
            return
        # Bot attempt
        bot_ok = False
        bot_err = None
        try:
            client = TelegramClient(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
            ok, res = client.send_message("Test from Cobaltax (bot)")
            if ok:
                bot_ok = True
            else:
                bot_err = res
        except Exception as e:
            bot_err = str(e)
        if bot_ok:
            messagebox.showinfo(
                "Telegram", "Test message sent via bot. Click Load to refresh.")
            self.update_status_bar("Telegram test sent (bot)")
            return
        # Fallback user session
        if TLUserClient is None:
            messagebox.showerror(
                "Telegram", f"Bot failed: {bot_err}\nTelethon not installed for fallback.")
            self.update_status_bar("Telegram test failed")
            return
        import asyncio

        async def send_user():
            try:
                api_id = int(os.environ.get('TELEGRAM_API_ID', '0') or 0)
                api_hash = os.environ.get('TELEGRAM_API_HASH')
                if not api_id or not api_hash:
                    return False, "Missing TELEGRAM_API_ID / TELEGRAM_API_HASH"
                cid_raw = str(TELEGRAM_CHAT_ID)
                try:
                    cid = int(cid_raw)
                except Exception:
                    cid = cid_raw
                async with TLUserClient('cobaltax_user_session', api_id, api_hash) as c:
                    # Resolve entity
                    try:
                        entity = await c.get_entity(cid)
                    except Exception:
                        entity = None
                        async for d in c.iter_dialogs():
                            ent = d.entity
                            base_id = getattr(ent, 'id', None)
                            full_id = f"-100{base_id}" if ent.__class__.__name__ == 'Channel' else str(
                                base_id)
                            if str(full_id) == str(cid_raw):
                                entity = ent
                                break
                    if entity is None:
                        return False, f"User session cannot resolve chat {cid_raw}"
                    await c.send_message(entity, "Test from Cobaltax (user session fallback)")
                    return True, None
            except Exception as e:
                return False, str(e)
        try:
            ok, err = asyncio.run(send_user())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                ok, err = loop.run_until_complete(send_user())
            finally:
                loop.close()
        if ok:
            messagebox.showinfo(
                "Telegram", "Test message sent via user session. Click Load to refresh.")
            self.update_status_bar("Telegram test sent (user session)")
        else:
            messagebox.showerror(
                "Telegram", f"Bot failed: {bot_err}\nUser session failed: {err}")
            self.update_status_bar("Telegram test failed")

    def _telegram_set_text(self, text: str):
        """Utility to safely update telegram text widget."""
        if not self.telegram_text:
            return
        self.telegram_text.config(state=tk.NORMAL)
        self.telegram_text.delete('1.0', tk.END)
        self.telegram_text.insert(tk.END, text)
        # Auto-scroll to last line
        try:
            self.telegram_text.see(tk.END)
        except Exception:
            pass
        self.telegram_text.config(state=tk.DISABLED)

    # --- Enhanced Telegram features ---
    def schedule_telegram_auto(self):
        if not TELEGRAM_ENABLED:
            return
        if self.telegram_auto_job:
            try:
                self.root.after_cancel(self.telegram_auto_job)
            except Exception:
                pass
            self.telegram_auto_job = None
        if self.telegram_auto_var.get():
            self.telegram_auto_job = self.root.after(
                self.telegram_interval * 1000, self._auto_refresh_telegram)

    def _auto_refresh_telegram(self):
        if not self.telegram_auto_var.get():
            return
        self.load_telegram_messages(silent=True)
        self.schedule_telegram_auto()

    def send_custom_telegram(self):
        if not TELEGRAM_ENABLED:
            return
        text = self.telegram_send_var.get().strip()
        if not text:
            return

        def worker():
            try:
                self._set_tel_status("sending…", 'orange')
                client = TelegramClient(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
                ok, res = client.send_message(text)
                if ok:
                    self.telegram_send_var.set("")
                    self._set_tel_status("sent", 'green')
                    self.load_telegram_messages(silent=True)
                else:
                    self._set_tel_status(f"fail: {res}", 'red')
            except Exception as e:
                self._set_tel_status(f"error: {e}", 'red')
        threading.Thread(target=worker, daemon=True).start()

    def _set_tel_status(self, text: str, color: str = 'grey'):
        if hasattr(self, 'telegram_status') and self.telegram_status is not None:
            try:
                self.telegram_status.config(text=text, foreground=color)
            except Exception:
                pass

    def _filter_messages(self, msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        flt = self.telegram_filter_var.get().strip().lower()
        if not flt:
            return msgs
        out = []
        for m in msgs:
            if flt in (m.get('text') or '').lower():
                out.append(m)
        return out

    def telegram_fetch_via_user_session(self, limit: int, full: bool):
        """Fetch messages using Telethon user session (cobaltax_user_session)."""
        if TLUserClient is None:
            return False, "Telethon not installed (pip install telethon)"
        import asyncio

        try:
            api_id = int(os.environ.get('TELEGRAM_API_ID', '0') or 0)
        except ValueError:
            api_id = 0
        api_hash = os.environ.get('TELEGRAM_API_HASH')
        if not api_id or not api_hash:
            return False, "Missing TELEGRAM_API_ID / TELEGRAM_API_HASH env vars"

        cid_raw = str(TELEGRAM_CHAT_ID)
        try:
            cid = int(cid_raw)
        except Exception:
            cid = cid_raw

        async def fetch():
            try:
                async with TLUserClient('cobaltax_user_session', api_id, api_hash) as client:
                    # Resolve entity (direct or dialog scan)
                    entity = None
                    try:
                        entity = await client.get_entity(cid)
                    except Exception:
                        async for d in client.iter_dialogs():
                            ent = d.entity
                            base_id = getattr(ent, 'id', None)
                            full_id = f"-100{base_id}" if ent.__class__.__name__ == 'Channel' else str(
                                base_id)
                            if str(full_id) == str(cid_raw):
                                entity = ent
                                break
                    if entity is None:
                        return False, f"User session cannot resolve chat id {cid_raw}"

                    fetch_limit = limit if full else min(limit, 200)
                    msgs = []
                    async for msg in client.iter_messages(entity, limit=fetch_limit):
                        msgs.append({
                            'date': msg.date,
                            'text': getattr(msg, 'message', '') or ''
                        })
                    # Return newest last for readable chronological order
                    msgs.reverse()
                    return True, msgs
            except Exception as e:
                return False, f"Telethon error: {e}"

        try:
            return asyncio.run(fetch())
        except RuntimeError:
            # If already in loop (unlikely in our threaded usage), create new loop
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(fetch())
            finally:
                loop.close()

    def load_telegram_full_history(self):
        """Load extended history (large limit)."""
        if not TELEGRAM_ENABLED:
            messagebox.showinfo("Telegram", "Telegram not configured.")
            return

        def run_full():
            self._set_tel_status("loading full…", 'blue')
            self.root.after(0, lambda: self.update_status_bar(
                "Loading full Telegram history"))
            try:
                client = TelegramClient(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
                limit = max(self.tel_limit_var.get(), 500)
                ok, data = client.get_full_history(limit=limit)
            except Exception as e:
                ok, data = False, str(e)
            if ok:
                msgs = self._filter_messages(data)
                lines = []
                for m in msgs:
                    ts = m['date'].strftime(
                        '%Y-%m-%d %H:%M:%S') if m.get('date') else ''
                    lines.append(f"[{ts}] {m.get('text','')}")
                if not lines:
                    lines = ["(no history)"]
                self.root.after(
                    0, lambda: self._telegram_set_text("\n".join(lines)))
                self._set_tel_status("full ok", 'green')
                self.root.after(0, lambda: self.update_status_bar(
                    "Full Telegram history loaded"))
            else:
                self._set_tel_status("error", 'red')
                self.root.after(0, lambda: messagebox.showwarning(
                    "Telegram", f"Full history failed: {data}"))
                self.root.after(0, lambda: self.update_status_bar(
                    "Full history not available"))
        threading.Thread(target=run_full, daemon=True).start()

    def update_server_display(self, server_ip: str, status: Dict[str, Any]):
        """Update the display for a specific server."""
        if server_ip not in self.server_widgets:
            return

        widgets = self.server_widgets[server_ip]

        # Update status indicator and text
        if status.get('online'):
            widgets['status_indicator'].config(fg='green')
            widgets['status_text'].config(text=_('online'))
            widgets['restart_btn'].config(state='normal')
        else:
            widgets['status_indicator'].config(fg='red')
            if status.get('ping_success') or status.get('ping'):
                widgets['status_text'].config(text=_('ssh_port_closed'))
            else:
                widgets['status_text'].config(text=_('offline'))
            widgets['restart_btn'].config(state='disabled')

        # Update last checked time
        last_checked = status.get(
            'last_check') or status.get('last_checked') or ''
        widgets['last_checked'].config(
            text=f"{_('last_checked')}: {last_checked}")

        # Update or create resource information
        if 'resources_label' not in widgets:
            # Create resource label if it doesn't exist
            resources_label = ttk.Label(
                widgets['frame'],
                text="",
                font=('Arial', 8),
                foreground='blue'
            )
            resources_label.grid(
                row=3, column=0, columnspan=2, sticky=tk.W, pady=(5, 0))
            widgets['resources_label'] = resources_label

        # Display resource information (condensed/verbose + ESXi abbreviations)
        if status.get('resources') and 'error' not in status['resources']:
            r = status['resources']
            server_def = self.server_by_ip.get(server_ip, {})
            is_esxi = server_def.get('os_type') == 'esxi'
            parts = []
            if self.condensed_resources_mode:
                if 'cpu_usage' in r:
                    parts.append(f"C{r['cpu_usage']:.0f}%")
                if 'memory_usage' in r and 'memory_used_gb' in r and 'memory_total_gb' in r:
                    parts.append(f"R{r['memory_usage']:.0f}%")
                if 'disk_usage' in r:
                    parts.append(f"D{r['disk_usage']:.0f}%")
                if 'uptime' in r:
                    u = r['uptime']
                    short_u = u.split(',')[0].strip()
                    parts.append(short_u)
                txt = ' '.join(parts)
            else:
                if 'cpu_usage' in r:
                    parts.append(f"CPU: {r['cpu_usage']:.1f}%")
                if 'memory_usage' in r and 'memory_used_gb' in r and 'memory_total_gb' in r:
                    if is_esxi:
                        parts.append(
                            f"RAM {r['memory_used_gb']:.0f}/{r['memory_total_gb']:.0f}G ({r['memory_usage']:.0f}%)")
                    else:
                        parts.append(
                            f"RAM: {r['memory_usage']:.1f}% ({r['memory_used_gb']:.1f}/{r['memory_total_gb']:.1f}GB)")
                if 'disk_usage' in r and 'disk_free' in r:
                    if is_esxi:
                        parts.append(
                            f"DSK {r['disk_usage']:.0f}% F:{r['disk_free']}")
                    else:
                        parts.append(
                            f"Disk: {r['disk_usage']:.1f}% (Free: {r['disk_free']})")
                if 'uptime' in r:
                    parts.append(f"Up {r['uptime']}")
                txt = ' | '.join(parts)
            widgets['resources_label'].config(text=txt if txt else (
                "Res: N/A" if self.condensed_resources_mode else "Resources: N/A"))
        elif status.get('resources') and 'error' in status['resources']:
            widgets['resources_label'].config(
                text=(
                    f"Res ERR: {status['resources']['error']}" if self.condensed_resources_mode else f"Resources: {status['resources']['error']}")
            )
        else:
            widgets['resources_label'].config(
                text="Res: N/A" if self.condensed_resources_mode else "Resources: N/A")

        # Always enable SSH test button (may be overridden if parent offline)
        widgets['test_ssh_btn'].config(state='normal')
        server = self.server_by_ip.get(server_ip)
        parent_ip = server.get('parent') if server else None
        # If parent offline, visually disable child
        if parent_ip and parent_ip in self.server_status and not self.server_status[parent_ip]['online']:
            widgets['status_indicator'].config(fg='gray')
            widgets['status_text'].config(text='(Parent Offline)')
            for key in ('restart_btn', 'test_ssh_btn', 'test_sudo_btn', 'debug_btn'):
                if key in widgets:
                    widgets[key].config(state='disabled')
        # Update dependency line dynamically
        if server and 'dependency_label' in widgets:
            widgets['dependency_label'].config(
                text=self.format_dependency_line(server))
        # Update parent roll-up summary after any child update
        if parent_ip:
            self.update_parent_header(parent_ip)
        # If server itself is a parent, update its header
        if server_ip in self.dependency_children:
            self.update_parent_header(server_ip)

        # Update list view row if list mode active
        if getattr(self, 'view_mode', 'card') == 'list' and hasattr(self, 'server_rows') and server_ip in self.server_rows:
            self.update_list_row(server_ip)

    # --- Dependency Handling ---
    def build_dependency_index(self):
        self.dependency_children.clear()
        for s in SERVERS:
            parent = s.get('parent')
            if parent:
                self.dependency_children.setdefault(parent, []).append(s)

    def format_dependency_line(self, server: Dict[str, Any]) -> str:
        parent = server.get('parent')
        children = self.dependency_children.get(server.get('ip'), [])
        parts = []
        if parent:
            p_name = self.server_by_ip.get(parent, {}).get('name', parent)
            parts.append(f"Parent: {p_name}")
        if children:
            # Show up to 3 children, then count
            names = [c.get('name', c['ip']) for c in children]
            if len(names) > 3:
                shown = ", ".join(names[:3]) + f" (+{len(names)-3})"
            else:
                shown = ", ".join(names)
            # Add up count summary
            up = 0
            for c in children:
                st = self.server_status.get(c['ip'])
                if st and st.get('online'):
                    up += 1
            parts.append(f"Children: {shown} [{up}/{len(children)} up]")
        return " | ".join(parts) if parts else ""

    def update_parent_header(self, parent_ip: str):
        server = self.server_by_ip.get(parent_ip)
        if not server:
            return
        widgets = self.server_widgets.get(parent_ip)
        if not widgets:
            return
        children = self.dependency_children.get(parent_ip, [])
        total = len(children)
        up = 0
        for c in children:
            st = self.server_status.get(c['ip'])
            if st and st.get('online'):
                up += 1
        arrow = '▼' if parent_ip in self.expanded_parents else '▶'
        if self.current_theme.startswith(('retro', 'norton')):
            arrow = '-' if parent_ip in self.expanded_parents else '+'
        # Emoji roll-up for quick glance
        if total == 0:
            health_emoji = '•'
        elif up == total:
            health_emoji = '✅'
        elif up == 0:
            health_emoji = '❌'
        else:
            health_emoji = '⚠️'
        summary = f" {health_emoji} ({up}/{total})" if total else ""
        widgets['frame'].config(text=f"{server['name']}{summary}")
        if widgets.get('toggle_btn'):
            widgets['toggle_btn'].config(text=arrow)

    # --- Compact Mode ---
    def toggle_compact_mode(self):
        self.compact_mode = self.compact_mode_var.get()
        self.apply_compact_mode()
        self.update_server_grid(force=True)

    def toggle_ultra_compact_mode(self):
        self.ultra_compact_mode = self.ultra_compact_mode_var.get()
        # Ultra implies at least compact visuals
        if self.ultra_compact_mode and not self.compact_mode:
            self.compact_mode = True
            self.compact_mode_var.set(True)
        self.apply_compact_mode()
        self.update_server_grid(force=True)

    def toggle_hide_buttons_mode(self):
        self.hide_buttons_mode = self.hide_buttons_var.get()
        self.apply_compact_mode()
        self.update_server_grid(force=True)

    def toggle_condensed_resources_mode(self):
        self.condensed_resources_mode = self.condensed_resources_var.get()
        for ip, st in self.server_status.items():
            self.update_server_display(ip, st)

    def apply_compact_mode(self):
        """Adjust widgets for compact vs normal mode."""
        # Font selections
        if self.current_theme.startswith('retro'):
            base_font_normal = ('Courier New', 10)
            base_font_compact = ('Courier New', 7)
            base_font_ultra = ('Courier New', 6)
        else:
            base_font_normal = ('Arial', 10)
            base_font_compact = ('Arial', 7)
            base_font_ultra = ('Arial', 6)

        for ip, widgets in self.server_widgets.items():
            frame = widgets['frame']
            try:
                if self.ultra_compact_mode:
                    frame.configure(padding="2")
                elif self.compact_mode:
                    frame.configure(padding="6")
                else:
                    frame.configure(padding="10")
            except Exception:
                pass

            # Status indicator size
            try:
                indicator_size = 10 if self.ultra_compact_mode else (
                    14 if self.compact_mode else 20)
                widgets['status_indicator'].config(
                    font=('Arial', indicator_size))
            except Exception:
                pass

            # Labels fonts
            f = base_font_ultra if self.ultra_compact_mode else (
                base_font_compact if self.compact_mode else base_font_normal)
            for key in ('status_text', 'last_checked', 'dependency_label', 'resources_label', 'ip_label'):
                if key in widgets and widgets[key] is not None:
                    try:
                        widgets[key].config(font=f)
                    except Exception:
                        pass

            # Hide less critical labels entirely in ultra compact
            hide_labels = self.ultra_compact_mode
            for key in ('last_checked', 'dependency_label', 'resources_label'):
                if key in widgets and widgets[key] is not None:
                    try:
                        if hide_labels:
                            widgets[key].grid_remove()
                        else:
                            # Re-grid only if it had been removed previously (simple approach: use grid again by position)
                            # We won't perfectly restore original ordering beyond functional density needs.
                            if not widgets[key].winfo_manager():
                                if key == 'last_checked':
                                    widgets[key].grid(
                                        row=1, column=0, columnspan=3, sticky=tk.W, pady=(5, 0))
                                elif key == 'dependency_label':
                                    widgets[key].grid(
                                        row=2, column=0, columnspan=3, sticky=tk.W, pady=(3, 0))
                                elif key == 'resources_label':
                                    widgets[key].grid(
                                        row=3, column=0, columnspan=2, sticky=tk.W, pady=(5, 0))
                    except Exception:
                        pass

            # Buttons: shorten text in compact mode
            if self.hide_buttons_mode and 'button_frame' in widgets:
                try:
                    widgets['button_frame'].grid_remove()
                except Exception:
                    pass
            else:
                # Ensure frame is visible
                if 'button_frame' in widgets:
                    try:
                        if not widgets['button_frame'].winfo_manager():
                            widgets['button_frame'].grid(
                                row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(10, 0))
                    except Exception:
                        pass
                if self.compact_mode or self.ultra_compact_mode:
                    if 'restart_btn' in widgets:
                        widgets['restart_btn'].config(text='⟳')
                    if 'test_ssh_btn' in widgets:
                        widgets['test_ssh_btn'].config(text='SSH')
                    if 'test_sudo_btn' in widgets:
                        widgets['test_sudo_btn'].config(text='🔑')
                    if 'debug_btn' in widgets:
                        widgets['debug_btn'].config(text='🐞')
                else:
                    if 'restart_btn' in widgets:
                        widgets['restart_btn'].config(text=_('restart_server'))
                    if 'test_ssh_btn' in widgets:
                        widgets['test_ssh_btn'].config(text=_('test_ssh'))
                    if 'test_sudo_btn' in widgets:
                        widgets['test_sudo_btn'].config(text="🔑 Test 'sudo'")
                    if 'debug_btn' in widgets:
                        widgets['debug_btn'].config(text='🔍 Debug')

        # Parent headers may need re-evaluation of length/truncation (future improvement)
        for parent_ip in self.dependency_children.keys():
            self.update_parent_header(parent_ip)

        # If list view is active, restyle row height & refresh rows
        if getattr(self, 'view_mode', 'card') == 'list' and hasattr(self, 'list_tree') and self.list_tree:
            try:
                row_h = 16 if self.compact_mode else 20
                self._style.configure('Treeview', rowheight=row_h)
            except Exception:
                pass
            for ip in list(getattr(self, 'server_rows', {}).keys()):
                self.update_list_row(ip)

    # ---------------- List / Table View Helpers ----------------
    def switch_view_mode(self, mode: str):
        """Switch between card and list modes for density preferences."""
        if mode == getattr(self, 'view_mode', 'card'):
            return
        self.view_mode = mode
        # Hide both sets first
        try:
            self.card_canvas.grid_remove()
            self.card_scrollbar.grid_remove()
        except Exception:
            pass
        if hasattr(self, 'list_tree') and self.list_tree:
            try:
                self.list_tree.grid_remove()
                if self.list_scrollbar:
                    self.list_scrollbar.grid_remove()
            except Exception:
                pass
        if mode == 'list':
            if not hasattr(self, 'list_tree') or self.list_tree is None:
                self.build_list_view()
            self.populate_list_view()
        else:  # card
            try:
                self.card_canvas.grid(
                    row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
                self.card_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
            except Exception:
                pass
            self.update_server_grid(force=True)
        self.update_status_bar(f"Switched to {mode} view")

    def build_list_view(self):
        columns = ('name', 'ip', 'status', 'res', 'relation')
        self.list_tree = ttk.Treeview(
            self.servers_frame, columns=columns, show='headings')
        headers = {
            'name': 'Name',
            'ip': 'IP',
            'status': 'Status',
            'res': 'Res',
            'relation': 'Relation'
        }
        for col in columns:
            self.list_tree.heading(col, text=headers[col])
            width = 110
            if col == 'name':
                width = 160
            if col == 'relation':
                width = 140
            if col == 'res':
                width = 120
            self.list_tree.column(col, width=width, anchor=tk.W, stretch=True)
        self.list_tree.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.E, tk.W))
        self.servers_frame.rowconfigure(0, weight=1)
        self.servers_frame.columnconfigure(0, weight=1)
        # Scrollbar
        self.list_scrollbar = ttk.Scrollbar(
            self.servers_frame, orient='vertical', command=self.list_tree.yview)
        self.list_tree.configure(yscrollcommand=self.list_scrollbar.set)
        self.list_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.list_tree.bind('<Double-1>', self.on_list_double_click)
        self.server_rows = {}

    def populate_list_view(self):
        if not self.list_tree:
            return
        for iid in self.list_tree.get_children():
            self.list_tree.delete(iid)
        self.server_rows.clear()
        display_ips: List[str] = []
        for s in SERVERS:
            if not s.get('parent'):
                display_ips.append(s['ip'])
                if s['ip'] in self.expanded_parents:
                    for child in self.dependency_children.get(s['ip'], []):
                        display_ips.append(child['ip'])
        for ip in display_ips:
            server = self.server_by_ip.get(ip, {})
            name = server.get('name', ip)
            if server.get('parent'):
                name = f"↳ {name}"
            status_obj = self.server_status.get(ip)
            status_text = self.get_status_text_for_list(ip, status_obj)
            res_text = self.summarize_resources(status_obj)
            relation_text = self.get_relation_text(ip)
            iid = self.list_tree.insert('', tk.END, iid=ip, values=(
                name, ip, status_text, res_text, relation_text))
            self.server_rows[ip] = iid

    def summarize_resources(self, status: Dict[str, Any] | None) -> str:
        if not status or not status.get('resources') or 'error' in status['resources']:
            return ''
        r = status['resources']
        parts = []
        if 'cpu_usage' in r:
            parts.append(f"C{r['cpu_usage']:.0f}%")
        if 'memory_usage' in r:
            parts.append(f"R{r['memory_usage']:.0f}%")
        if 'disk_usage' in r:
            parts.append(f"D{r['disk_usage']:.0f}%")
        return ' '.join(parts)

    def get_status_text_for_list(self, ip: str, status: Dict[str, Any] | None) -> str:
        if not status:
            return _('checking')
        if not status.get('online'):
            if status.get('ping_success'):
                return _('ssh_port_closed')
            return _('offline')
        return _('online')

    def get_relation_text(self, ip: str) -> str:
        if ip in self.dependency_children:
            children = self.dependency_children[ip]
            total = len(children)
            up = 0
            for c in children:
                st = self.server_status.get(c['ip'])
                if st and st.get('online'):
                    up += 1
            return f"Children {up}/{total} up" if total else ''
        server = self.server_by_ip.get(ip)
        if server and server.get('parent'):
            parent_name = self.server_by_ip.get(
                server['parent'], {}).get('name', server['parent'])
            return f"Parent: {parent_name}"
        return ''

    def update_list_row(self, ip: str):
        if not getattr(self, 'list_tree', None) or ip not in getattr(self, 'server_rows', {}):
            return
        server = self.server_by_ip.get(ip, {})
        name = server.get('name', ip)
        if server.get('parent'):
            name = f"↳ {name}"
        status_obj = self.server_status.get(ip)
        status_text = self.get_status_text_for_list(ip, status_obj)
        res_text = self.summarize_resources(status_obj)
        relation_text = self.get_relation_text(ip)
        self.list_tree.item(self.server_rows[ip], values=(
            name, ip, status_text, res_text, relation_text))

    def on_list_double_click(self, event):
        if not getattr(self, 'list_tree', None):
            return
        item = self.list_tree.identify_row(event.y)
        if not item:
            return
        ip = item
        if ip in self.dependency_children:
            if ip in self.expanded_parents:
                self.expanded_parents.remove(ip)
            else:
                self.expanded_parents.add(ip)
            self.populate_list_view()

    def toggle_parent(self, parent_ip: str):
        if parent_ip in self.expanded_parents:
            self.expanded_parents.remove(parent_ip)
        else:
            self.expanded_parents.add(parent_ip)
        self.update_parent_header(parent_ip)
        self.update_server_grid(force=True)

    def update_dependency_visuals(self):
        # Refresh after a batch status update
        for parent_ip in list(self.dependency_children.keys()):
            self.update_parent_header(parent_ip)
            for child in self.dependency_children[parent_ip]:
                st = self.server_status.get(child['ip'])
                if st:
                    self.update_server_display(child['ip'], st)

    def check_server_status(self, server: Dict[str, Any]):
        """Check status of a single server (runs in thread)."""
        try:
            status = self.server_monitor.get_server_status(server)
            self.server_status[server['ip']] = status

            # Update GUI in main thread
            self.root.after(
                0, lambda: self.update_server_display(server['ip'], status))

        except Exception as e:
            print(f"Error checking server {server['name']}: {e}")

    def refresh_all_servers(self):
        """Refresh status of all servers."""
        self.update_status_bar(_('refreshing_status'))
        self.refresh_btn.config(state='disabled')

        # Disable all restart buttons during refresh
        for widgets in self.server_widgets.values():
            widgets['restart_btn'].config(state='disabled')
            widgets['status_text'].config(text=_('checking'))

        # Start status checks in parallel threads
        threads = []
        for server in SERVERS:
            thread = threading.Thread(
                target=self.check_server_status, args=(server,))
            thread.daemon = True
            thread.start()
            threads.append(thread)

        # Wait for all threads to complete in a separate thread
        def wait_for_completion():
            for thread in threads:
                thread.join()

            # Re-enable refresh button
            self.root.after(0, lambda: self.refresh_btn.config(state='normal'))
            self.root.after(0, lambda: self.update_status_bar(
                _('status_refresh_completed')))

        completion_thread = threading.Thread(target=wait_for_completion)
        completion_thread.daemon = True
        completion_thread.start()

    def restart_server(self, server: Dict[str, Any]):
        """Restart a server (runs in thread)."""
        # Confirm restart
        result = messagebox.askyesno(
            _('confirm_restart'),
            _('confirm_restart_message',
              server=server['name'], ip=server['ip'])
        )

        if not result:
            log_event('restart_cancelled', {
                'server': server.get('name'),
                'ip': server.get('ip'),
                'user': get_session_user()
            })
            return

        def restart_operation():
            self.root.after(0, lambda: self.update_status_bar(
                _('restarting_server', server=server['name'])))

            success, message = self.ssh_manager.restart_server(server)

            # Log result
            log_event('restart_executed', {
                'server': server.get('name'),
                'ip': server.get('ip'),
                'success': success,
                'message': message,
                'user': get_session_user()
            })

            # Show result in main thread
            self.root.after(0, lambda: self.show_restart_result(
                server, success, message))

        # Run restart in thread
        thread = threading.Thread(target=restart_operation)
        thread.daemon = True
        thread.start()

    def show_restart_result(self, server: Dict[str, Any], success: bool, message: str):
        """Show restart operation result."""
        if success:
            messagebox.showinfo(
                _('restart_initiated'),
                _('restart_initiated_message',
                  server=server['name'], message=message)
            )
            self.update_status_bar(
                _('restart_command_sent', server=server['name']))
        else:
            messagebox.showerror(
                _('restart_failed_title'),
                _('restart_failed_message',
                  server=server['name'], message=message)
            )
            self.update_status_bar(_('restart_failed', server=server['name']))

    def test_ssh_connection(self, server: Dict[str, Any]):
        """Test SSH connection to a server."""
        def test_operation():
            self.root.after(0, lambda: self.update_status_bar(
                _('testing_ssh', server=server['name'])))

            client, error = self.ssh_manager.create_ssh_client(server)

            if client:
                client.close()
                success = True
                message = "SSH connection successful!"
            else:
                success = False
                message = error

            # Show result in main thread
            self.root.after(0, lambda: self.show_ssh_test_result(
                server, success, message))

        # Run test in thread
        thread = threading.Thread(target=test_operation)
        thread.daemon = True
        thread.start()

    def show_ssh_test_result(self, server: Dict[str, Any], success: bool, message: str):
        """Show SSH test result."""
        if success:
            messagebox.showinfo(
                _('ssh_test_result'),
                _('ssh_test_successful_message', server=server['name'])
            )
            self.update_status_bar(
                _('ssh_test_successful', server=server['name']))
        else:
            messagebox.showerror(
                _('ssh_test_failed_title'),
                _('ssh_test_failed_message',
                  server=server['name'], message=message)
            )
            self.update_status_bar(_('ssh_test_failed', server=server['name']))

    def test_sudo_access(self, server: Dict[str, Any]):
        """Test sudo access on a server."""
        def test_operation():
            self.root.after(0, lambda: self.update_status_bar(
                f"Testing sudo access on {server['name']}..."))

            has_sudo, message = self.ssh_manager.test_sudo_access(server)

            # Show result in main thread
            self.root.after(0, lambda: self.show_sudo_test_result(
                server, has_sudo, message))

        # Run test in thread
        thread = threading.Thread(target=test_operation)
        thread.daemon = True
        thread.start()

    def show_sudo_test_result(self, server: Dict[str, Any], has_sudo: bool, message: str):
        """Show sudo test result."""
        if has_sudo:
            messagebox.showinfo(
                "Sudo Test Result",
                f"Sudo access test for {server['name']} successful!\n\n"
                f"{message}\n\n"
                "Server restart should work properly."
            )
            self.update_status_bar(
                f"Sudo test for {server['name']} successful")
        else:
            messagebox.showwarning(
                "Sudo Test Failed",
                f"Sudo access test for {server['name']} failed.\n\n"
                f"Issue: {message}\n\n"
                "Server restart may not work. Please check:\n"
                "• User has sudo privileges\n"
                "• Passwordless sudo is configured\n"
                "• User is in sudoers file"
            )
            self.update_status_bar(f"Sudo test for {server['name']} failed")

    def debug_server(self, server: Dict[str, Any]):
        """Open debug window for a server."""
        def debug_operation():
            self.root.after(0, lambda: self.update_status_bar(
                f"Gathering debug info for {server['name']}..."))

            # Collect debug information
            debug_info = []

            # Basic connectivity
            ping_result = self.server_monitor.ping_server(server['ip'])
            debug_info.append(
                f"Ping: {'✅ Success' if ping_result else '❌ Failed'}")

            ssh_port = server.get('ssh_port', 22)
            port_result = self.server_monitor.check_port(
                server['ip'], ssh_port)
            debug_info.append(
                f"SSH Port {ssh_port}: {'✅ Open' if port_result else '❌ Closed'}")

            if ping_result and port_result:
                # SSH connection test
                client, error = self.ssh_manager.create_ssh_client(server)
                if client:
                    debug_info.append("SSH Connection: ✅ Success")
                    client.close()

                    # Sudo test
                    has_sudo, sudo_msg = self.ssh_manager.test_sudo_access(
                        server)
                    debug_info.append(
                        f"Sudo Access: {'✅' if has_sudo else '❌'} {sudo_msg}")

                    # System info
                    info_success, system_info = self.ssh_manager.get_system_info(
                        server)
                    if info_success:
                        debug_info.append("System Info: ✅ Retrieved")
                        debug_info.append("=" * 40)
                        debug_info.extend(system_info.split('\n'))
                    else:
                        debug_info.append(f"System Info: ❌ {system_info}")
                else:
                    debug_info.append(f"SSH Connection: ❌ {error}")

            # Show debug window in main thread
            self.root.after(
                0, lambda: self.show_debug_window(server, debug_info))

        # Run debug in thread
        thread = threading.Thread(target=debug_operation)
        thread.daemon = True
        thread.start()

    def show_debug_window(self, server: Dict[str, Any], debug_info: list):
        """Show debug information window."""
        debug_window = tk.Toplevel(self.root)
        debug_window.title(f"Debug Info - {server['name']}")
        debug_window.geometry("600x400")

        # Create scrolled text widget
        text_frame = ttk.Frame(debug_window)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        text_widget = scrolledtext.ScrolledText(
            text_frame,
            wrap=tk.WORD,
            font=('Courier', 10)
        )
        text_widget.pack(fill=tk.BOTH, expand=True)

        # Insert debug information
        debug_text = f"Debug Information for {server['name']} ({server['ip']})\n"
        debug_text += "=" * 60 + "\n\n"
        debug_text += "\n".join(debug_info)

        text_widget.insert(tk.END, debug_text)
        text_widget.config(state=tk.DISABLED)

        # Close button
        close_btn = ttk.Button(
            debug_window,
            text="Close",
            command=debug_window.destroy
        )
        close_btn.pack(pady=5)

        self.update_status_bar(f"Debug info displayed for {server['name']}")

    def toggle_auto_refresh(self):
        """Toggle auto-refresh functionality."""
        self.auto_refresh = self.auto_refresh_var.get()

        if self.auto_refresh:
            self.schedule_auto_refresh()
            self.update_status_bar(_('auto_refresh_enabled'))
        else:
            if self.refresh_job:
                self.root.after_cancel(self.refresh_job)
                self.refresh_job = None
            self.update_status_bar(_('auto_refresh_disabled'))

    def schedule_auto_refresh(self):
        """Schedule the next auto-refresh."""
        if self.auto_refresh:
            self.refresh_job = self.root.after(
                REFRESH_INTERVAL * 1000,
                self.auto_refresh_callback
            )

    def auto_refresh_callback(self):
        """Callback for auto-refresh timer."""
        if self.auto_refresh:
            self.refresh_all_servers()
            self.schedule_auto_refresh()

    def on_closing(self):
        """Handle application closing."""
        if self.refresh_job:
            self.root.after_cancel(self.refresh_job)

        self.root.quit()
        self.root.destroy()

    def run(self):
        """Start the GUI application."""
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.on_closing()

    def create_server_widgets(self):
        """Create widgets for each configured server."""
        for i, server in enumerate(SERVERS):
            server_frame = ttk.LabelFrame(
                self.scrollable_frame,
                text=server['name'],
                padding="10"
            )
            try:
                server_frame.configure(style='Server.TLabelframe')
            except Exception:
                pass
            server_frame.grid(row=i, column=0, sticky=(tk.W, tk.E), pady=5)
            server_frame.columnconfigure(0, weight=0)
            server_frame.columnconfigure(1, weight=1)
            server_frame.columnconfigure(2, weight=0)

            is_parent = server['ip'] in self.dependency_children
            toggle_btn = None
            if is_parent:
                sym = '▼'
                if self.current_theme.startswith(('retro', 'norton')):
                    sym = '-'
                toggle_btn = ttk.Button(
                    server_frame,
                    text=sym,
                    width=2,
                    command=lambda ip=server['ip']: self.toggle_parent(ip),
                    style='Action.TButton'
                )
                toggle_btn.grid(row=0, column=0, sticky=tk.W, pady=(0, 2))

            ip_label = ttk.Label(
                server_frame, text=f"{_('ip_address')}: {server['ip']}")
            ip_label.grid(row=0, column=1, sticky=tk.W)

            status_frame = ttk.Frame(server_frame)
            status_frame.grid(row=0, column=2, sticky=tk.E)

            status_indicator = tk.Label(
                status_frame, text="●", font=('Arial', 20), fg='gray')
            status_indicator.pack(side=tk.LEFT)

            status_text = ttk.Label(status_frame, text=_('checking'))
            status_text.pack(side=tk.LEFT, padx=(5, 0))

            last_checked = ttk.Label(
                server_frame,
                text=f"{_('last_checked')}: {_('never')}",
                font=('Arial', 8),
                foreground='gray'
            )
            last_checked.grid(row=1, column=0, columnspan=3,
                              sticky=tk.W, pady=(5, 0))

            button_frame = ttk.Frame(server_frame)
            button_frame.grid(row=4, column=0, columnspan=3,
                              sticky=(tk.W, tk.E), pady=(10, 0))

            restart_btn = ttk.Button(
                button_frame,
                text=_('restart_server'),
                command=lambda s=server: self.restart_server(s),
                style='Primary.TButton'
            )
            restart_btn.pack(side=tk.LEFT)

            test_ssh_btn = ttk.Button(
                button_frame,
                text=_('test_ssh'),
                command=lambda s=server: self.test_ssh_connection(s),
                style='Action.TButton'
            )
            test_ssh_btn.pack(side=tk.LEFT, padx=(5, 0))

            test_sudo_btn = ttk.Button(
                button_frame,
                text="🔑 Test 'sudo'",
                command=lambda s=server: self.test_sudo_access(s),
                style='Action.TButton'
            )
            test_sudo_btn.pack(side=tk.LEFT, padx=(5, 0))

            debug_btn = ttk.Button(
                button_frame,
                text="🔍 Debug",
                command=lambda s=server: self.debug_server(s),
                style='Danger.TButton'
            )
            debug_btn.pack(side=tk.LEFT, padx=(5, 0))

            dep_label = ttk.Label(server_frame, text="", font=('Arial', 8))
            dep_label.grid(row=2, column=0, columnspan=3,
                           sticky=tk.W, pady=(3, 0))
            dep_label.config(text=self.format_dependency_line(server))

            self.server_widgets[server['ip']] = {
                'frame': server_frame,
                'ip_label': ip_label,
                'status_indicator': status_indicator,
                'status_text': status_text,
                'last_checked': last_checked,
                'restart_btn': restart_btn,
                'test_ssh_btn': test_ssh_btn,
                'test_sudo_btn': test_sudo_btn,
                'debug_btn': debug_btn,
                'dependency_label': dep_label,
                'toggle_btn': toggle_btn,
                'button_frame': button_frame
            }

        for parent_ip in self.dependency_children.keys():
            self.update_parent_header(parent_ip)

    def setup_bindings(self):
        """Register window and keyboard bindings."""
        # Proper window close handling
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        # Refresh shortcuts
        self.root.bind('<F5>', lambda e: self.refresh_all_servers())
        self.root.bind('<Control-r>', lambda e: self.refresh_all_servers())
        # Exit shortcut
        self.root.bind('<Escape>', lambda e: self.on_closing())

    # --- Re-added scrolling helper ---
    def bind_mousewheel(self):
        """Bind mouse wheel events to scroll the servers canvas."""
        if not hasattr(self, 'canvas') or self.canvas is None:
            return

        def _on_mousewheel(event):
            if event.delta:  # Windows / macOS
                delta = event.delta
            elif getattr(event, 'num', None) in (4, 5):  # X11
                delta = 120 if event.num == 4 else -120
            else:
                delta = 0
            if delta:
                self.canvas.yview_scroll(int(-1 * (delta / 120)), "units")

        def _bind(_):
            self.canvas.bind_all("<MouseWheel>", _on_mousewheel)
            self.canvas.bind_all("<Button-4>", _on_mousewheel)
            self.canvas.bind_all("<Button-5>", _on_mousewheel)

        def _unbind(_):
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")

        self.canvas.bind("<Enter>", _bind)
        self.canvas.bind("<Leave>", _unbind)

    # --- Re-added responsive layout helpers (previously removed accidentally) ---
    def classify_width(self, width: int) -> int:
        """Return ideal number of columns based on available width."""
        if self.compact_mode:
            if width < 600:
                return 1
            if width < 900:
                return 2
            if width < 1300:
                return 3
            return 4
        else:
            if width < 750:
                return 1
            if width < 1200:
                return 2
            return 3

    def update_server_grid(self, force: bool = False):
        """Re-grid server frames into responsive columns (card mode only)."""
        if getattr(self, 'view_mode', 'card') != 'card':
            return
        try:
            width = self.root.winfo_width()
        except Exception:
            width = WINDOW_WIDTH
        cols = self.classify_width(width)
        if not force and hasattr(self, 'server_columns') and cols == getattr(self, 'server_columns', None):
            return
        self.server_columns = cols

        display_ips: List[str] = []
        for s in SERVERS:
            if not s.get('parent'):
                display_ips.append(s['ip'])
                if s['ip'] in self.expanded_parents:
                    for child in self.dependency_children.get(s['ip'], []):
                        display_ips.append(child['ip'])

        for widgets in self.server_widgets.values():
            widgets['frame'].grid_forget()

        for c in range(cols):
            self.scrollable_frame.columnconfigure(c, weight=1)

        for idx, ip in enumerate(display_ips):
            widgets = self.server_widgets.get(ip)
            if not widgets:
                continue
            row = idx // cols
            col = idx % cols
            server_def = self.server_by_ip.get(ip, {})
            padx = (50, 5) if server_def.get('parent') else (5, 5)
            if server_def.get('parent'):
                try:
                    current_text = widgets['frame'].cget('text')
                    if not current_text.startswith('↳'):
                        widgets['frame'].config(text=f"↳ {current_text}")
                except Exception:
                    pass
            widgets['frame'].grid(row=row, column=col,
                                  sticky='nsew', padx=padx, pady=5)

    def on_window_resize(self, event):
        """Handle window resize events and update layout if width class changes."""
        if event.widget is self.root:
            self.update_server_grid()

# --- End of class ServerMonitorGUI ---

# --- Restored application entry point ---


def main():
    """Main entry point."""
    if not SERVERS:
        print("Error: No servers configured in config.py")
        sys.exit(1)

    print(f"Starting {WINDOW_TITLE}...")
    print(f"Monitoring {len(SERVERS)} server(s)")

    try:
        app = ServerMonitorGUI()
        app.run()
    except Exception as e:
        print(f"Error starting application: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
