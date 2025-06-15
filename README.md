# 🚀 Système d'Analyse OSINT - Ukraine

**Plateforme automatisée d'analyse de documents Open Source Intelligence**

[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/)
[![Google Drive](https://img.shields.io/badge/Google%20Drive-API-green.svg)](https://developers.google.com/drive)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)]()

## 📋 Description

Ce système permet l'analyse automatique de centaines de documents PDF relatifs à la guerre en Ukraine. Il classe automatiquement les documents par domaines OSINT, génère des synthèses intelligentes et maintient une synchronisation avec Google Drive.

### 🎯 Fonctionnalités Principales

- 📁 **Synchronisation Google Drive** automatique
- 🔍 **OCR automatique** pour les PDFs non-extractibles  
- 🏷️ **Classification thématique** par domaines OSINT
- 📊 **Synthèses automatiques** (max 20 points par domaine)
- 🔄 **Mise à jour incrémentielle** hebdomadaire
- 📱 **Interface responsive** mobile/desktop
- 🌐 **Publication GitHub Pages** automatique

### 🎪 Domaines OSINT Configurés

| Domaine | Description | Mots-clés |
|---------|-------------|-----------|
| 🏥 **Sauvetage Combat** | Évacuation médicale, premiers secours | `sauvetage`, `medic`, `evacuation` |
| 🚁 **Drones** | UAV, surveillance, reconnaissance | `drone`, `UAV`, `surveillance` |
| 📡 **Guerre Électronique** | Brouillage, radar, communications | `EW`, `jamming`, `radar` |
| 🏢 **Organisation PC** | Postes de commandement, structure | `command post`, `organisation` |
| 🎓 **Formation Personnel** | Entraînement, instruction militaire | `formation`, `training` |
| 💥 **Artillerie** | Canons, bombardements, appui feu | `artillerie`, `canon`, `HIMARS` |

## 🚀 Installation Rapide

### Prérequis
- Python 3.7+
- Compte Google (pour Drive API)
- Git

### 1️⃣ Cloner le Repository
```bash
git clone https://github.com/VOTRE-USERNAME/osint-ukraine-analysis
cd osint-ukraine-analysis
```

### 2️⃣ Installation Automatique

**Windows :**
```bash
python install_osint.py
start_osint.bat
```

**Linux/Mac :**
```bash
python3 install_osint.py
chmod +x start_osint.sh
./start_osint.sh install
```

### 3️⃣ Configuration Google Drive

1. **Allez sur [Google Cloud Console](https://console.cloud.google.com/)**
2. **Créez un projet** ou sélectionnez-en un
3. **Activez l'API Google Drive**
4. **Créez des identifiants OAuth 2.0**
5. **Téléchargez `credentials.json`**
6. **Placez-le dans le dossier du projet**

```bash
python setup_gdrive.py
```

## 🎯 Utilisation

### Démarrage Rapide

**Mode Normal (Recommandé) :**
```bash
# Windows
start_osint.bat

# Linux/Mac  
./start_osint.sh continuous
```

**Synchronisation Unique :**
```bash
./start_osint.sh sync
```

**Tests Système :**
```bash
python test_system.py
```

### Workflow Quotidien

1. **Déposez vos PDFs** dans `Raw Documents/`
2. **Le système détecte automatiquement** les nouveaux fichiers
3. **OCR automatique** si nécessaire
4. **Classification par domaine** OSINT
5. **Génération des synthèses** mises à jour
6. **Publication web** automatique

## 📁 Structure du Projet

```
osint-ukraine-analysis/
├── 📄 install_osint.py         # Installation automatique
├── 🔧 setup_gdrive.py          # Configuration Google Drive
├── 🔄 sync_gdrive.py           # Synchronisation
├── 🧪 test_system.py           # Tests système
├── 🖥️ start_osint.sh           # Démarrage Linux/Mac
├── 🖥️ start_osint.bat          # Démarrage Windows
├── 📋 requirements.txt         # Dépendances Python
├── ⚙️ config_template.json     # Configuration système
├── 📁 Raw Documents/           # 📥 Déposez vos PDFs ici
├── 📁 Processed Documents/     # 📊 Documents analysés
│   ├── Sauvetage Combat/
│   ├── Drones/
│   ├── Guerre Electronique/
│   ├── Organisation PC/
│   ├── Formation Personnel/
│   └── Artillerie/
├── 📁 Syntheses/              # 📋 Rapports générés
├── 📁 Logs/                   # 📝 Journaux système
└── 📁 Config/                 # ⚙️ Configuration
```

## ⚙️ Configuration Avancée

### Modification des Domaines OSINT

Éditez `config.json` pour ajouter/modifier les domaines :

```json
{
  "osint_domains": {
    "Nouveau Domaine": {
      "keywords": ["mot1", "mot2", "mot3"],
      "aliases": ["alias1", "alias2"],
      "priority": 2
    }
  }
}
```

### Paramètres de Synchronisation

```json
{
  "google_drive": {
    "sync_interval": 1800,        // 30 minutes
    "max_file_size": 104857600,   // 100MB
    "allowed_extensions": [".pdf", ".docx"]
  }
}
```

## 🧪 Tests et Validation

### Tests Complets
```bash
python test_system.py
```

### Tests Spécifiques
```bash
# Test Google Drive
python test_system.py --test drive

# Test OCR
python test_system.py --test ocr

# Test Classification
python test_system.py --test clustering
```

## 📊 Monitoring

### Statut Système
```bash
./start_osint.sh status
```

### Mode Monitoring
```bash
./start_osint.sh monitor
```

### Logs
```bash
tail -f Logs/sync_$(date +%Y%m%d).log
```

## 🌐 Publication Web

Le système génère automatiquement un site web accessible publiquement :

**URL :** `https://VOTRE-USERNAME.github.io/osint-ukraine-analysis`

### Fonctionnalités Web
- 📊 Dashboard avec métriques temps réel
- 🔍 Moteur de recherche sémantique  
- 📱 Interface responsive mobile/desktop
- 📄 Export PDF des synthèses
- 📈 Graphiques de relations entre documents

## 🔧 Dépannage

### Problèmes Courants

**❌ Token Google Drive expiré**
```bash
rm token.json
python setup_gdrive.py
```

**❌ Erreur OCR**
- Vérifiez votre clé API OCR.space
- Vérifiez la taille des fichiers (<10MB)

**❌ Synchronisation bloquée**
```bash
./start_osint.sh sync --force
```

**❌ Erreur dépendances**
```bash
pip install -r requirements.txt --upgrade
```

### Logs de Débogage
```bash
# Activer le mode debug
export LOG_LEVEL=DEBUG
./start_osint.sh continuous
```

## 📈 Métriques

Le système suit automatiquement :
- 📊 Nombre de documents traités
- ⏱️ Temps de traitement moyen
- 🎯 Précision de classification
- 💾 Utilisation de l'espace Drive
- 🔄 Fréquence de synchronisation

## 🔄 Mises à Jour

### Mise à Jour Automatique
```bash
git pull origin main
pip install -r requirements.txt --upgrade
```

### Mise à Jour Manuelle
1. Sauvegardez votre configuration
2. Téléchargez la nouvelle version
3. Restaurez votre configuration
4. Relancez les tests

## 🆘 Support

### Documentation
- 📖 [Guide Google Drive API](GUIDE_GOOGLE_DRIVE.md)
- 🧪 [Tests Système](test_system.py)
- ⚙️ [Configuration](config_template.json)

### Résolution de Problèmes
1. **Vérifiez les logs** dans `Logs/`
2. **Lancez les tests** : `python test_system.py`
3. **Consultez la documentation** Google Drive API
4. **Vérifiez les permissions** des dossiers

### Contact
- 📧 Issues GitHub pour les bugs
- 💬 Discussions pour les questions
- 📝 Wiki pour la documentation détaillée

## 📜 Licence

MIT License - Voir [LICENSE](LICENSE) pour les détails.

## 🏆 Contributeurs

Merci à tous les contributeurs qui améliorent ce système !

---

**🚀 Système prêt à l'emploi - Déployez en 5 minutes !**

*Dernière mise à jour : $(date)*
