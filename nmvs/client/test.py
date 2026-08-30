import os
import logging
from conf.myconfigparser import MyConfiguration


print(MyConfiguration.get_value("database_url"))
