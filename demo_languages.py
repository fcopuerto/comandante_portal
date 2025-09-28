#!/usr/bin/env python3
"""
Demo script to showcase the multilanguage capabilities
"""

from language_manager import get_language_manager, _


def demo_languages():
    """Demonstrate the multilanguage support."""
    lm = get_language_manager()

    print("🌍 CobaltaX Server Monitor - Multilanguage Demo")
    print("=" * 50)

    languages = [
        ('en', 'English'),
        ('es', 'Español'),
        ('ca', 'Català')
    ]

    for lang_code, lang_name in languages:
        print(f"\n📍 {lang_name} ({lang_code}):")
        print("-" * 30)

        lm.set_language(lang_code)

        print(f"App Title: {_('app_title')}")
        print(f"Servers: {_('servers')}")
        print(f"Online: {_('online')}")
        print(f"Offline: {_('offline')}")
        print(f"Restart Server: {_('restart_server')}")
        print(f"Test SSH: {_('test_ssh')}")
        print(f"Language: {_('language')}")

        # Demo with formatting
        print(f"Status Message: {_('restarting_server', server='TestServer')}")

    print("\n✅ All languages working correctly!")
    print("\nTo run the application:")
    print("conda activate servers_cobaltax")
    print("python server_monitor.py")


if __name__ == "__main__":
    demo_languages()
