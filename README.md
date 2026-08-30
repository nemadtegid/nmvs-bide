# NMVS-BIDE Project 

This repository contains the community version of National Medicine Verification System 
Business Inteligence Data Extractor (NMVS-BIDE), used for
processing NMVS product data from a Solidsoft Reply NMVS Blueprint system.

Meant to be used as a cron job to fetch data from NMVS reports and persist it in a MySQL database. Good place to build local business intelligence on.  
All logic is implemented in Python and installed as an editable package using
`pyproject.toml`.

## Project Structure

```
nmvs/
├── client/
│   ├── client.py
│   └── test.py
├── importer/
│   ├── nmvs_data.py
│   └── nmvs_exception.py (Not used by client.py)
├── conf/
│   ├── myconfigparser.py
│   └── logging.conf
├── scripts/
│   ├── exec-examples.sh
│   └── nmvs-cron.sh
└── __init__.py
setup.sh
clean-venv.sh
pyproject.toml
```

[Installation](INSTALLATION_GUIDE.md)

[Usage examples](scripts/exec-examples.sh)

[To do](TODO.md)

Licensed under the MIT License. See [LICENSE](LICENSE) for details.
