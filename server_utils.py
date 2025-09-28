"""
Server monitoring utilities for network connectivity and SSH operations.
"""

import socket
import subprocess
import platform
import paramiko
import threading
from typing import Dict, Any, Tuple
import time
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
import os
import asyncio

# Optional Telethon fallback for history access
try:
    from telethon.sync import TelegramClient as _TLClient
    _HAS_TELETHON = True
except Exception:
    _HAS_TELETHON = False


class ServerMonitor:
    """Lightweight network reachability monitor (ping + port)."""

    def __init__(self, timeout: int = 3):
        self.timeout = timeout

    def ping_server(self, ip: str) -> bool:
        try:
            if platform.system().lower() == "windows":
                result = subprocess.run([
                    "ping", "-n", "1", "-w", str(self.timeout * 1000), ip
                ], capture_output=True, timeout=self.timeout + 2)
            else:
                result = subprocess.run([
                    "ping", "-c", "1", "-W", str(self.timeout), ip
                ], capture_output=True, timeout=self.timeout + 2)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
            return False

    def check_port(self, ip: str, port: int) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except socket.error:
            return False

    def get_server_status(self, server_config: Dict[str, Any]) -> Dict[str, Any]:
        """Aggregate reachability + (optional) SSH resource snapshot.

        Returns dict with keys: online(bool), ping(bool), ssh(bool), last_check, resources(optional/error)
        """
        ip = server_config.get('ip')
        now_iso = datetime.utcnow().isoformat(timespec='seconds')
        status: Dict[str, Any] = {
            'online': False,
            'ping': False,
            'ssh': False,
            'ping_success': False,  # legacy key for UI
            'last_check': now_iso,
            'last_checked': now_iso,  # legacy key
            'resources': None,
        }
        # Ping
        status['ping'] = self.ping_server(ip)
        status['ping_success'] = status['ping']
        if not status['ping']:
            return status
        # Try SSH quick connect for deeper metrics
        ssh_mgr = SSHManager(timeout=5)
        client, err = ssh_mgr.create_ssh_client(server_config)
        if client:
            status['ssh'] = True
            try:
                client.close()
            except Exception:
                pass
            # Obtain resources (non-blocking best effort)
            try:
                res = ssh_mgr.get_system_resources(server_config)
                status['resources'] = res
            except Exception as e:
                status['resources'] = {'error': str(e)}
        else:
            status['resources'] = {'error': f'SSH: {err}'}
        status['online'] = status['ping'] or status['ssh']
        return status


class SSHManager:
    """Encapsulates SSH connectivity, commands, resource collection, and restarts."""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    # ---------- Connection ----------
    def create_ssh_client(self, server_config: Dict[str, Any]) -> Tuple[Any, str]:
        ip = server_config.get('ip')
        user = server_config.get('ssh_user')
        password = server_config.get('ssh_password')
        key_path = server_config.get('ssh_key_path')
        port = server_config.get('ssh_port', 22)
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_args = {
                'hostname': ip,
                'username': user,
                'timeout': self.timeout,
                'port': port,
                'banner_timeout': 5,
                'auth_timeout': 5,
            }
            if key_path:
                connect_args['key_filename'] = key_path
            else:
                connect_args['password'] = password
            client.connect(**connect_args)
            return client, ''
        except Exception as e:
            return None, str(e)

    # ---------- Restart ----------
    def restart_server(self, server_config: Dict[str, Any]) -> Tuple[bool, str]:
        client, error = self.create_ssh_client(server_config)
        if not client:
            return False, f"SSH connection failed: {error}"
        try:
            os_type = server_config.get('os_type', 'linux').lower()
            ssh_password = server_config.get('ssh_password')
            if os_type == 'windows':
                return self._restart_windows_server(client, ssh_password)
            else:
                return self._restart_linux_server(client, ssh_password)
        except paramiko.SSHException as e:
            client.close()
            if "Socket is closed" in str(e) or "Connection lost" in str(e):
                return True, "Restart initiated (connection dropped as expected)"
            return False, f"SSH command failed: {e}"
        except Exception as e:
            client.close()
            return False, f"Restart failed: {e}"

    # (Reuse original private restart helpers below)

    def _restart_linux_server(self, client: paramiko.SSHClient, ssh_password: str) -> Tuple[bool, str]:
        """Restart Linux server."""
        # First, check if user has passwordless sudo privileges
        stdin, stdout, stderr = client.exec_command('sudo -n true', timeout=3)
        exit_status = stdout.channel.recv_exit_status()

        # Try different restart commands in order of preference
        restart_commands = [
            'sudo systemctl reboot',           # systemd (modern Ubuntu)
            'sudo shutdown -r now',            # Traditional shutdown command
            'sudo reboot',                     # Direct reboot command
            'sudo /sbin/reboot'                # Full path reboot
        ]

        for cmd in restart_commands:
            try:
                if exit_status != 0 and ssh_password:
                    # Need password for sudo - use echo method
                    full_cmd = f'echo "{ssh_password}" | sudo -S {cmd.split("sudo ")[1]} >/dev/null 2>&1 &'
                else:
                    # Passwordless sudo or try without password
                    full_cmd = f'nohup {cmd} >/dev/null 2>&1 &'

                # Execute restart command with short timeout
                stdin, stdout, stderr = client.exec_command(
                    full_cmd, timeout=3)

                # Give it a moment to execute
                import time
                time.sleep(0.5)

                client.close()
                return True, f"Linux restart command sent successfully: {cmd}"

            except paramiko.SSHException as ssh_error:
                # Connection drop is expected on reboot, this might be success
                if "Socket is closed" in str(ssh_error) or "Connection lost" in str(ssh_error):
                    client.close()
                    return True, f"Linux restart initiated (connection dropped): {cmd}"
                continue
            except Exception:
                continue

        client.close()
        return False, "All Linux restart commands failed. Check sudo privileges and server configuration."

    def _restart_windows_server(self, client: paramiko.SSHClient, ssh_password: str) -> Tuple[bool, str]:
        """Restart Windows server."""
        # Windows restart commands
        restart_commands = [
            # Immediate restart via cmd
            'shutdown /r /t 0',
            'shutdown /r /t 5',                                    # 5 second delay via cmd
            'powershell -NoProfile -Command "Restart-Computer -Force"'  # PowerShell
        ]

        for cmd in restart_commands:
            try:
                # Execute restart command
                stdin, stdout, stderr = client.exec_command(cmd, timeout=5)

                # Give it a moment to execute
                import time
                time.sleep(0.5)

                client.close()
                return True, f"Windows restart command sent successfully: {cmd}"

            except paramiko.SSHException as ssh_error:
                # Connection drop is expected on reboot
                if "Socket is closed" in str(ssh_error) or "Connection lost" in str(ssh_error):
                    client.close()
                    return True, f"Windows restart initiated (connection dropped): {cmd}"
                continue
            except Exception:
                continue

        client.close()
        return False, "All Windows restart commands failed. Check user privileges and server configuration."

    def get_system_resources(self, server_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get system resource information (CPU, RAM, Disk).

        Args:
            server_config: Server configuration dictionary

        Returns:
            Dictionary with resource information
        """
        client, error = self.create_ssh_client(server_config)

        if not client:
            return {'error': f"SSH connection failed: {error}"}

        try:
            os_type = server_config.get('os_type', 'linux').lower()

            if os_type == 'windows':
                return self._get_windows_resources(client)
            else:
                return self._get_linux_resources(client)

        except Exception as e:
            client.close()
            return {'error': f"Failed to get system resources: {str(e)}"}

    def _get_linux_resources(self, client: paramiko.SSHClient) -> Dict[str, Any]:
        """Get Linux system resources."""
        resources = {}

        try:
            # CPU Usage
            stdin, stdout, stderr = client.exec_command(
                "top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | awk -F'%' '{print $1}'",
                timeout=5
            )
            cpu_usage = stdout.read().decode('utf-8').strip()
            try:
                resources['cpu_usage'] = float(cpu_usage.replace('%', ''))
            except:
                resources['cpu_usage'] = 0.0

            # Memory Usage
            stdin, stdout, stderr = client.exec_command(
                "free | grep Mem | awk '{printf \"%.1f %.1f %.1f\", $3/$2 * 100.0, $3/1024/1024, $2/1024/1024}'",
                timeout=5
            )
            mem_info = stdout.read().decode('utf-8').strip().split()
            if len(mem_info) >= 3:
                resources['memory_usage'] = float(mem_info[0])
                resources['memory_used_gb'] = float(mem_info[1])
                resources['memory_total_gb'] = float(mem_info[2])
            else:
                resources['memory_usage'] = 0.0
                resources['memory_used_gb'] = 0.0
                resources['memory_total_gb'] = 0.0

            # Disk Usage (use KiB for reliable parsing, then convert)
            stdin, stdout, stderr = client.exec_command(
                "df -k / | awk 'NR==2{printf \"%s %s %s %s\", $3, $2, $4, $5}'",
                timeout=5
            )
            disk_info = stdout.read().decode('utf-8').strip().split()
            if len(disk_info) >= 4:
                try:
                    used_kb = float(disk_info[0])
                    total_kb = float(disk_info[1])
                    free_kb = float(disk_info[2])
                    usage_pct = float(disk_info[3].replace('%', ''))
                    resources['disk_used'] = f"{used_kb/1024/1024:.1f}GB"
                    resources['disk_total'] = f"{total_kb/1024/1024:.1f}GB"
                    resources['disk_free'] = f"{free_kb/1024/1024:.1f}GB"
                    resources['disk_usage'] = usage_pct
                except Exception:
                    resources['disk_used'] = '0GB'
                    resources['disk_total'] = '0GB'
                    resources['disk_free'] = '0GB'
                    resources['disk_usage'] = 0.0
            else:
                resources['disk_used'] = '0GB'
                resources['disk_total'] = '0GB'
                resources['disk_free'] = '0GB'
                resources['disk_usage'] = 0.0

            # Load Average
            stdin, stdout, stderr = client.exec_command(
                "uptime | awk -F'load average:' '{print $2}'", timeout=5)
            load_avg = stdout.read().decode('utf-8').strip()
            resources['load_average'] = load_avg

            # Uptime
            stdin, stdout, stderr = client.exec_command("uptime -p", timeout=5)
            uptime = stdout.read().decode('utf-8').strip()
            resources['uptime'] = uptime

            client.close()
            return resources

        except Exception as e:
            client.close()
            return {'error': f"Failed to get Linux resources: {str(e)}"}

    def _get_windows_resources(self, client: paramiko.SSHClient) -> Dict[str, Any]:
        """Get Windows system resources."""
        resources = {}

        try:
            # CPU Usage (PowerShell CIM)
            stdin, stdout, stderr = client.exec_command(
                'powershell -NoProfile -Command "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"',
                timeout=10
            )
            cpu_output = stdout.read().decode('utf-8').strip()
            try:
                resources['cpu_usage'] = float(cpu_output)
            except Exception:
                resources['cpu_usage'] = 0.0

            # Memory Usage (JSON)
            stdin, stdout, stderr = client.exec_command(
                'powershell -NoProfile -Command "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json -Compress"',
                timeout=10
            )
            mem_output = stdout.read().decode('utf-8').strip()
            try:
                mem_data = json.loads(mem_output)
                total_kb = float(mem_data.get('TotalVisibleMemorySize', 0))
                free_kb = float(mem_data.get('FreePhysicalMemory', 0))
                used_kb = max(total_kb - free_kb, 0)
                resources['memory_total_gb'] = total_kb/1024/1024
                resources['memory_used_gb'] = used_kb/1024/1024
                resources['memory_usage'] = (
                    used_kb / total_kb * 100.0) if total_kb > 0 else 0.0
            except Exception:
                resources['memory_usage'] = 0.0
                resources['memory_used_gb'] = 0.0
                resources['memory_total_gb'] = 0.0

            # Disk Usage for C: (JSON)
            stdin, stdout, stderr = client.exec_command(
                'powershell -NoProfile -Command "Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID=\\\"C:\\\"\" | Select-Object Size,FreeSpace | ConvertTo-Json -Compress"',
                timeout=10
            )
            disk_output = stdout.read().decode('utf-8').strip()
            try:
                disk_data = json.loads(disk_output)
                size_bytes = float(disk_data.get('Size', 0))
                free_bytes = float(disk_data.get('FreeSpace', 0))
                used_bytes = max(size_bytes - free_bytes, 0)
                to_gb = 1024*1024*1024
                resources['disk_total'] = f"{size_bytes/to_gb:.1f}GB"
                resources['disk_free'] = f"{free_bytes/to_gb:.1f}GB"
                resources['disk_used'] = f"{used_bytes/to_gb:.1f}GB"
                resources['disk_usage'] = (
                    used_bytes/size_bytes*100.0) if size_bytes > 0 else 0.0
            except Exception:
                resources['disk_used'] = '0GB'
                resources['disk_total'] = '0GB'
                resources['disk_free'] = '0GB'
                resources['disk_usage'] = 0.0

            # Uptime
            stdin, stdout, stderr = client.exec_command(
                'powershell "(get-date) - (gcim Win32_OperatingSystem).LastBootUpTime"',
                timeout=10
            )
            uptime_output = stdout.read().decode('utf-8').strip()
            resources['uptime'] = uptime_output if uptime_output else 'Unknown'

            resources['load_average'] = 'N/A (Windows)'

            client.close()
            return resources

        except Exception as e:
            client.close()
            return {'error': f"Failed to get Windows resources: {str(e)}"}

    def test_sudo_access(self, server_config: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Test if the user has sudo privileges on the server.

        Args:
            server_config: Server configuration dictionary

        Returns:
            Tuple of (has_sudo, message)
        """
        client, error = self.create_ssh_client(server_config)

        if not client:
            return False, f"SSH connection failed: {error}"

        try:
            # Test sudo access without password first
            stdin, stdout, stderr = client.exec_command(
                'sudo -n true', timeout=5)
            exit_status = stdout.channel.recv_exit_status()

            if exit_status == 0:
                client.close()
                return True, "User has passwordless sudo privileges"
            else:
                # Check if user has sudo with password
                ssh_password = server_config.get('ssh_password')
                if ssh_password:
                    # Test sudo with password
                    stdin, stdout, stderr = client.exec_command(
                        f'echo "{ssh_password}" | sudo -S true',
                        timeout=5
                    )
                    exit_status = stdout.channel.recv_exit_status()

                    if exit_status == 0:
                        client.close()
                        return True, "User has sudo privileges (requires password)"
                    else:
                        stderr_text = stderr.read().decode('utf-8').strip()
                        client.close()
                        return False, f"Sudo failed even with password: {stderr_text}"
                else:
                    # No password available to test
                    stderr_text = stderr.read().decode('utf-8').strip()
                    client.close()
                    if "password is required" in stderr_text.lower():
                        return False, "User requires password for sudo (no password configured in app)"
                    else:
                        return False, f"User does not have sudo privileges: {stderr_text}"

        except Exception as e:
            client.close()
            return False, f"Failed to test sudo access: {str(e)}"

    def get_system_info(self, server_config: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Get basic system information from the server.

        Args:
            server_config: Server configuration dictionary

        Returns:
            Tuple of (success, system_info)
        """
        client, error = self.create_ssh_client(server_config)

        if not client:
            return False, f"SSH connection failed: {error}"

        try:
            # Get system information
            commands = [
                'uname -a',                    # System information
                'uptime',                      # Uptime
                'whoami',                      # Current user
                'sudo -n systemctl is-active systemd-logind 2>/dev/null || echo "no-systemd"'  # Check systemd
            ]

            info_lines = []
            for cmd in commands:
                stdin, stdout, stderr = client.exec_command(cmd, timeout=5)
                output = stdout.read().decode('utf-8').strip()
                if output:
                    info_lines.append(f"{cmd}: {output}")

            client.close()
            return True, "\n".join(info_lines)

        except Exception as e:
            client.close()
            return False, f"Failed to get system info: {str(e)}"

    def execute_command(self, server_config: Dict[str, Any], command: str) -> Tuple[bool, str, str]:
        """
        Execute a command on the server via SSH.

        Args:
            server_config: Server configuration dictionary
            command: Command to execute

        Returns:
            Tuple of (success, stdout, stderr)
        """
        client, error = self.create_ssh_client(server_config)

        if not client:
            return False, "", f"SSH connection failed: {error}"

        try:
            stdin, stdout, stderr = client.exec_command(command, timeout=30)

            stdout_text = stdout.read().decode('utf-8')
            stderr_text = stderr.read().decode('utf-8')

            client.close()
            return True, stdout_text, stderr_text

        except Exception as e:
            client.close()
            return False, "", f"Command execution failed: {str(e)}"


def async_operation(func, *args, **kwargs):
    """
    Run a function asynchronously in a separate thread.

    Args:
        func: Function to execute
        *args: Function arguments
        **kwargs: Function keyword arguments

    Returns:
        Thread object
    """
    thread = threading.Thread(target=func, args=args, kwargs=kwargs)
    thread.daemon = True
    thread.start()
    return thread


class TelegramClient:
    """Unified Telethon user-session client (Bot API removed)."""

    def __init__(self, token: str, chat_id: str, timeout: int = 10):
        self.token = token  # retained only if future features need it
        self.chat_id = chat_id
        self.timeout = timeout

    def get_recent_messages(self, limit: int = 50) -> Tuple[bool, Any]:
        """Return the newest messages up to limit (chronological ascending)."""
        ok, data = self.get_full_history(limit=limit)
        if not ok:
            return ok, data
        # get_full_history already returns oldest->newest order after reversal
        if len(data) > limit:
            data = data[-limit:]
        return True, data

    def send_message(self, text: str) -> Tuple[bool, Any]:
        """Send message using user session."""
        if not _HAS_TELETHON:
            return False, "Telethon not installed"
        api_id = os.environ.get('TELEGRAM_API_ID')
        api_hash = os.environ.get('TELEGRAM_API_HASH')
        if not (api_id and api_hash):
            return False, "API credentials not set"
        try:
            api_id_int = int(api_id)
            if not (0 < api_id_int < 2147483647):
                return False, f"Invalid TELEGRAM_API_ID range: {api_id_int}"
        except Exception:
            return False, "Invalid TELEGRAM_API_ID"
        session_path = os.path.join(
            os.path.expanduser('~'), '.cobaltax_user_session')
        if not os.path.exists(session_path + '.session') and not os.path.exists(session_path):
            return False, "User session missing. Run scripts/telegram_login.py"
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            with _TLClient(session_path, api_id_int, api_hash) as tl:
                tl.connect()
                if not tl.is_user_authorized():
                    return False, "Session unauthorized"
                # Resolve entity robustly
                entity = self._resolve_entity(tl, self.chat_id)
                if entity is None:
                    return False, f"Cannot resolve chat id {self.chat_id}. Ensure the account has joined the chat."
                sent = tl.send_message(entity, text)
                return True, getattr(sent, 'id', None)
        except Exception as e:
            return False, f"Send failed: {e}"
        finally:
            try:
                loop.run_until_complete(asyncio.sleep(0))
            except Exception:
                pass
            asyncio.set_event_loop(None)
            loop.close()

    # --- Extended (user session) history retrieval via Telethon ---
    def get_full_history(self, limit: int = 500) -> Tuple[bool, Any]:
        """Return message history using a user session (if available) via Telethon.

        This bypasses Bot API visibility limits by using a normal user account session.
        Requirements:
          - telethon installed
          - environment vars TELEGRAM_API_ID / TELEGRAM_API_HASH set
          - a previously created user session file (see scripts/telegram_login.py)

        If the user session doesn't exist, an instructional message is returned.
        """
        if not _HAS_TELETHON:
            return False, "Telethon not installed. Run 'pip install telethon'."
        api_id = os.environ.get('TELEGRAM_API_ID')
        api_hash = os.environ.get('TELEGRAM_API_HASH')
        if not (api_id and api_hash):
            return False, "TELEGRAM_API_ID / TELEGRAM_API_HASH not set in environment."
        try:
            api_id_int = int(api_id)
            if not (0 < api_id_int < 2147483647):
                return False, f"Invalid TELEGRAM_API_ID range: {api_id_int}"
        except Exception:
            return False, f"Invalid TELEGRAM_API_ID value: {api_id}"

        # Dedicated user session path
        session_path = os.path.join(
            os.path.expanduser('~'), '.cobaltax_user_session')
        if not os.path.exists(session_path + '.session') and not os.path.exists(session_path):
            return False, (
                "User session not found. Run 'python scripts/telegram_login.py' (will prompt in console) "
                "to create a user session so full history can be retrieved."
            )

        # Use a fresh event loop isolated from Tk thread
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            with _TLClient(session_path, api_id_int, api_hash) as tl:
                # If session is invalid this may raise prompting for code (cannot be answered here)
                try:
                    tl.connect()
                    if not tl.is_user_authorized():
                        return False, (
                            "User session not authorized (needs login). Re-run 'python scripts/telegram_login.py'."
                        )
                except Exception as e:
                    return False, f"Failed to connect user session: {e}"

                # Resolve entity with fallbacks (-100 prefix, dialog scan)
                entity = self._resolve_entity(tl, self.chat_id)
                if entity is None:
                    return False, (
                        f"Cannot find any entity for '{self.chat_id}'. "
                        "If it's a supergroup/channel, ensure the user session joined it. "
                        "You may need to open Telegram manually with that account first."
                    )
                try:
                    msgs = tl.get_messages(entity, limit=limit)
                except Exception as e:
                    return False, f"Failed to fetch messages: {e}"

                out = []
                for msg in reversed(list(msgs)):
                    text = (msg.message or '').strip()
                    if not text:
                        if msg.photo:
                            text = '[photo]'
                        elif msg.document:
                            name = 'document'
                            try:
                                for attr in getattr(msg.document, 'attributes', []) or []:
                                    name = getattr(
                                        attr, 'file_name', name) or name
                            except Exception:
                                pass
                            text = f'[document: {name}]'
                        elif msg.sticker:
                            text = '[sticker]'
                        elif msg.video:
                            text = '[video]'
                        elif msg.voice:
                            text = '[voice message]'
                        elif msg.audio:
                            text = '[audio]'
                        else:
                            text = '[non-text message]'
                    try:
                        dt = msg.date.replace(
                            tzinfo=None) if msg.date else None
                    except Exception:
                        dt = msg.date
                    out.append({'date': dt, 'text': text})
                return True, out
        finally:
            try:
                loop.run_until_complete(asyncio.sleep(0))
            except Exception:
                pass
            asyncio.set_event_loop(None)
            loop.close()

    def _resolve_entity(self, tl, chat_id: Any):
        """Attempt to resolve a chat/channel/user entity using multiple strategies.

        Strategies:
          1. Direct get_entity(chat_id) as provided.
          2. If string starts with -100 (supergroup/channel), try stripping prefix.
          3. If numeric string, convert to int.
          4. Iterate dialogs comparing id and derived -100{id} forms.
        Returns entity object or None.
        """
        # Fast path
        try:
            return tl.get_entity(chat_id)
        except Exception:
            pass
        raw = str(chat_id)
        candidates = []
        if raw.startswith('-100'):
            try:
                base = int(raw[4:])
                candidates.append(base)
            except Exception:
                pass
        # Numeric direct
        if raw.isdigit():
            try:
                candidates.append(int(raw))
            except Exception:
                pass
        # Try candidates
        for c in candidates:
            try:
                return tl.get_entity(c)
            except Exception:
                continue
        # Dialog scan (last resort)
        try:
            for d in tl.iter_dialogs():
                ent = d.entity
                ent_id = getattr(ent, 'id', None)
                if ent_id is None:
                    continue
                # Build comparable forms
                if str(ent_id) == raw:
                    return ent
                if raw.startswith('-100') and f"-100{ent_id}" == raw:
                    return ent
        except Exception:
            pass
        return None
