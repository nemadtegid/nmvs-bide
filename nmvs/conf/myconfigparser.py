"""
Created on Nov 28, 2024
Revised for Jelastic environment variables (2025-11)
@author: Reinhold Sojer
"""

import os
import configparser
import logging.config
from pathlib import Path


class MyConfiguration:
    """Configuration handler for environment-based setup (Jelastic)."""

    @staticmethod
    def initialize_logging(logging_config_file="logging.conf"):
        """Initialize logging using a local configuration file."""
        current_dir = Path(__file__).parent.absolute()
        config_file = current_dir / logging_config_file
        logging_settings = configparser.ConfigParser()
        logging_settings.read(config_file)
        project_root = current_dir.parent.parent

        configured_log_dir = Path(logging_settings.get("DEFAULT", "logdir"))
        log_dir = (configured_log_dir if configured_log_dir.is_absolute()
               else project_root / configured_log_dir).absolute()

        if not log_dir.is_dir():
            raise FileNotFoundError(f"Log directory does not exist: {log_dir}")
        if not os.access(log_dir, os.W_OK):
            raise PermissionError(f"Log directory is not writable: {log_dir}")

        logging.config.fileConfig(
            config_file,
            disable_existing_loggers=False
        )

    @staticmethod
    def get_value(key: str, default=None):
        """
        Reads configuration values from Jelastic environment variables.
        :param key: Environment variable name.
        :param default: Fallback if variable not set.
        """
        value = os.getenv(key, default)
        if value is None:
            logging.warning(f"[Config] Environment variable '{key}' not set. Using default: {default}")
        return value

    @staticmethod
    def get_required_value(key: str):
        """
        Reads required configuration variable or raises an error if not found.
        """
        value = os.getenv(key)
        if value is None:
            raise EnvironmentError(f"Missing required environment variable: {key}")
        return value


# Example usage (optional)
if __name__ == "__main__":
    MyConfiguration.initialize_logging()
    db_host = MyConfiguration.get_value("DB_HOST", "localhost")
    print(f"DB host: {db_host}")
