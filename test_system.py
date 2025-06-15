#!/usr/bin/env python3
"""
Tests système complets pour le système OSINT
Validation de tous les composants et de leur intégration
"""

import os
import sys
import json
import pickle
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
import logging

# Configuration des couleurs pour l'affichage
try:
    from colorama import init, Fore, Style
    init()

    class Colors:
        GREEN = Fore.GREEN
        RED = Fore.RED
        YELLOW = Fore.YELLOW
        BLUE = Fore.BLUE
        CYAN = Fore.CYAN
        RESET = Style.RESET_ALL
        BOLD = Style.BRIGHT

except ImportError:
    class Colors:
        GREEN = RED = YELLOW = BLUE = CYAN = RESET = BOLD = ""

class OSINTSystemTester:
    def __init__(self):
        self.base_path = Path.cwd()
        self.errors = []
        self.warnings = []
        self.passed_tests = []
        self.failed_tests = []

        # Configuration du logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('test_system.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def print_header(self):
        """Afficher l'en-tête des tests"""
        print(f"{Colors.BLUE}{Colors.BOLD}")
        print("=" * 70)
        print("🧪 TESTS SYSTÈME OSINT UKRAINE")
        print("📊 Validation complète des composants")
        print("=" * 70)
        print(f"{Colors.RESET}")

    def print_test_start(self, test_name):
        """Afficher le début d'un test"""
        print(f"{Colors.CYAN}▶️ Test: {test_name}...{Colors.RESET}")

    def print_success(self, message):
        """Afficher un succès"""
        print(f"{Colors.GREEN}✅ {message}{Colors.RESET}")

    def print_error(self, message):
        """Afficher une erreur"""
        print(f"{Colors.RED}❌ {message}{Colors.RESET}")

    def print_warning(self, message):
        """Afficher un avertissement"""
        print(f"{Colors.YELLOW}⚠️ {message}{Colors.RESET}")

    def test_file_structure(self):
        """Tester la structure des fichiers"""
        self.print_test_start("Structure des fichiers")

        required_files = [
            "install_osint.py",
            "setup_gdrive.py", 
            "sync_gdrive.py",
            "start_osint.sh",
            "start_osint.bat",
            "requirements.txt",
            "config_template.json"
        ]

        missing_files = []
        for file in required_files:
            file_path = self.base_path / file
            if file_path.exists():
                self.print_success(f"Fichier trouvé: {file}")
            else:
                missing_files.append(file)
                self.print_error(f"Fichier manquant: {file}")

        if missing_files:
            self.failed_tests.append("Structure des fichiers")
            self.errors.append(f"Fichiers manquants: {', '.join(missing_files)}")
            return False
        else:
            self.passed_tests.append("Structure des fichiers")
            return True

    def test_directories(self):
        """Tester la structure des dossiers"""
        self.print_test_start("Structure des dossiers")

        required_dirs = [
            "Raw Documents",
            "Processed Documents",
            "Syntheses", 
            "Templates",
            "Logs",
            "Config"
        ]

        created_dirs = []
        for directory in required_dirs:
            dir_path = self.base_path / directory
            if not dir_path.exists():
                try:
                    dir_path.mkdir(exist_ok=True)
                    created_dirs.append(directory)
                    self.print_success(f"Dossier créé: {directory}")
                except Exception as e:
                    self.print_error(f"Erreur création {directory}: {e}")
                    self.failed_tests.append("Structure des dossiers")
                    return False
            else:
                self.print_success(f"Dossier existant: {directory}")

        if created_dirs:
            self.print_warning(f"Dossiers créés: {', '.join(created_dirs)}")

        self.passed_tests.append("Structure des dossiers")
        return True

    def test_python_dependencies(self):
        """Tester les dépendances Python"""
        self.print_test_start("Dépendances Python")

        required_modules = [
            ("google.auth", "google-auth"),
            ("googleapiclient.discovery", "google-api-python-client"),
            ("requests", "requests"),
            ("dotenv", "python-dotenv"),
            ("schedule", "schedule"),
            ("watchdog", "watchdog"),
            ("PIL", "Pillow"),
            ("PyPDF2", "PyPDF2"),
            ("tqdm", "tqdm"),
            ("colorama", "colorama")
        ]

        missing_modules = []
        for module_name, package_name in required_modules:
            try:
                __import__(module_name)
                self.print_success(f"Module disponible: {module_name}")
            except ImportError:
                missing_modules.append(package_name)
                self.print_error(f"Module manquant: {module_name}")

        if missing_modules:
            self.failed_tests.append("Dépendances Python")
            self.errors.append(f"Installez: pip install {' '.join(missing_modules)}")
            return False
        else:
            self.passed_tests.append("Dépendances Python")
            return True

    def test_google_credentials(self):
        """Tester les identifiants Google"""
        self.print_test_start("Identifiants Google Drive")

        credentials_file = self.base_path / "credentials.json"
        token_file = self.base_path / "token.json"

        if not credentials_file.exists():
            self.print_error("credentials.json manquant")
            self.warnings.append("Lancez setup_gdrive.py pour configurer")
            self.failed_tests.append("Identifiants Google")
            return False

        try:
            with open(credentials_file, 'r') as f:
                creds_data = json.load(f)

            if "installed" in creds_data and "client_id" in creds_data["installed"]:
                self.print_success("credentials.json valide")
            else:
                self.print_error("credentials.json invalide")
                self.failed_tests.append("Identifiants Google")
                return False

        except Exception as e:
            self.print_error(f"Erreur lecture credentials.json: {e}")
            self.failed_tests.append("Identifiants Google")
            return False

        if token_file.exists():
            try:
                with open(token_file, 'rb') as f:
                    pickle.load(f)
                self.print_success("token.json valide")
            except Exception as e:
                self.print_warning(f"token.json corrompu: {e}")

        self.passed_tests.append("Identifiants Google")
        return True

    def test_google_drive_connection(self):
        """Tester la connexion Google Drive"""
        self.print_test_start("Connexion Google Drive")

        try:
            # Import des modules Google
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            import pickle

            token_file = self.base_path / "token.json"
            if not token_file.exists():
                self.print_warning("Token manquant - lancez setup_gdrive.py")
                self.warnings.append("Connexion Google Drive non testée")
                return True  # Pas d'erreur bloquante

            # Charger le token
            with open(token_file, 'rb') as f:
                creds = pickle.load(f)

            # Créer le service
            service = build('drive', 'v3', credentials=creds)

            # Test simple
            results = service.files().list(pageSize=1).execute()

            self.print_success("Connexion Google Drive OK")
            self.passed_tests.append("Connexion Google Drive")
            return True

        except Exception as e:
            self.print_error(f"Erreur connexion Google Drive: {e}")
            self.warnings.append("Vérifiez la configuration Google Drive")
            return True  # Non bloquant pour les autres tests

    def test_ocr_configuration(self):
        """Tester la configuration OCR"""
        self.print_test_start("Configuration OCR")

        # Vérifier si la clé API est configurée
        ocr_api_key = os.environ.get('OCR_API_KEY')

        if not ocr_api_key:
            self.print_warning("Clé API OCR.space non configurée")
            self.warnings.append("Configurez OCR_API_KEY pour l'OCR automatique")
        else:
            self.print_success("Clé API OCR configurée")

        # Test de connexion OCR
        try:
            import requests

            test_url = "https://api.ocr.space/parse/image"
            response = requests.get(test_url, timeout=5)

            if response.status_code == 200:
                self.print_success("Service OCR.space accessible")
            else:
                self.print_warning("Service OCR.space inaccessible")

        except Exception as e:
            self.print_warning(f"Test OCR échoué: {e}")

        self.passed_tests.append("Configuration OCR")
        return True

    def test_environment_variables(self):
        """Tester les variables d'environnement"""
        self.print_test_start("Variables d'environnement")

        env_file = self.base_path / ".env"
        env_template = self.base_path / ".env.template"

        if env_file.exists():
            self.print_success(".env trouvé")
            try:
                from dotenv import load_dotenv
                load_dotenv()
                self.print_success("Variables d'environnement chargées")
            except Exception as e:
                self.print_error(f"Erreur chargement .env: {e}")
        else:
            if env_template.exists():
                self.print_warning(".env manquant, template disponible")
                self.warnings.append("Copiez .env.template vers .env et configurez")
            else:
                self.print_warning("Aucun fichier d'environnement")

        self.passed_tests.append("Variables d'environnement")
        return True

    def test_configuration_files(self):
        """Tester les fichiers de configuration"""
        self.print_test_start("Fichiers de configuration")

        config_file = self.base_path / "config.json"
        config_template = self.base_path / "config_template.json"

        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                self.print_success("config.json valide")

                # Vérifier les sections principales
                required_sections = ["system", "google_drive", "osint_domains"]
                for section in required_sections:
                    if section in config:
                        self.print_success(f"Section {section} présente")
                    else:
                        self.print_warning(f"Section {section} manquante")

            except Exception as e:
                self.print_error(f"config.json invalide: {e}")
                self.failed_tests.append("Fichiers de configuration")
                return False
        else:
            if config_template.exists():
                self.print_warning("config.json manquant, template disponible")
                self.warnings.append("Lancez setup_gdrive.py pour générer config.json")
            else:
                self.print_error("Aucun fichier de configuration")
                self.failed_tests.append("Fichiers de configuration")
                return False

        self.passed_tests.append("Fichiers de configuration")
        return True

    def test_log_system(self):
        """Tester le système de logs"""
        self.print_test_start("Système de logs")

        logs_dir = self.base_path / "Logs"
        logs_dir.mkdir(exist_ok=True)

        # Test d'écriture de log
        test_log_file = logs_dir / "test.log"
        try:
            with open(test_log_file, 'w') as f:
                f.write(f"Test log - {datetime.now().isoformat()}\n")
            self.print_success("Écriture de logs OK")

            # Nettoyer
            test_log_file.unlink()

        except Exception as e:
            self.print_error(f"Erreur écriture logs: {e}")
            self.failed_tests.append("Système de logs")
            return False

        self.passed_tests.append("Système de logs")
        return True

    def test_file_creation(self):
        """Tester la création de fichiers"""
        self.print_test_start("Création de fichiers")

        try:
            # Test création fichier temporaire
            test_file = self.base_path / "test_temp.txt"
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("Test OSINT System\n")
                f.write(f"Date: {datetime.now().isoformat()}\n")

            self.print_success("Création de fichier OK")

            # Vérification lecture
            with open(test_file, 'r', encoding='utf-8') as f:
                content = f.read()

            if "Test OSINT System" in content:
                self.print_success("Lecture de fichier OK")
            else:
                self.print_error("Erreur lecture fichier")

            # Nettoyer
            test_file.unlink()

        except Exception as e:
            self.print_error(f"Erreur création fichier: {e}")
            self.failed_tests.append("Création de fichiers")
            return False

        self.passed_tests.append("Création de fichiers")
        return True

    def generate_report(self):
        """Générer le rapport de tests"""
        print()
        print(f"{Colors.BLUE}{Colors.BOLD}")
        print("=" * 70)
        print("📊 RAPPORT DE TESTS")
        print("=" * 70)
        print(f"{Colors.RESET}")

        total_tests = len(self.passed_tests) + len(self.failed_tests)
        success_rate = (len(self.passed_tests) / total_tests) * 100 if total_tests > 0 else 0

        print(f"{Colors.CYAN}📈 STATISTIQUES:{Colors.RESET}")
        print(f"  Total tests: {total_tests}")
        print(f"  Réussis: {Colors.GREEN}{len(self.passed_tests)}{Colors.RESET}")
        print(f"  Échoués: {Colors.RED}{len(self.failed_tests)}{Colors.RESET}")
        print(f"  Taux de réussite: {Colors.BOLD}{success_rate:.1f}%{Colors.RESET}")
        print()

        if self.passed_tests:
            print(f"{Colors.GREEN}✅ TESTS RÉUSSIS:{Colors.RESET}")
            for test in self.passed_tests:
                print(f"  • {test}")
            print()

        if self.failed_tests:
            print(f"{Colors.RED}❌ TESTS ÉCHOUÉS:{Colors.RESET}")
            for test in self.failed_tests:
                print(f"  • {test}")
            print()

        if self.warnings:
            print(f"{Colors.YELLOW}⚠️ AVERTISSEMENTS:{Colors.RESET}")
            for warning in self.warnings:
                print(f"  • {warning}")
            print()

        if self.errors:
            print(f"{Colors.RED}🚨 ERREURS:{Colors.RESET}")
            for error in self.errors:
                print(f"  • {error}")
            print()

        # Recommandations
        print(f"{Colors.CYAN}💡 RECOMMANDATIONS:{Colors.RESET}")

        if len(self.failed_tests) == 0:
            print(f"  {Colors.GREEN}🎉 Système prêt à l'emploi!{Colors.RESET}")
            print(f"  🚀 Lancez: ./start_osint.sh")
        elif len(self.failed_tests) <= 2:
            print(f"  {Colors.YELLOW}⚙️ Quelques ajustements nécessaires{Colors.RESET}")
            print(f"  🔧 Corrigez les erreurs puis relancez les tests")
        else:
            print(f"  {Colors.RED}🔧 Configuration requise{Colors.RESET}")
            print(f"  📋 Suivez le guide d'installation")

        print()
        print(f"{Colors.BLUE}=" * 70 + f"{Colors.RESET}")

        return len(self.failed_tests) == 0

    def run_all_tests(self):
        """Exécuter tous les tests"""
        self.print_header()
        print()

        tests = [
            ("Structure des fichiers", self.test_file_structure),
            ("Structure des dossiers", self.test_directories),
            ("Dépendances Python", self.test_python_dependencies),
            ("Identifiants Google", self.test_google_credentials),
            ("Connexion Google Drive", self.test_google_drive_connection),
            ("Configuration OCR", self.test_ocr_configuration),
            ("Variables d'environnement", self.test_environment_variables),
            ("Fichiers de configuration", self.test_configuration_files),
            ("Système de logs", self.test_log_system),
            ("Création de fichiers", self.test_file_creation)
        ]

        for test_name, test_func in tests:
            try:
                test_func()
            except Exception as e:
                self.print_error(f"Erreur test {test_name}: {e}")
                self.failed_tests.append(test_name)
                self.errors.append(f"Exception dans {test_name}: {str(e)}")
            print()

        success = self.generate_report()
        return success

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Tests système OSINT')
    parser.add_argument('--test', 
                       choices=['all', 'files', 'python', 'google', 'config'],
                       default='all',
                       help='Type de test à exécuter')

    args = parser.parse_args()

    tester = OSINTSystemTester()

    if args.test == 'all':
        success = tester.run_all_tests()
    elif args.test == 'files':
        success = tester.test_file_structure() and tester.test_directories()
    elif args.test == 'python':
        success = tester.test_python_dependencies()
    elif args.test == 'google':
        success = tester.test_google_credentials() and tester.test_google_drive_connection()
    elif args.test == 'config':
        success = tester.test_configuration_files()
    else:
        success = tester.run_all_tests()

    # Code de sortie
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
