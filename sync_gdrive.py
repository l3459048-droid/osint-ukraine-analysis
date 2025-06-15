#!/usr/bin/env python3
"""
Synchronisation automatique Google Drive pour le système OSINT
Gestion des uploads, downloads et surveillance des changements
"""

import os
import json
import time
import hashlib
import schedule
import logging
from pathlib import Path
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request
import pickle
import io
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import argparse

class GoogleDriveSync:
    def __init__(self, config_file="config.json"):
        self.config_file = Path(config_file)
        self.config = self.load_config()
        self.service = self.initialize_service()

        # Dossiers locaux
        self.raw_docs_path = Path("Raw Documents")
        self.processed_docs_path = Path("Processed Documents")
        self.syntheses_path = Path("Syntheses")
        self.logs_path = Path("Logs")

        # Créer les dossiers locaux si nécessaire
        for path in [self.raw_docs_path, self.processed_docs_path, 
                    self.syntheses_path, self.logs_path]:
            path.mkdir(exist_ok=True)

        # Configuration du logging
        log_file = self.logs_path / f"sync_{datetime.now().strftime('%Y%m%d')}.log"
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def load_config(self):
        """Charger la configuration"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Erreur chargement config: {e}")
            return None

    def initialize_service(self):
        """Initialiser le service Google Drive"""
        try:
            token_file = Path("token.json")
            if not token_file.exists():
                print("❌ Token Google Drive manquant. Lancez setup_gdrive.py")
                return None

            with open(token_file, 'rb') as token:
                creds = pickle.load(token)

            service = build('drive', 'v3', credentials=creds)
            self.logger.info("Service Google Drive initialisé")
            return service
        except Exception as e:
            self.logger.error(f"Erreur initialisation service: {e}")
            return None

    def calculate_file_hash(self, file_path):
        """Calculer le hash MD5 d'un fichier"""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            self.logger.error(f"Erreur calcul hash {file_path}: {e}")
            return None

    def get_drive_files(self, folder_id):
        """Récupérer la liste des fichiers d'un dossier Drive"""
        try:
            query = f"'{folder_id}' in parents and trashed=false"
            results = self.service.files().list(
                q=query,
                fields="files(id, name, modifiedTime, md5Checksum, size)"
            ).execute()

            return results.get('files', [])
        except HttpError as e:
            self.logger.error(f"Erreur récupération fichiers Drive: {e}")
            return []

    def get_local_files(self, directory):
        """Récupérer la liste des fichiers locaux"""
        files = []
        try:
            for file_path in directory.rglob('*'):
                if file_path.is_file():
                    stat = file_path.stat()
                    files.append({
                        'name': file_path.name,
                        'path': str(file_path),
                        'size': stat.st_size,
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        'hash': self.calculate_file_hash(file_path)
                    })
        except Exception as e:
            self.logger.error(f"Erreur récupération fichiers locaux: {e}")

        return files

    def upload_file(self, file_path, folder_id, description=""):
        """Uploader un fichier vers Google Drive"""
        try:
            file_path = Path(file_path)

            # Métadonnées du fichier
            file_metadata = {
                'name': file_path.name,
                'parents': [folder_id],
                'description': description
            }

            # Upload du fichier
            media = MediaFileUpload(str(file_path), resumable=True)
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()

            file_id = file.get('id')
            self.logger.info(f"Fichier uploadé: {file_path.name} (ID: {file_id})")
            return file_id

        except Exception as e:
            self.logger.error(f"Erreur upload {file_path}: {e}")
            return None

    def download_file(self, file_id, local_path):
        """Télécharger un fichier depuis Google Drive"""
        try:
            request = self.service.files().get_media(fileId=file_id)
            fh = io.FileIO(local_path, 'wb')
            downloader = MediaIoBaseDownload(fh, request)

            done = False
            while done is False:
                status, done = downloader.next_chunk()

            self.logger.info(f"Fichier téléchargé: {local_path}")
            return True

        except Exception as e:
            self.logger.error(f"Erreur download {file_id}: {e}")
            return False

    def sync_raw_documents(self):
        """Synchroniser les documents bruts"""
        print("📁 Synchronisation Raw Documents...")

        if not self.config or not self.service:
            return False

        raw_folder_id = self.config['google_drive']['folder_map'].get('Raw Documents')
        if not raw_folder_id:
            self.logger.error("ID dossier Raw Documents manquant")
            return False

        # Récupérer les fichiers locaux et Drive
        local_files = self.get_local_files(self.raw_docs_path)
        drive_files = self.get_drive_files(raw_folder_id)

        # Créer des dictionnaires pour comparaison
        local_dict = {f['name']: f for f in local_files}
        drive_dict = {f['name']: f for f in drive_files}

        # Upload des nouveaux fichiers locaux
        for filename, local_file in local_dict.items():
            if filename not in drive_dict:
                print(f"  ⬆️ Upload: {filename}")
                self.upload_file(
                    local_file['path'], 
                    raw_folder_id,
                    f"Document OSINT - {datetime.now().strftime('%Y-%m-%d')}"
                )
            elif local_file['hash'] != drive_dict[filename].get('md5Checksum'):
                print(f"  🔄 Mise à jour: {filename}")
                # Supprimer l'ancienne version et uploader la nouvelle
                self.service.files().delete(fileId=drive_dict[filename]['id']).execute()
                self.upload_file(local_file['path'], raw_folder_id)

        # Download des nouveaux fichiers Drive
        for filename, drive_file in drive_dict.items():
            if filename not in local_dict:
                local_path = self.raw_docs_path / filename
                print(f"  ⬇️ Download: {filename}")
                self.download_file(drive_file['id'], str(local_path))

        print("✅ Synchronisation Raw Documents terminée")
        return True

    def sync_processed_documents(self):
        """Synchroniser les documents traités"""
        print("📊 Synchronisation Processed Documents...")

        processed_folder_id = self.config['google_drive']['folder_map'].get('Processed Documents')
        if not processed_folder_id:
            return False

        # Synchroniser chaque sous-dossier thématique
        for domain, domain_config in self.config['osint_domains'].items():
            domain_folder_id = domain_config.get('folder_id')
            if not domain_folder_id:
                continue

            domain_path = self.processed_docs_path / domain
            domain_path.mkdir(exist_ok=True)

            print(f"  📂 {domain}")

            local_files = self.get_local_files(domain_path)
            drive_files = self.get_drive_files(domain_folder_id)

            local_dict = {f['name']: f for f in local_files}
            drive_dict = {f['name']: f for f in drive_files}

            # Upload nouveaux fichiers
            for filename, local_file in local_dict.items():
                if filename not in drive_dict:
                    print(f"    ⬆️ {filename}")
                    self.upload_file(local_file['path'], domain_folder_id)

            # Download nouveaux fichiers
            for filename, drive_file in drive_dict.items():
                if filename not in local_dict:
                    local_path = domain_path / filename
                    print(f"    ⬇️ {filename}")
                    self.download_file(drive_file['id'], str(local_path))

        print("✅ Synchronisation Processed Documents terminée")
        return True

    def sync_syntheses(self):
        """Synchroniser les synthèses"""
        print("📋 Synchronisation Syntheses...")

        syntheses_folder_id = self.config['google_drive']['folder_map'].get('Syntheses')
        if not syntheses_folder_id:
            return False

        local_files = self.get_local_files(self.syntheses_path)
        drive_files = self.get_drive_files(syntheses_folder_id)

        local_dict = {f['name']: f for f in local_files}
        drive_dict = {f['name']: f for f in drive_files}

        # Upload synthèses locales
        for filename, local_file in local_dict.items():
            if filename not in drive_dict:
                print(f"  ⬆️ Upload: {filename}")
                self.upload_file(local_file['path'], syntheses_folder_id)
            elif local_file['hash'] != drive_dict[filename].get('md5Checksum'):
                print(f"  🔄 Mise à jour: {filename}")
                self.service.files().delete(fileId=drive_dict[filename]['id']).execute()
                self.upload_file(local_file['path'], syntheses_folder_id)

        print("✅ Synchronisation Syntheses terminée")
        return True

    def full_sync(self):
        """Synchronisation complète"""
        print("=" * 60)
        print(f"🔄 Synchronisation complète - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        if not self.service:
            print("❌ Service Google Drive non disponible")
            return False

        success = True
        success &= self.sync_raw_documents()
        success &= self.sync_processed_documents()
        success &= self.sync_syntheses()

        if success:
            print("🎉 Synchronisation complète réussie!")
        else:
            print("⚠️ Synchronisation terminée avec des erreurs")

        print("=" * 60)
        return success

    def watch_folder(self, path):
        """Surveiller les changements dans un dossier"""
        class SyncHandler(FileSystemEventHandler):
            def __init__(self, sync_instance):
                self.sync = sync_instance

            def on_created(self, event):
                if not event.is_directory:
                    self.sync.logger.info(f"Nouveau fichier détecté: {event.src_path}")
                    # Attendre un peu pour être sûr que le fichier est complet
                    time.sleep(2)
                    self.sync.full_sync()

            def on_modified(self, event):
                if not event.is_directory:
                    self.sync.logger.info(f"Fichier modifié: {event.src_path}")
                    time.sleep(2)
                    self.sync.full_sync()

        event_handler = SyncHandler(self)
        observer = Observer()
        observer.schedule(event_handler, str(path), recursive=True)
        return observer

    def start_continuous_sync(self):
        """Démarrer la synchronisation continue"""
        print("🔄 Démarrage synchronisation continue...")

        # Synchronisation initiale
        self.full_sync()

        # Planifier les synchronisations périodiques
        schedule.every(30).minutes.do(self.full_sync)

        # Surveiller les dossiers
        observers = []
        for path in [self.raw_docs_path, self.processed_docs_path, self.syntheses_path]:
            if path.exists():
                observer = self.watch_folder(path)
                observer.start()
                observers.append(observer)
                print(f"👀 Surveillance: {path}")

        print("✅ Synchronisation continue active")
        print("   🔄 Sync automatique: toutes les 30 minutes")
        print("   👀 Surveillance temps réel des dossiers")
        print("   ⏹️ Ctrl+C pour arrêter")

        try:
            while True:
                schedule.run_pending()
                time.sleep(60)
        except KeyboardInterrupt:
            print("\n⏹️ Arrêt de la synchronisation...")
            for observer in observers:
                observer.stop()
                observer.join()
            print("✅ Synchronisation arrêtée")

def main():
    parser = argparse.ArgumentParser(description='Synchronisation Google Drive OSINT')
    parser.add_argument('--mode', 
                       choices=['once', 'continuous', 'watch', 'status'],
                       default='once',
                       help='Mode de synchronisation')

    args = parser.parse_args()

    sync = GoogleDriveSync()

    if args.mode == 'once':
        sync.full_sync()
    elif args.mode == 'continuous':
        sync.start_continuous_sync()
    elif args.mode == 'status':
        print("📊 Statut de la synchronisation:")
        if sync.service:
            print("  ✅ Service Google Drive: OK")
        else:
            print("  ❌ Service Google Drive: Erreur")
        if sync.config:
            print("  ✅ Configuration: OK")
        else:
            print("  ❌ Configuration: Erreur")

if __name__ == "__main__":
    main()
