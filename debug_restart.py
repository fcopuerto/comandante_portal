#!/usr/bin/env python3
"""
Debug script to test server restart functionality
"""

from server_utils import ServerMonitor, SSHManager
from config import SERVERS
import sys
import os
sys.path.append(os.path.dirname(__file__))


def test_server_restart():
    """Test server restart functionality with detailed diagnostics."""
    print("🔧 CobaltaX Server Restart Debug Tool")
    print("=" * 50)

    if not SERVERS:
        print("❌ No servers configured in config.py")
        return

    ssh_manager = SSHManager()
    server_monitor = ServerMonitor()

    for i, server in enumerate(SERVERS, 1):
        print(f"\n🖥️  Testing Server {i}: {server['name']} ({server['ip']})")
        print("-" * 40)

        # Test basic connectivity
        print("1. Testing basic connectivity...")
        ping_result = server_monitor.ping_server(server['ip'])
        print(f"   Ping: {'✅ Success' if ping_result else '❌ Failed'}")

        if not ping_result:
            print("   ⚠️  Server unreachable - skipping SSH tests")
            continue

        # Test SSH port
        ssh_port = server.get('ssh_port', 22)
        port_result = server_monitor.check_port(server['ip'], ssh_port)
        print(
            f"   SSH Port {ssh_port}: {'✅ Open' if port_result else '❌ Closed'}")

        if not port_result:
            print("   ⚠️  SSH port closed - skipping SSH tests")
            continue

        # Test SSH connection
        print("2. Testing SSH connection...")
        client, error = ssh_manager.create_ssh_client(server)
        if client:
            print("   ✅ SSH connection successful")
            client.close()
        else:
            print(f"   ❌ SSH connection failed: {error}")
            continue

        # Test sudo access
        print("3. Testing sudo privileges...")
        has_sudo, sudo_msg = ssh_manager.test_sudo_access(server)
        print(f"   Sudo access: {'✅' if has_sudo else '❌'} {sudo_msg}")

        # Get system info
        print("4. Getting system information...")
        info_success, system_info = ssh_manager.get_system_info(server)
        if info_success:
            print("   ✅ System info retrieved:")
            for line in system_info.split('\n'):
                print(f"      {line}")
        else:
            print(f"   ❌ Failed to get system info: {system_info}")

        # Test restart (ask for confirmation)
        if has_sudo:
            print("\n5. Restart test options:")
            print("   [y] - Test restart command (WILL RESTART THE SERVER)")
            print("   [d] - Dry run (test without actually restarting)")
            print("   [s] - Skip restart test")

            choice = input("   Choose option [y/d/s]: ").lower().strip()

            if choice == 'y':
                print("   ⚠️  RESTARTING SERVER...")
                success, message = ssh_manager.restart_server(server)
                print(
                    f"   Restart result: {'✅' if success else '❌'} {message}")

            elif choice == 'd':
                print("   🧪 Dry run - testing restart commands without execution...")
                client, error = ssh_manager.create_ssh_client(server)
                if client:
                    # Test each restart command availability
                    restart_commands = [
                        'which systemctl',
                        'which shutdown',
                        'which reboot',
                        'ls -la /sbin/reboot'
                    ]

                    for cmd in restart_commands:
                        try:
                            stdin, stdout, stderr = client.exec_command(
                                cmd, timeout=3)
                            exit_status = stdout.channel.recv_exit_status()
                            output = stdout.read().decode('utf-8').strip()
                            if exit_status == 0 and output:
                                print(f"      ✅ {cmd}: {output}")
                            else:
                                print(f"      ❌ {cmd}: Not found")
                        except Exception as e:
                            print(f"      ❌ {cmd}: Error - {e}")

                    client.close()
                    print("   ✅ Dry run completed")
                else:
                    print(f"   ❌ SSH connection failed for dry run: {error}")
            else:
                print("   ⏭️  Skipping restart test")
        else:
            print("   ⚠️  Cannot test restart - no sudo privileges")

        print(f"\n✅ Server {i} testing completed")

    print("\n🏁 All tests completed!")
    print("\nTroubleshooting tips:")
    print("• Ensure SSH user has passwordless sudo access")
    print("• Check firewall settings on servers")
    print("• Verify SSH key authentication is working")
    print("• Make sure servers support systemd or traditional shutdown commands")


if __name__ == "__main__":
    test_server_restart()
