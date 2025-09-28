# Language support module for CobaltaX Server Monitor
# Multilanguage support for English, Spanish, and Catalan

import json
import os


class LanguageManager:
    """Manages multilanguage support for the application."""

    def __init__(self, default_language='en'):
        self.current_language = default_language
        self.translations = {}
        self.available_languages = ['en', 'es', 'ca']
        self.load_translations()

    def load_translations(self):
        """Load all translation files."""
        translations_dir = os.path.join(
            os.path.dirname(__file__), 'translations')

        # Create translations directory if it doesn't exist
        if not os.path.exists(translations_dir):
            os.makedirs(translations_dir)

        # Load translation files
        for lang in self.available_languages:
            lang_file = os.path.join(translations_dir, f'{lang}.json')
            if os.path.exists(lang_file):
                try:
                    with open(lang_file, 'r', encoding='utf-8') as f:
                        self.translations[lang] = json.load(f)
                except (json.JSONDecodeError, IOError):
                    # If file is corrupted, use default translations
                    self.translations[lang] = self._get_default_translations(
                        lang)
            else:
                # Create default translation file
                self.translations[lang] = self._get_default_translations(lang)
                self._save_translation_file(lang)

    def _get_default_translations(self, language):
        """Get default translations for a language."""
        translations = {
            'en': {
                # Window and application
                'app_title': 'CobaltaX Server Monitor',
                'server_monitor': 'Server Monitor',

                # Buttons and controls
                'refresh': '🔄 Refresh',
                'auto_refresh': 'Auto-refresh',
                'restart_server': '🔄 Restart Server',
                'test_ssh': '🔗 Test SSH',
                'language': 'Language',

                # Status messages
                'online': 'Online',
                'offline': 'Offline',
                'ssh_port_closed': 'SSH Port Closed',
                'checking': 'Checking...',
                'ready': 'Ready',
                'last_checked': 'Last checked',
                'never': 'Never',

                # Server information
                'servers': 'Servers',
                'ip_address': 'IP',

                # Status bar messages
                'refreshing_status': 'Refreshing server status...',
                'status_refresh_completed': 'Status refresh completed',
                'restarting_server': 'Restarting {server}...',
                'restart_command_sent': 'Restart command sent to {server}',
                'restart_failed': 'Failed to restart {server}',
                'testing_ssh': 'Testing SSH to {server}...',
                'ssh_test_successful': 'SSH test to {server} successful',
                'ssh_test_failed': 'SSH test to {server} failed',
                'auto_refresh_enabled': 'Auto-refresh enabled',
                'auto_refresh_disabled': 'Auto-refresh disabled',

                # Dialogs
                'confirm_restart': 'Confirm Restart',
                'confirm_restart_message': 'Are you sure you want to restart {server} ({ip})?\n\nThis will cause a temporary service interruption.',
                'restart_initiated': 'Restart Initiated',
                'restart_initiated_message': 'Restart command sent to {server}.\n\nThe server should be back online in 1-2 minutes.\n\nMessage: {message}',
                'restart_failed_title': 'Restart Failed',
                'restart_failed_message': 'Failed to restart {server}.\n\nError: {message}',
                'ssh_test_result': 'SSH Test Result',
                'ssh_test_successful_message': 'SSH connection to {server} successful!\n\nYou can safely restart this server.',
                'ssh_test_failed_title': 'SSH Test Failed',
                'ssh_test_failed_message': 'SSH connection to {server} failed.\n\nError: {message}\n\nPlease check your SSH credentials and network connectivity.',

                # Language selection
                'english': 'English',
                'spanish': 'Español',
                'catalan': 'Català',

                # Menu items
                'file': 'File',
                'settings': 'Settings',
                'help': 'Help',
                'about': 'About',
                'exit': 'Exit'
            },

            'es': {
                # Window and application
                'app_title': 'Monitor de Servidores CobaltaX',
                'server_monitor': 'Monitor de Servidores',

                # Buttons and controls
                'refresh': '🔄 Actualizar',
                'auto_refresh': 'Auto-actualizar',
                'restart_server': '🔄 Reiniciar Servidor',
                'test_ssh': '🔗 Probar SSH',
                'language': 'Idioma',

                # Status messages
                'online': 'En línea',
                'offline': 'Desconectado',
                'ssh_port_closed': 'Puerto SSH Cerrado',
                'checking': 'Verificando...',
                'ready': 'Listo',
                'last_checked': 'Última verificación',
                'never': 'Nunca',

                # Server information
                'servers': 'Servidores',
                'ip_address': 'IP',

                # Status bar messages
                'refreshing_status': 'Actualizando estado de servidores...',
                'status_refresh_completed': 'Actualización de estado completada',
                'restarting_server': 'Reiniciando {server}...',
                'restart_command_sent': 'Comando de reinicio enviado a {server}',
                'restart_failed': 'Error al reiniciar {server}',
                'testing_ssh': 'Probando SSH a {server}...',
                'ssh_test_successful': 'Prueba SSH a {server} exitosa',
                'ssh_test_failed': 'Prueba SSH a {server} falló',
                'auto_refresh_enabled': 'Auto-actualización activada',
                'auto_refresh_disabled': 'Auto-actualización desactivada',

                # Dialogs
                'confirm_restart': 'Confirmar Reinicio',
                'confirm_restart_message': '¿Está seguro de que desea reiniciar {server} ({ip})?\n\nEsto causará una interrupción temporal del servicio.',
                'restart_initiated': 'Reinicio Iniciado',
                'restart_initiated_message': 'Comando de reinicio enviado a {server}.\n\nEl servidor debería estar en línea en 1-2 minutos.\n\nMensaje: {message}',
                'restart_failed_title': 'Reinicio Falló',
                'restart_failed_message': 'Error al reiniciar {server}.\n\nError: {message}',
                'ssh_test_result': 'Resultado de Prueba SSH',
                'ssh_test_successful_message': '¡Conexión SSH a {server} exitosa!\n\nPuede reiniciar este servidor de forma segura.',
                'ssh_test_failed_title': 'Prueba SSH Falló',
                'ssh_test_failed_message': 'Conexión SSH a {server} falló.\n\nError: {message}\n\nPor favor verifique sus credenciales SSH y conectividad de red.',

                # Language selection
                'english': 'English',
                'spanish': 'Español',
                'catalan': 'Català',

                # Menu items
                'file': 'Archivo',
                'settings': 'Configuración',
                'help': 'Ayuda',
                'about': 'Acerca de',
                'exit': 'Salir'
            },

            'ca': {
                # Window and application
                'app_title': 'Monitor de Servidors CobaltaX',
                'server_monitor': 'Monitor de Servidors',

                # Buttons and controls
                'refresh': '🔄 Actualitzar',
                'auto_refresh': 'Auto-actualitzar',
                'restart_server': '🔄 Reiniciar Servidor',
                'test_ssh': '🔗 Provar SSH',
                'language': 'Idioma',

                # Status messages
                'online': 'En línia',
                'offline': 'Desconnectat',
                'ssh_port_closed': 'Port SSH Tancat',
                'checking': 'Verificant...',
                'ready': 'Llest',
                'last_checked': 'Última verificació',
                'never': 'Mai',

                # Server information
                'servers': 'Servidors',
                'ip_address': 'IP',

                # Status bar messages
                'refreshing_status': 'Actualitzant estat dels servidors...',
                'status_refresh_completed': 'Actualització d\'estat completada',
                'restarting_server': 'Reiniciant {server}...',
                'restart_command_sent': 'Ordre de reinici enviat a {server}',
                'restart_failed': 'Error al reiniciar {server}',
                'testing_ssh': 'Provant SSH a {server}...',
                'ssh_test_successful': 'Prova SSH a {server} exitosa',
                'ssh_test_failed': 'Prova SSH a {server} ha fallat',
                'auto_refresh_enabled': 'Auto-actualització activada',
                'auto_refresh_disabled': 'Auto-actualització desactivada',

                # Dialogs
                'confirm_restart': 'Confirmar Reinici',
                'confirm_restart_message': 'Esteu segur que voleu reiniciar {server} ({ip})?\n\nAixò causarà una interrupció temporal del servei.',
                'restart_initiated': 'Reinici Iniciat',
                'restart_initiated_message': 'Ordre de reinici enviat a {server}.\n\nEl servidor hauria d\'estar en línia en 1-2 minuts.\n\nMissatge: {message}',
                'restart_failed_title': 'Reinici Ha Fallat',
                'restart_failed_message': 'Error al reiniciar {server}.\n\nError: {message}',
                'ssh_test_result': 'Resultat de Prova SSH',
                'ssh_test_successful_message': 'Connexió SSH a {server} exitosa!\n\nPodeu reiniciar aquest servidor de forma segura.',
                'ssh_test_failed_title': 'Prova SSH Ha Fallat',
                'ssh_test_failed_message': 'Connexió SSH a {server} ha fallat.\n\nError: {message}\n\nSi us plau, verifiqueu les vostres credencials SSH i connectivitat de xarxa.',

                # Language selection
                'english': 'English',
                'spanish': 'Español',
                'catalan': 'Català',

                # Menu items
                'file': 'Fitxer',
                'settings': 'Configuració',
                'help': 'Ajuda',
                'about': 'Quant a',
                'exit': 'Sortir'
            }
        }

        return translations.get(language, translations['en'])

    def _save_translation_file(self, language):
        """Save translation file for a language."""
        translations_dir = os.path.join(
            os.path.dirname(__file__), 'translations')
        lang_file = os.path.join(translations_dir, f'{language}.json')

        try:
            with open(lang_file, 'w', encoding='utf-8') as f:
                json.dump(self.translations[language],
                          f, ensure_ascii=False, indent=2)
        except IOError:
            pass  # Ignore file write errors

    def set_language(self, language):
        """Set the current language."""
        if language in self.available_languages:
            self.current_language = language
            return True
        return False

    def get_text(self, key, **kwargs):
        """Get translated text for a key with optional formatting."""
        if self.current_language not in self.translations:
            self.current_language = 'en'

        text = self.translations[self.current_language].get(key, key)

        # Format text with provided arguments
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError):
                pass  # Return original text if formatting fails

        return text

    def get_available_languages(self):
        """Get list of available languages with their display names."""
        return [
            ('en', self.get_text('english')),
            ('es', self.get_text('spanish')),
            ('ca', self.get_text('catalan'))
        ]


# Global language manager instance
_language_manager = None


def get_language_manager():
    """Get the global language manager instance."""
    global _language_manager
    if _language_manager is None:
        _language_manager = LanguageManager()
    return _language_manager


def _(key, **kwargs):
    """Shortcut function for getting translated text."""
    return get_language_manager().get_text(key, **kwargs)
