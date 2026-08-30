# NMVS-BIDE Installation Guide

## Prep the database

Set up a MySQL database and allow a remote user to do necessary things:
```
CREATE DATABASE <your-database-name> CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER '<your-user-name>'@'%' IDENTIFIED BY '<your-strong-passwor>';
GRANT ALTER, CREATE, INDEX, INSERT, SHOW VIEW, UPDATE, SELECT ON `<your-database-name>`.* TO '<your-user-name>'@'%';
FLUSH PRIVILEGES;
```

## 1. Prep the VM
(as root)
apt update && apt install sudo git python3 python3.13-venv -y
adduser nmvs
usermod -aG sudo nmvs
mkdir -p /opt/nmvs-services
chown -R nmvs:nmvs /opt/nmvs-services 

## 1. Clone the repository

As user who will run thing
```
git clone git@github.com:nemadtegid/nmvs-bide.git
cd nmvs-bide
```

## 2. Install NMVS package

Check in the "nmvs/logging.conf" file if the log folder and file name are set according to your requirements nad expecations.

Execute the setup script that uses pyproject.toml for main configuration.
Review the file before executing.
```
./setup.sh()
```

## 3. Set secrets

If the secrets come from your execution environment... do something else.

Adjust the variables in the .serverts.env (created by the setup.sh script) file according to your setup.

To test, if the environment variables work use the "--test" execution mode. See execution examples for this.

## 4. Usage

Example usage in [exec-examples.sh](scripts/exec-examples.sh)
Cron example in [nmvs-cron.sh](scripts/nmvs-cron.sh)

