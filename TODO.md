# TODO

## High priority

  - Improve credentials secrecy. Use smthing like:
> import os
> from dotenv import load_dotenv
> load_dotenv()
> db_user = os.getenv("DB_USER")
> db_password = os.getenv("DB_PASSWORD")
> db_host = os.getenv("DB_HOST", "localhost")

- [ ] Functional changes
  - Incorporate Exeptions API to standard process [nmvs/importer/nmvs_exceptions.py](nmvs/importer/nmvs_exceptions.py)

## Medium priority
- [ ] Add basic validation and regression checks
  - Run project smoke tests for the main CLI flows 
  - Add minimal checks for import/report execution paths
- [ ] Make the table structure setup dynamic and transfer API structure to some reasonable DB structure. Currently hardcoded.

## Low priority / cleanup
- setup.sh - set default user agent according to pyproject.toml
