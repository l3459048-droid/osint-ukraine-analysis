__version__ = "0.6.0"

# v0.5 adds translation persistence without requiring a destructive database migration.
from .translation_db import install_translation_db_api

install_translation_db_api()
