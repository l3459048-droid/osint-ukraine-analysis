# 🔑 Guide Configuration Google Drive API

**Guide complet pour configurer l'accès Google Drive API pour le système OSINT**

## 📋 Vue d'ensemble

Ce guide vous accompagne étape par étape pour configurer l'accès à l'API Google Drive, prérequis indispensable au fonctionnement du système OSINT.

## 🎯 Prérequis

- ✅ Compte Google actif
- ✅ Navigateur web
- ✅ 10 minutes de temps libre

## 🚀 Étapes de Configuration

### 1️⃣ Accès à Google Cloud Console

1. **Ouvrez votre navigateur** et allez sur :  
   [https://console.cloud.google.com/](https://console.cloud.google.com/)

2. **Connectez-vous** avec votre compte Google

3. **Acceptez** les conditions d'utilisation si demandé

### 2️⃣ Création/Sélection du Projet

#### Option A : Créer un Nouveau Projet

1. **Cliquez sur le sélecteur de projet** (en haut à gauche)
2. **Cliquez "NOUVEAU PROJET"**
3. **Nom du projet** : `OSINT-Ukraine-Analysis`
4. **Organisation** : Laissez par défaut
5. **Cliquez "CRÉER"**
6. **Attendez** la création (30 secondes)

#### Option B : Utiliser un Projet Existant

1. **Sélectionnez votre projet** dans la liste
2. **Assurez-vous** qu'il est actif (nom affiché en haut)

### 3️⃣ Activation de l'API Google Drive

1. **Dans le menu de gauche**, cliquez sur :  
   `APIs et services` → `Bibliothèque`

2. **Recherchez** : `Google Drive API`

3. **Cliquez** sur `Google Drive API` dans les résultats

4. **Cliquez "ACTIVER"**

5. **Attendez** l'activation (quelques secondes)

6. ✅ **Confirmation** : "API Google Drive activée"

### 4️⃣ Configuration de l'Écran de Consentement OAuth

1. **Allez dans** : `APIs et services` → `Écran de consentement OAuth`

2. **Type d'utilisateur** : Sélectionnez `Externe`

3. **Cliquez "CRÉER"**

4. **Remplissez les informations** :
   - **Nom de l'application** : `OSINT Ukraine Analysis`
   - **E-mail de support utilisateur** : votre email
   - **Domaines autorisés** : laissez vide
   - **E-mail de contact développeur** : votre email

5. **Cliquez "ENREGISTRER ET CONTINUER"**

6. **Champs d'application** : Cliquez "ENREGISTRER ET CONTINUER" (pas de modification)

7. **Utilisateurs de test** : Cliquez "ENREGISTRER ET CONTINUER" (pas de modification)

8. **Résumé** : Cliquez "RETOUR AU TABLEAU DE BORD"

### 5️⃣ Création des Identifiants

1. **Allez dans** : `APIs et services` → `Identifiants`

2. **Cliquez "CRÉER DES IDENTIFIANTS"**

3. **Sélectionnez** : `ID client OAuth 2.0`

4. **Type d'application** : `Application de bureau`

5. **Nom** : `OSINT Desktop Client`

6. **Cliquez "CRÉER"**

7. ✅ **Popup de confirmation** apparaît avec les identifiants

### 6️⃣ Téléchargement du Fichier credentials.json

1. **Dans le popup**, cliquez "TÉLÉCHARGER JSON"

2. **Ou** cliquez sur l'icône de téléchargement dans la liste des identifiants

3. **Renommez** le fichier téléchargé en : `credentials.json`

4. **Placez-le** dans le dossier de votre projet OSINT

### 7️⃣ Vérification de la Configuration

1. **Ouvrez un terminal** dans le dossier du projet

2. **Vérifiez** la présence du fichier :
   ```bash
   ls -la credentials.json
   ```

3. **Lancez** la configuration :
   ```bash
   python setup_gdrive.py
   ```

4. **Suivez** les instructions d'authentification

## 🔐 Processus d'Authentification

### Premier Lancement

1. **Le navigateur s'ouvre** automatiquement
2. **Connectez-vous** à Google si nécessaire  
3. **Autorisez** l'application OSINT
4. **Accordez** les permissions demandées :
   - ✅ Voir et gérer les fichiers Drive
   - ✅ Créer des dossiers
   - ✅ Lire les métadonnées
5. **Page de confirmation** : "Authentification réussie"
6. **Fermez** l'onglet, retournez au terminal

### Résultat Attendu

```
🔐 Authentification Google Drive...
✅ Authentification réussie
✅ Token sauvegardé
✅ Service Google Drive initialisé
🗂️ Configuration de la structure Google Drive...
📁 Création: OSINT-Ukraine-Analysis
📁 Création: OSINT-Ukraine-Analysis/Raw Documents
📁 Création: OSINT-Ukraine-Analysis/Processed Documents
[...]
🎉 CONFIGURATION TERMINÉE!
```

## 📁 Structure Google Drive Créée

Après configuration, cette structure est créée automatiquement :

```
📂 OSINT-Ukraine-Analysis/
├── 📂 Raw Documents/
├── 📂 Processed Documents/
│   ├── 📂 Sauvetage Combat/
│   ├── 📂 Drones/
│   ├── 📂 Guerre Electronique/
│   ├── 📂 Organisation PC/
│   ├── 📂 Formation Personnel/
│   ├── 📂 Artillerie/
│   └── 📂 Autres/
├── 📂 Syntheses/
├── 📂 Archives/
└── 📂 Logs/
```

## 🔧 Dépannage

### ❌ Erreur "credentials.json manquant"

**Solution :**
1. Vérifiez que le fichier est bien nommé `credentials.json`
2. Vérifiez qu'il est dans le bon dossier
3. Téléchargez-le à nouveau depuis Google Cloud Console

### ❌ Erreur "API non activée"

**Solution :**
1. Retournez sur Google Cloud Console
2. Vérifiez que l'API Google Drive est activée
3. Attendez quelques minutes après activation

### ❌ Erreur d'authentification

**Solution :**
1. Supprimez le fichier `token.json`
2. Relancez `python setup_gdrive.py`
3. Réautorisez l'application

### ❌ Problème de permissions

**Solution :**
1. Vérifiez l'écran de consentement OAuth
2. Assurez-vous d'avoir accordé toutes les permissions
3. Reconfigurez les identifiants si nécessaire

### ❌ Quotas dépassés

**Solution :**
1. Vérifiez les quotas dans Google Cloud Console
2. Attendez le reset quotidien (minuit UTC)
3. Demandez une augmentation si nécessaire

## 📊 Vérification du Bon Fonctionnement

### Test de Connexion
```bash
python -c "
import pickle
from googleapiclient.discovery import build

with open('token.json', 'rb') as token:
    creds = pickle.load(token)

service = build('drive', 'v3', credentials=creds)
results = service.files().list(pageSize=1).execute()
print('✅ Connexion Google Drive OK')
"
```

### Test de Création de Dossier
```bash
python test_system.py --test drive
```

## 🔒 Sécurité et Bonnes Pratiques

### 🔐 Protection des Fichiers Sensibles

- ✅ **Ajoutez** `credentials.json` et `token.json` au `.gitignore`
- ✅ **Ne partagez jamais** ces fichiers
- ✅ **Révolutionnez** les identifiants si compromis

### 🚫 Fichiers à ne JAMAIS commiter

```
# .gitignore
credentials.json
token.json
.env
config.json
```

### 🔄 Rotation des Identifiants

**Fréquence recommandée** : Tous les 6 mois

**Processus** :
1. Créez de nouveaux identifiants
2. Testez avec le nouveau fichier
3. Supprimez les anciens identifiants
4. Mettez à jour la documentation

## 📋 Checklist de Validation

Avant de continuer, vérifiez :

- [ ] ✅ Projet Google Cloud créé
- [ ] ✅ API Google Drive activée  
- [ ] ✅ Écran de consentement configuré
- [ ] ✅ Identifiants OAuth créés
- [ ] ✅ Fichier `credentials.json` téléchargé et placé
- [ ] ✅ Authentification réussie
- [ ] ✅ Fichier `token.json` généré
- [ ] ✅ Structure de dossiers créée sur Drive
- [ ] ✅ Test de connexion OK

## 🚀 Étapes Suivantes

Une fois la configuration Google Drive terminée :

1. **Lancez les tests** : `python test_system.py`
2. **Démarrez la synchronisation** : `./start_osint.sh`
3. **Déposez vos premiers documents** dans `Raw Documents/`
4. **Consultez** l'interface web générée

## 📞 Support

En cas de problème :

1. **Consultez** les logs : `Logs/setup_gdrive.log`
2. **Relancez** avec debug : `python setup_gdrive.py --debug`
3. **Vérifiez** la documentation Google Drive API
4. **Créez** une issue GitHub avec les logs d'erreur

---

**🎉 Configuration terminée ! Votre système OSINT est prêt à analyser vos documents.**
