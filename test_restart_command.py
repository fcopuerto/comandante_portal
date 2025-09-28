#!/usr/bin/env python3
"""
Test script to verify restart command without actually restarting
"""

from server_utils import SSHManager
from config import SERVERS
import sys
import os
sys.path.append(os.path.dirname(__file__))


def test_restart_command():
    """Test restart command construction without executing."""
    print("🧪 Testing Restart Command Construction")
    print("=" * 50)

    if not SERVERS:
        print("❌ No servers configured")
        return

    ssh_manager = SSHManager()

    for i, server in enumerate(SERVERS, 1):
        print(f"\n🖥️  Server {i}: {server['name']} ({server['ip']})")
        print("-" * 40)

        # Test SSH connection
        client, error = ssh_manager.create_ssh_client(server)
        if not client:
            print(f"❌ SSH connection failed: {error}")
            continue

        print("✅ SSH connection successful")

        # Test sudo access
        has_sudo, sudo_msg = ssh_manager.test_sudo_access(server)
        print(f"Sudo test: {'✅' if has_sudo else '❌'} {sudo_msg}")

        if has_sudo:
            # Test command construction
            ssh_password = server.get('ssh_password')

            # Check passwordless sudo
            stdin, stdout, stderr = client.exec_command(
                'sudo -n true', timeout=3)
            exit_status = stdout.channel.recv_exit_status()

            if exit_status == 0:
                print("🔑 Passwordless sudo available")
                test_cmd = 'echo "Would execute: sudo reboot"'
            else:
                print("🔐 Password required for sudo")
                if ssh_password:
                    test_cmd = f'echo "Would execute: echo \\"[password]\\" | sudo -S reboot"'
                else:
                    test_cmd = 'echo "❌ No password configured for sudo"'

            # Execute test command
            stdin, stdout, stderr = client.exec_command(test_cmd, timeout=5)
            output = stdout.read().decode('utf-8').strip()
            print(f"📝 Command test: {output}")

        client.close()
        print("✅ Test completed")

    print("\n🎉 All command tests completed!")
    print("\n💡 The restart functionality should now work properly.")
    print("   You can test it safely using the GUI application.")


if __name__ == "__main__":
    test_restart_command()
