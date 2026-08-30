#!/usr/bin/env sh

set -eu

PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
VENV_LIST=$(mktemp)
trap 'rm -f "$VENV_LIST"' EXIT HUP INT TERM

echo "Searching for virtual environments under $PROJECT_ROOT..."
find "$PROJECT_ROOT" \
    -path "$PROJECT_ROOT/.git" -prune -o \
    -type f -name pyvenv.cfg -print > "$VENV_LIST"

if [ ! -s "$VENV_LIST" ]; then
    echo "No virtual environments found under $PROJECT_ROOT."
    exit 0
fi

echo "The following virtual-environment folders will be deleted:"
while IFS= read -r config_file; do
    venv_dir=$(dirname "$config_file")
    case "$venv_dir" in
        "$PROJECT_ROOT"/*)
            printf '  %s\n' "$venv_dir"
            ;;
    esac
done < "$VENV_LIST"

printf 'Continue with deletion? [y/N] '
confirmation=''
IFS= read -r confirmation || true
case "$confirmation" in
    y|Y|yes|YES|Yes)
        while IFS= read -r config_file; do
            venv_dir=$(dirname "$config_file")
            case "$venv_dir" in
                "$PROJECT_ROOT"/*)
                    printf 'Removing virtual environment: %s\n' "$venv_dir"
                    rm -rf -- "$venv_dir"
                    ;;
            esac
        done < "$VENV_LIST"
        echo "Virtual-environment cleanup complete."
        ;;
    *)
        echo "Cleanup cancelled."
        ;;
esac
