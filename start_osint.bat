@echo off
REM Système OSINT Ukraine - Script de démarrage Windows
REM Gestion complète du système d'analyse OSINT

title Système OSINT Ukraine

:HEADER
echo ================================================================
echo 🚀 Système d'Analyse OSINT - Ukraine
echo 📊 Plateforme d'Intelligence Open Source  
echo ================================================================
echo.

REM Vérification de Python
:CHECK_PYTHON
echo [INFO] Vérification de Python...

python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    goto :PYTHON_OK
)

python3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python3
    goto :PYTHON_OK
)

echo [ERROR] Python non trouvé. Installez Python 3.7+
pause
exit /b 1

:PYTHON_OK
echo [INFO] Python détecté

REM Menu principal
:MENU
echo.
echo 📋 MENU PRINCIPAL:
echo   1. Installation complète
echo   2. Configuration Google Drive
echo   3. Tests système
echo   4. Synchronisation unique
echo   5. Synchronisation continue
echo   6. Statut système
echo   7. Aide
echo   8. Quitter
echo.
set /p choice="Choisissez une option (1-8): "

if "%choice%"=="1" goto :INSTALL
if "%choice%"=="2" goto :SETUP
if "%choice%"=="3" goto :TEST
if "%choice%"=="4" goto :SYNC_ONCE
if "%choice%"=="5" goto :SYNC_CONTINUOUS
if "%choice%"=="6" goto :STATUS
if "%choice%"=="7" goto :HELP
if "%choice%"=="8" goto :EXIT

echo [ERROR] Option invalide
goto :MENU

REM Installation complète
:INSTALL
echo.
echo [INFO] === INSTALLATION COMPLETE ===
echo.

echo [INFO] Installation des dépendances...
if exist requirements.txt (
    %PYTHON_CMD% -m pip install -q -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Erreur installation dépendances
        pause
        goto :MENU
    )
    echo [INFO] Dépendances installées
) else (
    echo [WARN] requirements.txt manquant
)

echo [INFO] Configuration du système...
if exist setup_gdrive.py (
    %PYTHON_CMD% setup_gdrive.py
    if %errorlevel% neq 0 (
        echo [ERROR] Erreur configuration
        pause
        goto :MENU
    )
) else (
    echo [ERROR] setup_gdrive.py manquant
    pause
    goto :MENU
)

echo [INFO] Tests système...
if exist test_system.py (
    %PYTHON_CMD% test_system.py
)

echo [INFO] Installation terminée!
pause
goto :MENU

REM Configuration Google Drive
:SETUP
echo.
echo [INFO] === CONFIGURATION GOOGLE DRIVE ===
echo.

if exist setup_gdrive.py (
    %PYTHON_CMD% setup_gdrive.py
    if %errorlevel% equ 0 (
        echo [INFO] Configuration terminée
    ) else (
        echo [ERROR] Erreur configuration
    )
) else (
    echo [ERROR] setup_gdrive.py manquant
)

pause
goto :MENU

REM Tests système
:TEST
echo.
echo [INFO] === TESTS SYSTÈME ===
echo.

if exist test_system.py (
    %PYTHON_CMD% test_system.py
) else (
    echo [ERROR] test_system.py manquant
)

pause
goto :MENU

REM Synchronisation unique
:SYNC_ONCE
echo.
echo [INFO] === SYNCHRONISATION UNIQUE ===
echo.

if not exist config.json (
    echo [ERROR] Configuration manquante. Lancez d'abord l'option 2
    pause
    goto :MENU
)

if exist sync_gdrive.py (
    %PYTHON_CMD% sync_gdrive.py --mode once
) else (
    echo [ERROR] sync_gdrive.py manquant
)

pause
goto :MENU

REM Synchronisation continue
:SYNC_CONTINUOUS
echo.
echo [INFO] === SYNCHRONISATION CONTINUE ===
echo [INFO] Mode: Surveillance temps réel + sync périodique
echo [INFO] Appuyez sur Ctrl+C pour arrêter
echo.

if not exist config.json (
    echo [ERROR] Configuration manquante. Lancez d'abord l'option 2
    pause
    goto :MENU
)

if exist sync_gdrive.py (
    %PYTHON_CMD% sync_gdrive.py --mode continuous
) else (
    echo [ERROR] sync_gdrive.py manquant
    pause
    goto :MENU
)

echo.
echo [INFO] Synchronisation arrêtée
pause
goto :MENU

REM Statut système  
:STATUS
echo.
echo [INFO] === STATUT SYSTÈME ===
echo.

echo [INFO] Dossiers:
for %%d in ("Raw Documents" "Processed Documents" "Syntheses" "Logs") do (
    if exist %%d (
        echo   ✅ %%d: OK
    ) else (
        echo   ❌ %%d: Manquant
    )
)

echo.
if exist sync_gdrive.py (
    %PYTHON_CMD% sync_gdrive.py --mode status
) else (
    echo [ERROR] sync_gdrive.py manquant
)

pause
goto :MENU

REM Aide
:HELP
echo.
echo [INFO] === AIDE ===
echo.
echo 🔧 UTILISATION:
echo   Ce script permet de gérer le système OSINT Ukraine
echo.
echo 📋 OPTIONS:
echo   1. Installation     - Configuration première fois
echo   2. Setup           - Configuration Google Drive uniquement
echo   3. Tests           - Vérification du système
echo   4. Sync unique     - Synchronisation ponctuelle
echo   5. Sync continue   - Fonctionnement normal
echo   6. Statut          - Vérification état système
echo.
echo 💡 ORDRE RECOMMANDÉ (première utilisation):
echo   1. Option 1 (Installation complète)
echo   2. Option 5 (Synchronisation continue)
echo.
echo 📁 STRUCTURE:
echo   Raw Documents/        - Déposez vos PDFs ici
echo   Processed Documents/  - Documents analysés
echo   Syntheses/           - Rapports générés
echo   Logs/                - Journaux système
echo.

pause
goto :MENU

REM Sortie
:EXIT
echo.
echo [INFO] Arrêt du système OSINT
echo Au revoir!
echo.
exit /b 0
