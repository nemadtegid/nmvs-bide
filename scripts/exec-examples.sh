
# This file is not meant for direct execution!
############################################
# Here are exanmples for how to use the NMVS-BIDE client to run reports from the SSR NMVS Blueprint Reporting API.
# Some for running from CLI
#

#############################################
# Before running those examples CD to the project directory and activate the virtual environment with and load secrets
. "venv/bin/activate"
source .sercrets.env

# ... to check if the environment is working, run the system check. 
python -m nmvs.client.client --test

# ... then run "Snapshot" report.
python -m nmvs.client.client -n Snapshot

# ... or run "OrganisationsSummaryReport" report
python -m nmvs.client.client -n OrganisationsSummaryReport

# ... or run "ExceptionAuditTrailReport" (default to 1 day of data)
python -m nmvs.client.client -n ExceptionsAuditTrailReport

# ... or run "ExceptionsAuditTrailReport" with 3 days of data (default is 1 day)
python -m nmvs.client.client -n ExceptionsAuditTrailReport -d 3

#############################################
# Cron example
#########################################
# Open crontab for edditing
crontab -e
# Add the following line to run the reports daily at 2am
# Adjust the path to the absolute path of the project directory and log file target.
# Adjust the nmvs-cron.sh to your regular data extraction needs.
0 2 * * * <adjust-for-absolute-path>/scripts/nmvs-cron.sh 2>&1
