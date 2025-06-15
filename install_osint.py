#!/usr/bin/env python3
"""
Système d'Analyse OSINT - Script d'Installation Principal
Installation automatique du système complet d'analyse de documents OSINT
"""

import sys
import subprocess
import os
import json
import shutil
from pathlib import Path
import platform

class OSINTMasterInstaller:
    def __init__(self):
        self.system_name = "OSINT Ukraine Analysis System"
        self.version = "1.0.0"
        self.base_path = Path.cwd()
        self.errors = []
        self.warnings = []

    def print_header(self):
        print("=" * 60)
        print(f"🚀 {self.system_name}")
        print(f"📦 Version {self.version}")
        print("=" * 60)
        print()

    def check_python_version(self):
        """Vérifier la version Python"""
        print("🔍 Vérification de la version Python...")
        if sys.version_info < (3, 7):
            self.errors.append("Python 3.7+ requis. Version actuelle: " + sys.version)
            return False
        print(f"✅ Python {sys.version.split()[0]} détecté")
        return True

    def install_packages(self):
        """Installer les packages Python requis"""
        print("📦 Installation des dépendances Python...")

        packages = [
            "google-auth>=2.0.0",
            "google-auth-oauthlib>=0.5.0", 
            "google-auth-httplib2>=0.1.0",
            "google-api-python-client>=2.0.0",
            "requests>=2.25.0",
            "python-dotenv>=0.19.0",
            "schedule>=1.1.0",
            "watchdog>=2.1.0",
            "Pillow>=8.0.0",
            "PyPDF2>=2.0.0",
            "python-dateutil>=2.8.0",
            "tqdm>=4.62.0",
            "colorama>=0.4.4",
            "cryptography>=3.4.8",
            "lxml>=4.6.0",
            "beautifulsoup4>=4.10.0"
        ]

        try:
            for package in packages:
                print(f"  📥 Installation de {package.split('>=')[0]}...")
                result = subprocess.run([
                    sys.executable, "-m", "pip", "install", package
                ], capture_output=True, text=True)

                if result.returncode != 0:
                    self.errors.append(f"Erreur installation {package}: {result.stderr}")

            print("✅ Dépendances installées")
            return True
        except Exception as e:
            self.errors.append(f"Erreur installation packages: {str(e)}")
            return False

    def setup_project_structure(self):
        """Créer la structure du projet"""
        print("📁 Création de la structure du projet...")

        directories = [
            "Raw Documents",
            "Processed Documents", 
            "Syntheses",
            "Templates",
            "Scripts",
            "Logs",
            "Config",
            "Backup"
        ]

        try:
            for directory in directories:
                dir_path = self.base_path / directory
                dir_path.mkdir(exist_ok=True)
                print(f"  📂 {directory}")

            print("✅ Structure créée")
            return True
        except Exception as e:
            self.errors.append(f"Erreur création structure: {str(e)}")
            return False

    def setup_config_files(self):
        """Configurer les fichiers de configuration"""
        print("⚙️ Configuration des fichiers...")

        try:
            # Créer .env template
            env_content = """# Configuration Système OSINT
SYSTEM_NAME="OSINT Ukraine Analysis"
GOOGLE_DRIVE_FOLDER_ID=""
OCR_API_KEY=""
LOG_LEVEL=INFO
SYNC_INTERVAL=3600
"""

            with open(self.base_path / ".env.template", "w", encoding="utf-8") as f:
                f.write(env_content)

            # Créer gitignore
            gitignore_content = """# Fichiers sensibles
.env
credentials.json
token.json

# Cache Python
__pycache__/
*.pyc
*.pyo

# Logs
*.log
Logs/

# Données temporaires
temp/
tmp/

# OS
.DS_Store
Thumbs.db
"""

            with open(self.base_path / ".gitignore", "w", encoding="utf-8") as f:
                f.write(gitignore_content)

            print("✅ Fichiers de configuration créés")
            return True
        except Exception as e:
            self.errors.append(f"Erreur configuration: {str(e)}")
            return False

    def create_launcher_scripts(self):
        """Créer les scripts de lancement"""
        print("🚀 Création des scripts de lancement...")

        try:
            # Script Windows
            bat_content = """@echo off
echo === Système OSINT Ukraine ===
echo.

if not exist "venv" (
    echo Creation environnement virtuel...
    python -m venv venv
)

echo Activation environnement...
call venv\Scripts\activate.bat

echo Lancement synchronisation...
python sync_gdrive.py

pause
"""
            with open(self.base_path / "start_osint.bat", "w", encoding="utf-8") as f:
                f.write(bat_content)

            # Script Unix
            sh_content = """#!/bin/bash
echo "=== Système OSINT Ukraine ==="
echo

if [ ! -d "venv" ]; then
    echo "Création environnement virtuel..."
    python3 -m venv venv
fi

echo "Activation environnement..."
source venv/bin/activate

echo "Lancement synchronisation..."
python3 sync_gdrive.py
"""
            with open(self.base_path / "start_osint.sh", "w", encoding="utf-8") as f:
                f.write(sh_content)

            # Rendre exécutable sur Unix
            if platform.system() != "Windows":
                import stat
                os.chmod(self.base_path / "start_osint.sh", stat.S_IRWXU | stat.S_IRGRP | stat.S_IROTH)

            print("✅ Scripts de lancement créés")
            return True
        except Exception as e:
            self.errors.append(f"Erreur scripts lancement: {str(e)}")
            return False

    def create_requirements_file(self):
        """Créer le fichier requirements.txt"""
        print("📋 Génération requirements.txt...")

        requirements = """# Système OSINT Ukraine - Dépendances
google-auth>=2.0.0
google-auth-oauthlib>=0.5.0
google-auth-httplib2>=0.1.0
google-api-python-client>=2.0.0
requests>=2.25.0
python-dotenv>=0.19.0
schedule>=1.1.0
watchdog>=2.1.0
Pillow>=8.0.0
PyPDF2>=2.0.0
python-dateutil>=2.8.0
tqdm>=4.62.0
colorama>=0.4.4
cryptography>=3.4.8
lxml>=4.6.0
beautifulsoup4>=4.10.0
"""

        try:
            with open(self.base_path / "requirements.txt", "w", encoding="utf-8") as f:
                f.write(requirements)
            print("✅ requirements.txt créé")
            return True
        except Exception as e:
            self.errors.append(f"Erreur requirements.txt: {str(e)}")
            return False

    def run_initial_tests(self):
        """Exécuter les tests initiaux"""
        print("🧪 Tests initiaux du système...")

        try:
            # Test import des modules principaux
            test_imports = [
                "google.auth",
                "googleapiclient.discovery", 
                "requests",
                "dotenv",
                "schedule",
                "PIL"
            ]

            for module in test_imports:
                try:
                    __import__(module)
                    print(f"  ✅ {module}")
                except ImportError:
                    self.warnings.append(f"Module {module} non disponible")
                    print(f"  ⚠️ {module}")

            print("✅ Tests terminés")
            return True
        except Exception as e:
            self.errors.append(f"Erreur tests: {str(e)}")
            return False

    def generate_report(self):
        """Générer le rapport d'installation"""
        print()
        print("=" * 60)
        print("📊 RAPPORT D'INSTALLATION")
        print("=" * 60)

        if not self.errors:
            print("🎉 INSTALLATION RÉUSSIE!")
            print()
            print("📁 Structure créée:")
            print("  ├── Raw Documents/     (Déposez vos PDFs ici)")
            print("  ├── Scripts/           (Scripts système)")  
            print("  ├── Config/            (Configuration)")
            print("  └── Logs/              (Journaux)")
            print()
            print("🚀 Prochaines étapes:")
            print("  1. Configurez Google Drive API (GUIDE_GOOGLE_DRIVE.md)")
            print("  2. Modifiez .env avec vos paramètres")
            print("  3. Lancez: python setup_gdrive.py")
            print("  4. Testez: python test_system.py")
            print("  5. Démarrez: ./start_osint.sh (ou start_osint.bat)")

        elif len(self.errors) < 3:
            print("⚠️ INSTALLATION PARTIELLE")
            print("Quelques erreurs mais système utilisable:")
            for error in self.errors:
                print(f"  • {error}")

        else:
            print("❌ ÉCHEC INSTALLATION")
            print("Erreurs critiques:")
            for error in self.errors:
                print(f"  • {error}")

        if self.warnings:
            print()
            print("⚠️ Avertissements:")
            for warning in self.warnings:
                print(f"  • {warning}")

        print("=" * 60)

    def install(self):
        """Processus d'installation principal"""
        self.print_header()

        steps = [
            ("Version Python", self.check_python_version),
            ("Packages Python", self.install_packages),
            ("Structure projet", self.setup_project_structure),
            ("Fichiers config", self.setup_config_files),
            ("Scripts lancement", self.create_launcher_scripts),
            ("Requirements", self.create_requirements_file),
            ("Tests initiaux", self.run_initial_tests)
        ]

        for step_name, step_func in steps:
            print(f"▶️ {step_name}...")
            if not step_func():
                print(f"❌ Échec: {step_name}")
            print()

        self.generate_report()

def main():
    installer = OSINTMasterInstaller()
    installer.install()

if __name__ == "__main__":
    main()
