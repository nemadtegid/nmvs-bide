'''
Created on Nov 14, 2024

@author: reinholdsojer
'''

import requests
import json
from nmvs.conf.myconfigparser import MyConfiguration
from datetime import datetime, timedelta, timezone, time
import time as ttime
import logging

def _detect_encoding_from_headers(resp):
    ct = resp.headers.get('Content-Type', '') or ''
    # Try header-declared encoding first
    if 'charset=' in ct.lower():
        # requests should pick this up, but enforce explicitly
        enc = ct.split('charset=')[-1].split(';')[0].strip()
        return enc
    # Heuristic: CSV from NMVS is typically ISO-8859-1
    if 'text/csv' in ct.lower():
        return 'iso-8859-1'
    return None

def _safe_preview(resp, maxlen=120):
    try:
        return resp.json()
    except Exception:
        enc = resp.encoding or _detect_encoding_from_headers(resp) or 'utf-8'
        try:
            return (resp.content[:maxlen]).decode(enc, errors='replace')
        except Exception:
            return str(resp.content[:maxlen])

class Reports:
    
    def __init__(self):
        '''
        Constructor
        '''
        try:
            MyConfiguration.initialize_logging()
        except Exception:
            logging.basicConfig(level=logging.INFO)

        logging.info("Initialised Reports")
        
    from datetime import datetime, timedelta

    def __calculate_date_range(self, days_in_past: int, *, with_millis: bool = False):
        """
        Rerturns ISO8601-Strings in UTC :
          - fromDate: 00:00:00Z
          - toDate:   23:59:59Z (or 23:59:59.999Z if with_millis=True)
        """
        now_utc = datetime.now(timezone.utc)
        target_day = (now_utc - timedelta(days=days_in_past)).date()

        # Start des Tages
        start_dt = datetime.combine(target_day, time(0, 0, 0, tzinfo=timezone.utc))

        # Ende des Tages
        if with_millis:
            end_dt = datetime.combine(target_day, time(23, 59, 59, 999000, tzinfo=timezone.utc))  # 23:59:59.999Z
            timespec = "milliseconds"
        else:
            end_dt = datetime.combine(target_day, time(23, 59, 59, tzinfo=timezone.utc))          # 23:59:59Z
            timespec = "seconds"

        # ISO8601 + 'Z'
        fromDate = start_dt.isoformat(timespec=timespec).replace("+00:00", "Z")
        toDate   = end_dt.isoformat(timespec=timespec).replace("+00:00", "Z")

        # print(f"Calculated date range for {days_in_past} days in the past: fromDate={fromDate}, toDate={toDate}")

        return fromDate, toDate

    def __print_json(self,response) :
        try:
            logging.debug(json.dumps(response.json(), indent=4))
        except:
            logging.debug(response)

    def __wait(self, date_string):
        # convert date string
        destination_time = datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%S.%fZ")
    
        # get current time
        current_time = datetime.utcnow()
    
        # wait until destination time reached
        while current_time < destination_time:
            logging.info(f"Wait... current time: {current_time}, destination time: {destination_time}")
            # using time from import time
            ttime.sleep(20)  # wait 20 secondds
            current_time = datetime.utcnow()
    
        logging.info("Destination time reached, continue!")
        
        
    def __get_token(self):
        
        url = MyConfiguration.get_value('nmvs_token_url')
        client_id = MyConfiguration.get_value('nmvs_client_id')
        client_secret = MyConfiguration.get_value('nmvs_client_secret')
        
        mydata = {
            'client_id' : client_id,
            'client_secret' : client_secret,
            'grant_type' : 'client_credentials'
        }

        response = requests.post(url, data=mydata)
        return response.json()['access_token']


    def __create_headers(self):
        
        token = self.__get_token()    
        emvs_api_version = MyConfiguration.get_value('emvs_api_version')
        nmvs_user_agent = MyConfiguration.get_value('nmvs_user_agent')
        
        myheaders = {
            "Authorization" : "Bearer " + token,
            "Accept-Language" : "en",
            "Content-Type" : "application/json", 
            "emvs-api-version" : emvs_api_version,
            "User-Agent" : nmvs_user_agent
        }
        return myheaders
    
    
    def get_all_available_report_types(self) :
    
        url = MyConfiguration.get_value('nmvs_report_url') + "/report-types"
        myheaders = self.__create_headers()
        
        response = requests.get(url, headers=myheaders)
        logging.debug(self.__print_json(response))
        return response

    def get_specific_report_type(self, reportTypeId) :
    
        url = MyConfiguration.get_value("nmvs_report_url") + '/report-types'
        
        myheaders = self.__create_headers()
    
        response = requests.get(url + "/" + reportTypeId, headers=myheaders)
        # print(self.__print_json(response))
        return response
     
    # before is an integer values 0..n of days for retrieving older snapshot. before = 0 fetches the actual day. before = 1 the day before and so on
    # returns xls stream of snapshot
    def get_daily_snapshot_report(self, days_in_past=0):
        
        # 2024-12-09T12:50:00.153Z
        # to_datetime = request_time + timedelta(minutes=5)
        
        myFromDate, myToDate = self.__calculate_date_range(days_in_past)
     
       
        response = self.get_list_of_requested_reports(fromDate=myFromDate, toDate=myToDate, reportType="DailySnapshot")
        
        response.encoding = 'utf-8' 
        
        if response.json() is None :
            return None
        result = response.json()
        
        if result["operationCode"] != "15100000":
            return None
        
        reports = result["reports"]
        if len(reports) != 1:
            return None 
        report = reports[0]
        
        uri = report.get("uri")        
        response = self.get_report(uri)
        
        return response
        
    def get_list_of_requested_reports(self, **kwargs):
        url = MyConfiguration.get_value('nmvs_report_url') + '/report-requests'
        myheaders = self.__create_headers()
        
        mydata = { }
        
        for k, v in kwargs.items():
            if k == "fromDate":
                mydata["fromDate"] = v
            if k == "toDate":
                mydata["toDate"] = v   
            if k == "reportType":
                mydata["reportType"] = v
            if k == "requestedBy":
                mydata["requestedBy"] = v
            if k == "title":
                mydata["title"] = v
                
        response = requests.get(url, params=mydata, headers=myheaders)
        
        return response
    
    def request_transactions_report(self):
        
        # Transactions by Transaction Type Metric Report
        url = MyConfiguration.get_value('nmvs_report_url') + '/report-request'
        
        myheaders = self.__create_headers()

        mydata = {
         "report Type Id": "UserActivityReport",
         "name": "User Activity Report",
         "requested By": "NMVS automation",
         "parameters": {
             "startDate" : "2024-11-09",
             "endDate" : "2024-11-10"
              }
        }
    
        request_time = datetime.utcnow()
        response = requests.post(url, json=mydata, headers=myheaders)
        
        eta = response.json()['eta']
        
        logging.info(f"Request Time: {request_time}")
        logging.info("ETA: " + eta)
        
        url = MyConfiguration.get_value('nmvs_report_url') + '/report-requests'
                
        from_date_string = request_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        to_datetime = request_time + timedelta(minutes=5)
        
        to_date_string = to_datetime.strftime("≈") 
        
        my_params = {
            "fromDate": from_date_string,
            "toDate": to_date_string,
            "reportType": "UserActivityReport",
            "requestedBy": "NMVS automation"
        }
        
        response = requests.get(url, headers=myheaders, params=my_params)
        
        logging.debug(response.json())
        
        response.json()['uri']
        response.json()['id']
        
        logging.debug(response.json())
        return response    
    
    def get_organisations_summary_report(self):
                
        # report-request
        url = MyConfiguration.get_value('nmvs_report_url') + '/report-request'
        
        myheaders = self.__create_headers()
    
        mydata = {
         "report Type Id": "OrganisationsSummaryReport",
         "name": "Organisations Summary Report",
         "requested By": "NMVS automation",
        }
    
        request_time = datetime.now(timezone.utc)
        # Request new report
        response = requests.post(url, json=mydata, headers=myheaders)

        logging.debug(f"response 1. post-request: {response}")
        eta = response.json()['eta']
        
        logging.info(f"Request Time: {request_time}")
        logging.info(f"ETA: {eta}")
        self.__wait(eta)
        
        url = MyConfiguration.get_value('nmvs_report_url') + '/report-requests'
                
        from_date_string = request_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        to_datetime = request_time + timedelta(minutes=5)
        
        to_date_string = to_datetime.strftime("%Y-%m-%dT%H:%M:%S.%fZ") 
        
        my_params = {
            "fromDate": from_date_string,
            "toDate": to_date_string,
            "reportType": "OrganisationsSummaryReport",
            "requestedBy": "NMVS automation"
        }

        response = requests.get(url, headers=myheaders, params=my_params)
        
        logging.debug(f"response 2. get-request: {response.json()}")
        
        if len(response.json().get('reports', [])) > 1:
            logging.info("Warning: Several reports were generated at the same time. The first report is returned.")
        
        uri = response.json()['reports'][0].get('uri')
        
        logging.info(f"Report will be retrieved from: {uri}")
     
        response = self.get_report(uri)   
        return response    
    
    def get_exceptions_audit_trail_report(self, days_in_past: int = 1):

        myStartDateTime, myEndDateTime = self.__calculate_date_range(days_in_past)
        
        # Request new ExceptionsAuditTrailReport

        url = MyConfiguration.get_value('nmvs_report_url') + '/report-request'
                
        myheaders = self.__create_headers()
    
        mydata = {
         "report Type Id": "ExceptionsAuditTrailReport",
         "name": "Exceptions Audit Trail Report",
         "requested By": "NMVS automation",
         "parameters": {
             "startDateTime" : myStartDateTime,
             "endDateTime" : myEndDateTime,
             "syntheticMonitoring" : "false"
              }
        }
    
        request_time = datetime.now(timezone.utc)
        response = requests.post(url, json=mydata, headers=myheaders)
        
        logging.debug(f"response 1. post-request: {response}")
        eta = response.json()['eta']
        
        logging.info(f"Requested period: {myStartDateTime} to {myEndDateTime}")
        logging.info(f"Request Time: {request_time}")
        logging.info("ETA: " + eta)
        self.__wait(eta)

        # Get report requests for the last 5 minutes to find the URI of the generated report
        url = MyConfiguration.get_value('nmvs_report_url') + '/report-requests'
    
        from_date_string = request_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        to_datetime = request_time + timedelta(minutes=5)
        
        to_date_string = to_datetime.strftime("%Y-%m-%dT%H:%M:%S.%fZ") 
        
        my_params = {
            "fromDate": from_date_string,
            "toDate": to_date_string,
            "reportType": "ExceptionsAuditTrailReport",
            "requestedBy": "NMVS automation"
        }
        
        response = requests.get(url, headers=myheaders, params=my_params)
        
        logging.debug(f"response 2. get-request: {response.json()}")
        # logging.info(f"response 2. get-request: {response.json()}")
        
        if len(response.json().get('reports', [])) > 1:
            logging.info("Warning: Several reports were generated at the same time. The first report is returned.")
        
        uri = response.json()['reports'][0].get('uri')
        
        logging.info(f"Report will be retrieved from: {uri}")
        
        # print(response.json())

        response = self.get_report(uri)   
        return response
    
    def request_user_activity_report(self):
                
        # report-request
        
        url = MyConfiguration.get_value('nmvs_report_url') + '/report-request'
        
        myheaders = self.__create_headers()

        mydata = {
         "report Type Id": "UserActivityReport",
         "name": "User Activity Report",
         "requested By": "NMVS automation",
         "parameters": {
             "startDate" : "2024-11-09",
             "endDate" : "2024-11-10"
              }
        }
    
        request_time = datetime.utcnow()
        response = requests.post(url, json=mydata, headers=myheaders)
        
        eta = response.json()['eta']
        
        logging.info(f"Request Time: {request_time}")
        logging.info("ETA: " + eta)
        # https://api-ite.nmvo.eu/report/reports/{reportId}
        self.__wait(eta)
        
        # https://api-ite.nmvo.eu/report/report-requests[?fromDate][&toDate][&reportType][&requestedBy][&title]
        url = MyConfiguration.get_value('nmvs_report_url') + '/report-requests'
                
        from_date_string = request_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        to_datetime = request_time + timedelta(minutes=5)
        
        to_date_string = to_datetime.strftime("%Y-%m-%dT%H:%M:%S.%fZ") 
        
        my_params = {
            "fromDate": from_date_string,
            "toDate": to_date_string,
            "reportType": "UserActivityReport",
            "requestedBy": "NMVS automation"
        }
        
        response = requests.get(url, headers=myheaders, params=my_params)
        
        logging.debug(response.json())
        
        self.__wait(eta)
        
        uri = response.json()['uri']
        # id = response.json()['id']
     
        report_response = self.get_report(uri)   
        logging.debug(f"retrieving report {_safe_preview(report_response)}")
        return report_response    

    def get_report(self, uri):
        my_headers = self.__create_headers()
        response = requests.get(uri, headers=my_headers)
        # Ensure proper text encoding for CSV
        enc = _detect_encoding_from_headers(response)
        if enc and not response.encoding:
            response.encoding = enc
        # Default heuristic for NMVS CSV if still unknown
        if not response.encoding and (uri.lower().endswith('.csv') or 'text/csv' in (response.headers.get('Content-Type','').lower())):
            response.encoding = 'iso-8859-1'
        return response 
