#!/bin/bash

# Système OSINT Ukraine - Script de démarrage Linux/Mac
# Gestion complète du système d'analyse OSINT

# Couleurs pour l'affichage
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Fonction d'affichage avec couleur
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "${BLUE}"
    echo "================================================================="
    echo "🚀 Système d'Analyse OSINT - Ukraine"
    echo "📊 Plateforme d'Intelligence Open Source"
    echo "================================================================="
    echo -e "${NC}"
}

# Vérification de Python
check_python() {
    print_status "Vérification de Python..."

    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    else
        print_error "Python non trouvé. Installez Python 3.7+"
        exit 1
    fi

    # Vérifier la version
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
    REQUIRED_VERSION="3.7"

    if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
        print_error "Python 3.7+ requis. Version détectée: $PYTHON_VERSION"
        exit 1
    fi

    print_status "Python $PYTHON_VERSION détecté"
}

# Vérification des requirements
check_requirements() {
    print_status "Vérification des dépendances..."

    if [ ! -f "requirements.txt" ]; then
        print_warning "requirements.txt manquant"
        return 1
    fi

    # Vérifier si pip est disponible
    if ! $PYTHON_CMD -m pip --version &> /dev/null; then
        print_error "pip non disponible"
        exit 1
    fi

    print_status "Dépendances OK"
}

# Vérification de la configuration
check_config() {
    print_status "Vérification de la configuration..."

    if [ ! -f "config.json" ]; then
        print_warning "Configuration manquante. Lancez setup_gdrive.py"
        return 1
    fi

    if [ ! -f "token.json" ]; then
        print_warning "Token Google Drive manquant. Lancez setup_gdrive.py"
        return 1
    fi

    print_status "Configuration OK"
}

# Installation des dépendances
install_dependencies() {
    print_status "Installation des dépendances..."

    if [ -f "requirements.txt" ]; then
        $PYTHON_CMD -m pip install -q -r requirements.txt
        if [ $? -eq 0 ]; then
            print_status "Dépendances installées"
        else
            print_error "Erreur installation dépendances"
            exit 1
        fi
    else
        print_warning "requirements.txt manquant"
    fi
}

# Configuration du système
setup_system() {
    print_status "Configuration du système..."

    if [ ! -f "setup_gdrive.py" ]; then
        print_error "setup_gdrive.py manquant"
        exit 1
    fi

    $PYTHON_CMD setup_gdrive.py
    if [ $? -eq 0 ]; then
        print_status "Configuration terminée"
    else
        print_error "Erreur configuration"
        exit 1
    fi
}

# Exécution des tests
run_tests() {
    print_status "Exécution des tests système..."

    if [ -f "test_system.py" ]; then
        $PYTHON_CMD test_system.py
        if [ $? -eq 0 ]; then
            print_status "Tests réussis"
        else
            print_warning "Tests avec erreurs"
        fi
    else
        print_warning "test_system.py manquant"
    fi
}

# Synchronisation continue
start_continuous_sync() {
    print_status "Démarrage synchronisation continue..."
    print_status "Mode: Surveillance temps réel + sync périodique"
    print_status "Appuyez sur Ctrl+C pour arrêter"
    echo

    $PYTHON_CMD sync_gdrive.py --mode continuous
}

# Synchronisation unique
start_single_sync() {
    print_status "Synchronisation unique..."
    $PYTHON_CMD sync_gdrive.py --mode once
}

# Affichage du statut
show_status() {
    print_status "Statut du système..."
    $PYTHON_CMD sync_gdrive.py --mode status
}

# Mode monitoring
start_monitoring() {
    print_status "Mode monitoring activé..."
    print_status "Surveillance des métriques système"

    while true; do
        clear
        print_header
        echo

        # Statut des dossiers
        echo "📁 DOSSIERS:"
        for dir in "Raw Documents" "Processed Documents" "Syntheses" "Logs"; do
            if [ -d "$dir" ]; then
                count=$(find "$dir" -type f | wc -l)
                echo "  ✅ $dir: $count fichiers"
            else
                echo "  ❌ $dir: manquant"
            fi
        done

        echo
        echo "🔄 SYNCHRONISATION:"
        $PYTHON_CMD sync_gdrive.py --mode status

        echo
        echo "📊 SYSTÈME:"
        echo "  💾 Espace disque: $(df -h . | tail -1 | awk '{print $4}') libre"
        echo "  🕐 Dernière mise à jour: $(date)"

        echo
        echo "⏹️  Ctrl+C pour arrêter le monitoring"

        sleep 30
    done
}

# Affichage de l'aide
show_help() {
    print_header
    echo
    echo "🔧 UTILISATION:"
    echo "  $0 [OPTION]"
    echo
    echo "📋 OPTIONS:"
    echo "  install     Installation complète du système"
    echo "  setup       Configuration Google Drive"  
    echo "  test        Tests du système"
    echo "  sync        Synchronisation unique"
    echo "  continuous  Synchronisation continue (défaut)"
    echo "  status      Affichage du statut"
    echo "  monitor     Mode monitoring"
    echo "  help        Afficher cette aide"
    echo
    echo "💡 EXEMPLES:"
    echo "  $0 install     # Installation première fois"
    echo "  $0 continuous  # Démarrage normal"
    echo "  $0 sync        # Sync ponctuelle"
    echo "  $0 monitor     # Surveillance"
    echo
}

# Fonction principale
main() {
    # Gestion du signal d'arrêt
    trap 'echo -e "\n⏹️ Arrêt du système..."; exit 0' SIGINT SIGTERM

    case "${1:-continuous}" in
        "install")
            print_header
            check_python
            install_dependencies
            setup_system
            run_tests
            print_status "Installation terminée!"
            ;;

        "setup")
            print_header
            check_python
            setup_system
            ;;

        "test")
            print_header
            check_python
            run_tests
            ;;

        "sync")
            print_header
            check_python
            check_config
            start_single_sync
            ;;

        "continuous")
            print_header
            check_python
            check_requirements
            check_config
            start_continuous_sync
            ;;

        "status")
            print_header
            show_status
            ;;

        "monitor")
            print_header
            start_monitoring
            ;;

        "help"|"-h"|"--help")
            show_help
            ;;

        *)
            print_error "Option inconnue: $1"
            show_help
            exit 1
            ;;
    esac
}

# Exécution
main "$@"
