#!/usr/bin/env python3
"""
Configuration Google Drive API pour le système OSINT
Gestion automatique de l'authentification et de la structure des dossiers
"""

import os
import json
import sys
import pickle
from pathlib import Path
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import logging

# Configuration des scopes Google Drive
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/drive.file'
]

class GoogleDriveSetup:
    def __init__(self):
        self.base_path = Path.cwd()
        self.credentials_file = self.base_path / "credentials.json"
        self.token_file = self.base_path / "token.json"
        self.config_file = self.base_path / "config.json"
        self.service = None
        self.folder_structure = {
            "OSINT-Ukraine-Analysis": {
                "Raw Documents": {},
                "Processed Documents": {
                    "Sauvetage Combat": {},
                    "Drones": {},
                    "Guerre Electronique": {},
                    "Organisation PC": {},
                    "Formation Personnel": {},
                    "Artillerie": {},
                    "Autres": {}
                },
                "Syntheses": {},
                "Archives": {},
                "Logs": {}
            }
        }

        # Configuration du logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('setup_gdrive.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def check_credentials(self):
        """Vérifier la présence du fichier credentials.json"""
        if not self.credentials_file.exists():
            print("❌ Fichier credentials.json manquant!")
            print()
            print("📋 Pour obtenir credentials.json:")
            print("1. Allez sur https://console.cloud.google.com/")
            print("2. Créez un projet ou sélectionnez-en un")
            print("3. Activez l'API Google Drive")
            print("4. Créez des identifiants OAuth 2.0")
            print("5. Téléchargez le fichier JSON")
            print("6. Renommez-le 'credentials.json'")
            print("7. Placez-le dans le dossier du projet")
            print()
            return False
        return True

    def authenticate(self):
        """Authentification Google Drive"""
        print("🔐 Authentification Google Drive...")

        creds = None

        # Charger le token existant
        if self.token_file.exists():
            try:
                with open(self.token_file, 'rb') as token:
                    creds = pickle.load(token)
            except Exception as e:
                self.logger.warning(f"Erreur chargement token: {e}")

        # Si pas de credentials valides, lancer le flow OAuth
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    print("✅ Token rafraîchi")
                except Exception as e:
                    self.logger.error(f"Erreur rafraîchissement: {e}")
                    creds = None

            if not creds:
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.credentials_file), SCOPES)
                    creds = flow.run_local_server(port=0)
                    print("✅ Authentification réussie")
                except Exception as e:
                    self.logger.error(f"Erreur authentification: {e}")
                    return False

            # Sauvegarder le token
            try:
                with open(self.token_file, 'wb') as token:
                    pickle.dump(creds, token)
                print("✅ Token sauvegardé")
            except Exception as e:
                self.logger.error(f"Erreur sauvegarde token: {e}")

        try:
            self.service = build('drive', 'v3', credentials=creds)
            print("✅ Service Google Drive initialisé")
            return True
        except Exception as e:
            self.logger.error(f"Erreur création service: {e}")
            return False

    def create_folder(self, name, parent_id=None):
        """Créer un dossier sur Google Drive"""
        try:
            folder_metadata = {
                'name': name,
                'mimeType': 'application/vnd.google-apps.folder'
            }

            if parent_id:
                folder_metadata['parents'] = [parent_id]

            folder = self.service.files().create(
                body=folder_metadata,
                fields='id'
            ).execute()

            folder_id = folder.get('id')
            self.logger.info(f"Dossier créé: {name} (ID: {folder_id})")
            return folder_id

        except HttpError as e:
            self.logger.error(f"Erreur création dossier {name}: {e}")
            return None

    def folder_exists(self, name, parent_id=None):
        """Vérifier si un dossier existe"""
        try:
            query = f"name='{name}' and mimeType='application/vnd.google-apps.folder'"
            if parent_id:
                query += f" and '{parent_id}' in parents"

            results = self.service.files().list(
                q=query,
                fields="files(id, name)"
            ).execute()

            files = results.get('files', [])
            return files[0]['id'] if files else None

        except HttpError as e:
            self.logger.error(f"Erreur recherche dossier {name}: {e}")
            return None

    def create_folder_structure(self, structure, parent_id=None, path=""):
        """Créer récursivement la structure de dossiers"""
        folder_map = {}

        for folder_name, subfolders in structure.items():
            current_path = f"{path}/{folder_name}" if path else folder_name
            print(f"📁 Création: {current_path}")

            # Vérifier si le dossier existe
            existing_id = self.folder_exists(folder_name, parent_id)

            if existing_id:
                print(f"  ✅ Dossier existant: {folder_name}")
                folder_id = existing_id
            else:
                folder_id = self.create_folder(folder_name, parent_id)
                if folder_id:
                    print(f"  ✅ Dossier créé: {folder_name}")
                else:
                    print(f"  ❌ Échec création: {folder_name}")
                    continue

            folder_map[folder_name] = folder_id

            # Créer les sous-dossiers
            if subfolders:
                subfolder_map = self.create_folder_structure(
                    subfolders, folder_id, current_path
                )
                folder_map.update(subfolder_map)

        return folder_map

    def setup_drive_structure(self):
        """Configurer la structure complète sur Google Drive"""
        print("🗂️ Configuration de la structure Google Drive...")

        folder_map = self.create_folder_structure(self.folder_structure)

        if folder_map:
            print(f"✅ {len(folder_map)} dossiers configurés")
            return folder_map
        else:
            print("❌ Erreur configuration structure")
            return None

    def save_configuration(self, folder_map):
        """Sauvegarder la configuration"""
        print("💾 Sauvegarde de la configuration...")

        config = {
            "system": {
                "name": "OSINT Ukraine Analysis",
                "version": "1.0.0",
                "setup_date": str(Path.cwd())
            },
            "google_drive": {
                "main_folder_id": folder_map.get("OSINT-Ukraine-Analysis"),
                "folder_map": folder_map,
                "sync_enabled": True
            },
            "osint_domains": {
                "Sauvetage Combat": {
                    "keywords": ["sauvetage", "combat", "medic", "evacuation", "blessé"],
                    "folder_id": folder_map.get("Sauvetage Combat")
                },
                "Drones": {
                    "keywords": ["drone", "UAV", "UAS", "quadcopter", "surveillance"],
                    "folder_id": folder_map.get("Drones")
                },
                "Guerre Electronique": {
                    "keywords": ["guerre électronique", "EW", "brouillage", "radar", "communication"],
                    "folder_id": folder_map.get("Guerre Electronique")
                },
                "Organisation PC": {
                    "keywords": ["PC", "poste commandement", "organisation", "structure", "hiérarchie"],
                    "folder_id": folder_map.get("Organisation PC")
                },
                "Formation Personnel": {
                    "keywords": ["formation", "entraînement", "personnel", "instruction", "exercice"],
                    "folder_id": folder_map.get("Formation Personnel")
                },
                "Artillerie": {
                    "keywords": ["artillerie", "canon", "obus", "bombardement", "feu"],
                    "folder_id": folder_map.get("Artillerie")
                }
            }
        }

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            print("✅ Configuration sauvegardée")
            return True
        except Exception as e:
            self.logger.error(f"Erreur sauvegarde config: {e}")
            return False

    def test_connection(self):
        """Tester la connexion Google Drive"""
        print("🧪 Test de la connexion...")

        try:
            results = self.service.files().list(
                pageSize=1,
                fields="files(id, name)"
            ).execute()

            print("✅ Connexion Google Drive OK")
            return True
        except Exception as e:
            self.logger.error(f"Erreur test connexion: {e}")
            return False

    def setup(self):
        """Processus de configuration complet"""
        print("=" * 60)
        print("🚀 Configuration Google Drive - Système OSINT")
        print("=" * 60)
        print()

        # Vérification des prérequis
        if not self.check_credentials():
            return False

        # Authentification
        if not self.authenticate():
            print("❌ Échec authentification")
            return False

        # Test de connexion
        if not self.test_connection():
            print("❌ Échec test connexion")
            return False

        # Configuration structure
        folder_map = self.setup_drive_structure()
        if not folder_map:
            print("❌ Échec configuration structure")
            return False

        # Sauvegarde configuration
        if not self.save_configuration(folder_map):
            print("❌ Échec sauvegarde configuration")
            return False

        print()
        print("=" * 60)
        print("🎉 CONFIGURATION TERMINÉE!")
        print("=" * 60)
        print()
        print("📁 Structure Google Drive créée:")
        for folder_name in folder_map.keys():
            print(f"  ✅ {folder_name}")
        print()
        print("🚀 Prochaines étapes:")
        print("  1. Testez: python test_system.py")
        print("  2. Synchronisez: python sync_gdrive.py")  
        print("  3. Démarrez: ./start_osint.sh")
        print()

        return True

def main():
    setup = GoogleDriveSetup()
    success = setup.setup()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
