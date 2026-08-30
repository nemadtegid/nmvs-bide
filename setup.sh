#!/usr/bin/env sh
#set -eu

PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
VENV_DIR="$PROJECT_ROOT/venv"
LOGGING_CONFIG="$PROJECT_ROOT/nmvs/conf/logging.conf"
PYPROJECT_FILE="$PROJECT_ROOT/pyproject.toml"

cd "$PROJECT_ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found in PATH." >&2
  exit 1
fi

# Find or create the log directory specified in the logging configuration file

LOG_DIR=$(awk -F= '
    /^[[:space:]]*logdir[[:space:]]*=/ {
        value = $2
        sub(/^[[:space:]]+/, "", value)
        sub(/[[:space:]]+$/, "", value)
        print value
        exit
    }
' "$LOGGING_CONFIG")

case "$LOG_DIR" in
  /*) ;;
  *) LOG_DIR="$PROJECT_ROOT/$LOG_DIR" ;;
esac

if [ -z "$LOG_DIR" ]; then
  echo "logdir is missing or empty in $LOGGING_CONFIG." >&2
  exit 1
fi

printf 'Creating log directory %s ... ' "$LOG_DIR"
if mkdir -p "$LOG_DIR"; then
  echo "OK"
else
  echo "FAILED, make it manually" >&2
fi

# .secrets.env file is used to store sensitive information like database credentials and API keys.

# small trick to suggest a user agent string for the NMVS API client based on the project name and version from pyproject.toml
PROJECT_NAME=$(awk -F= '/^[[:space:]]*name[[:space:]]*=/ {
  value = $2
  gsub(/[[:space:]"]/, "", value)
  print value
  exit
}' "$PYPROJECT_FILE")
PROJECT_VERSION=$(awk -F= '/^[[:space:]]*version[[:space:]]*=/ {
  value = $2
  gsub(/[[:space:]"]/, "", value)
  print value
  exit
}' "$PYPROJECT_FILE")
NMVS_USER_AGENT=$(printf '%s %s' "$PROJECT_NAME" "$PROJECT_VERSION" | tr '[:lower:]' '[:upper:]')

if [ ! -f "$PROJECT_ROOT/.secrets.env" ]; then
  printf '%s\n' \
    'export database_url="mysql+pymysql://<your-db-user>:<your-db-password>@<your-db-server>:3306/<your-db-name>"' \
    'export nmvs_report_url="https://<something>/report"' \
    'export nmvs_token_url="https://<something>/identity/connect/token"' \
    'export nmvs_client_id="<your-nmvs-api-client-id>"' \
    'export nmvs_client_secret="<your-nmvs-api-client-secret>"' \
    'export emvs_api_version="3.4"' \
    "export nmvs_user_agent=\"$NMVS_USER_AGENT\"" \
    > "$PROJECT_ROOT/.secrets.env"
  chmod 600 "$PROJECT_ROOT/.secrets.env"
  echo "Created $PROJECT_ROOT/.secrets.env; edit it with your credentials."
else
  echo "$PROJECT_ROOT/.secrets.env already exists; leaving it unchanged."
fi

# Set up venv and install the package in editable mode

echo "Setting up virtual environment in $VENV_DIR..."
python3 -m venv "$VENV_DIR"
$VENV_DIR/bin/python -m pip install --upgrade pip
# For production installation skipp the "-e" option
$VENV_DIR/bin/python -m pip install -e .

echo
echo "Setup complete."
echo "Activate the environment with:"
echo "  ./venv/bin/activate"
echo "See execution examples from scripts/exec-examples.sh"

