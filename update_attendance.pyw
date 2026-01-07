"""Convert meeting attendance UP codes to daily AB codes when threshold is exceeded for today.

Runs daily to check today's meeting attendance and create daily attendance if threshold met.

Needs oracledb: pip install oracledb --upgrade
Needs the ACME PowerSchool library from https://easyregpro.com/acme.php
"""

import datetime
import json
import os

import acme_powerschool
import oracledb

# PowerSchool API credentials
D118_API_ID = os.environ.get("POWERSCHOOL_API_ID_2")
D118_API_SECRET = os.environ.get("POWERSCHOOL_API_SECRET_2")

# Database credentials
DB_UN = os.environ.get('POWERSCHOOL_READ_USER')
DB_PW = os.environ.get('POWERSCHOOL_DB_PASSWORD')
DB_CS = os.environ.get('POWERSCHOOL_SAND_DB')

# Configuration
SCHOOL_IDS = [5]  # List of school IDs to process
HALFDAY_THRESHOLD = 2  # Number of UP codes in a single day before it counts as a half-day absence
FULLDAY_THRESHOLD = 5  # Number of UP codes in a single day before it counts as a full-day absence
TODAY = datetime.date.today()  # Today's date
UNEXCUSED_PERIOD_CODE = 'UP'  # The meeting attendance code to count
ABSENT_HALFDAY_CODE = 'UH'  # The half-day attendance code to apply for the daily attendance
ABSENT_FULLDAY_CODE = 'UN'  # The daily attendance code to apply for the daily attendance
OVERRIDE_EXISTING_DAYCODE = False  # Whether to override existing daily attendance codes for the day

print(f'DBUG: DB Username: {DB_UN} | DB Password: {DB_PW} | DB Server: {DB_CS}')

def create_daily_attendance(ps, school_id, calendar_day, student_id, year_id, attendance_code_id, log):
    """Create a daily attendance record via PowerSchool API."""
    try:
        data = {
            "name": "Daily Attendance Automation",
            "record":[
                {
                    "name": "Daily Attendance Automation",
                    "tables": 
                    {
                        "attendance": {
                            "attendance_codeid": str(attendance_code_id),
                            "calendar_dayid": str(calendar_day),
                            "schoolid": str(school_id),
                            "yearid": str(year_id),
                            "studentid": str(student_id),
                            "att_mode_code": "ATT_ModeDaily",
                            "att_comment": f"Auto-generated from {absenceCount} meeting {UNEXCUSED_PERIOD_CODE} codes",
                            "att_date": TODAY.strftime('%Y-%m-%d'),
                            "programid": "0"
                        }
                    }
                }
            ]
        }
    
        result = ps.post('ws/attendance/daily_time', data=json.dumps(data))
        if result.status_code != 200:
            print(f'ERROR: Failed to create daily attendance for student ID {student_id}: {result}')
            print(f'ERROR: Failed to create daily attendance for student ID {student_id}: {result}', file=log)
    except Exception as er:
        print(f'ERROR while creating daily attendance for student ID {student_id}: {er}')
        print(f'ERROR while creating daily attendance for student ID {student_id}: {er}', file=log)

if __name__ == '__main__':
    with open('MeetingAttConversionLog.txt', 'w') as log:
        startTime = datetime.datetime.now()
        startTime = startTime.strftime('%H:%M:%S')
        print(f'Execution started at {startTime}')
        print(f'Execution started at {startTime}', file=log)

        for school in SCHOOL_IDS:
            print(f'INFO: Processing attendance at building {school}for {TODAY}')
            print(f'INFO: Processing attendance at building {school} for {TODAY}', file=log)

            fullday_code_id = None  # initialize variables to hold attendance code IDs for each school
            halfday_code_id = None
            calendar_day = None

            try:
                with oracledb.connect(user=DB_UN, password=DB_PW, dsn=DB_CS) as con:
                    with con.cursor() as cur:
                        print('INFO: Database connection established')
                        print('INFO: Database connection established', file=log)
                        ps = acme_powerschool.api('d118-sandbox.info', client_id=D118_API_ID, client_secret=D118_API_SECRET)  # start the PowerSchool API session
                        
                        # Get the attendance code ID for our full-day absent code so we can use it to insert the daily absence later via API
                        cur.execute('SELECT ac.id, t.yearid FROM attendance_code ac LEFT JOIN terms t ON ac.yearid = t.yearid \
                                    WHERE ac.att_code = :code AND ac.schoolid = :school AND t.isyearrec = 1 AND t.schoolid = :school \
                                    AND :today BETWEEN t.firstday AND t.lastday', code=ABSENT_FULLDAY_CODE, school=school, today=TODAY)  # use the between to check for terms that contain today so we can always have the correct year
                        result = cur.fetchone()  # only fetch the first result since there should be only one code per school per year
                        if result:
                            fullday_code_id = result[0]
                            year_id = result[1]
                            print(f'DBUG: Found {ABSENT_FULLDAY_CODE} attendance code ID: {fullday_code_id} for year ID: {year_id} at building {school}')
                            print(f'DBUG: Found {ABSENT_FULLDAY_CODE} attendance code ID: {fullday_code_id} for year ID: {year_id} at building {school}', file=log)
                        else:
                            print(f'ERROR: Could not find {ABSENT_FULLDAY_CODE} attendance code at building {school} for year ID {year_id}', file=log)
                            print(f'ERROR: Could not find {ABSENT_FULLDAY_CODE} attendance code at building {school} for year ID {year_id}', file=log)
                            exit(1)

                        # Get the attendance code ID for our half-day absent code so we can use it to insert the daily absence later via API
                        cur.execute('SELECT ac.id FROM attendance_code ac LEFT JOIN terms t ON ac.yearid = t.yearid \
                                    WHERE ac.att_code = :code AND ac.schoolid = :school AND t.isyearrec = 1 AND t.schoolid = :school \
                                    AND :today BETWEEN t.firstday AND t.lastday', code=ABSENT_HALFDAY_CODE, school=school, today=TODAY)  # use the between to check for terms that contain today so we can always have the correct year
                        result = cur.fetchone()  # only fetch the first result since there should be only one code per school per year
                        if result:
                            halfday_code_id = result[0]
                            print(f'DBUG: Found {ABSENT_HALFDAY_CODE} attendance code ID: {halfday_code_id} for year ID: {year_id} at building {school}')
                            print(f'DBUG: Found {ABSENT_HALFDAY_CODE} attendance code ID: {halfday_code_id} for year ID: {year_id} at building {school}', file=log)
                        else:
                            print(f'ERROR: Could not find {ABSENT_HALFDAY_CODE} attendance code at building {school} for year ID {year_id}', file=log)
                            print(f'ERROR: Could not find {ABSENT_HALFDAY_CODE} attendance code at building {school} for year ID {year_id}', file=log)
                            exit(1)

                        # get the calendar day ID for today to use when inserting daily attendance
                        cur.execute('SELECT id FROM calendar_day WHERE schoolid = :school AND date_value = :today', school=school, today=TODAY)
                        result = cur.fetchone()
                        if result:
                            calendar_day = result[0]
                            print(f'DBUG: Found calendar day ID: {calendar_day} for {TODAY} at building {school}')
                            print(f'DBUG: Found calendar day ID: {calendar_day} for {TODAY} at building {school}', file=log)
                        else:
                            print(f'ERROR: Could not find calendar day ID for {TODAY} at building {school}', file=log)
                            print(f'ERROR: Could not find calendar day ID for {TODAY} at building {school}', file=log)
                            exit(1)

                        # get the meeting attendance from today using the pssis_attendance_meeting view, filtering to just entries that have our unexcused period code
                        # use count and group by to get the number of UP codes per student for today so we dont have to count them in python
                        try:
                            cur.execute('SELECT name, student_number, studentid, count(*) as count FROM pssis_attendance_meeting \
                                        WHERE att_code = :code AND schoolid = :school AND att_date = :today \
                                        GROUP BY student_number, name, student_number, studentid', code=UNEXCUSED_PERIOD_CODE, school=school, today=TODAY)
                            absences = cur.fetchall()
                            for absence in absences:
                                stuName = absence[0]
                                stuNum = str(int(absence[1]))
                                stuID = absence[2]
                                absenceCount = absence[3]
                                existing_daily = False
                                print(f'DBUG: Student {stuName} with student number {stuNum} has {absenceCount} unexcused period absences today')
                                print(f'DBUG: Student {stuName} with student number {stuNum} has {absenceCount} unexcused period absences today', file=log)

                                # check to see if there is already a daily attendance record for this student for today
                                cur.execute('SELECT att_code FROM pssis_attendance_daily WHERE studentid = :stuID AND schoolid = :school AND att_date = :today', stuID=stuID, school=school, today=TODAY)
                                existing_daily = cur.fetchone()
                                
                                if HALFDAY_THRESHOLD <= absenceCount < FULLDAY_THRESHOLD:
                                    print(f'INFO: Student {stuName} with student number {stuNum} meets half day threshold with {absenceCount} unexcused period absences today')
                                    print(f'INFO: Student {stuName} with student number {stuNum} meets half day threshold with {absenceCount} unexcused period absences today', file=log)
                                    if existing_daily and not OVERRIDE_EXISTING_DAYCODE:  # if there is already a daily attendance record and we are not overriding existing codes, skip creating the half-day absence and just warn
                                        print(f'WARN: Student {stuName} with student number {stuNum} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of half-day absence due to configuration.')
                                        print(f'WARN: Student {stuName} with student number {stuNum} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of half-day absence due to configuration.', file=log)
                                    else:  # otherwise if they dont have a daily attendance record or we are overriding existing codes, create the half-day absence
                                        create_daily_attendance(ps, school, calendar_day, stuID, year_id, halfday_code_id, log)  # create the daily attendance record via API for a half day absence

                                elif absenceCount >= FULLDAY_THRESHOLD:
                                    print(f'INFO: Student {stuName} with student number {stuNum} meets full day threshold with {absenceCount} unexcused period absences today')
                                    print(f'INFO: Student {stuName} with student number {stuNum} meets full day threshold with {absenceCount} unexcused period absences today', file=log)
                                    if existing_daily and not OVERRIDE_EXISTING_DAYCODE:  # if there is already a daily attendance record and we are not overriding existing codes, skip creating the half-day absence and just warn
                                        print(f'WARN: Student {stuName} with student number {stuNum} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of full-day absence due to configuration.')
                                        print(f'WARN: Student {stuName} with student number {stuNum} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of full-day absence due to configuration.', file=log)
                                    # create the daily attendance record via API
                                    create_daily_attendance(ps, school, calendar_day, stuID, year_id, fullday_code_id, log)

                        except Exception as er:
                            print(f'ERROR while querying or processing meeting attendance: {er}')
                            print(f'ERROR while querying or processing meeting attendance: {er}', file=log)
                            
            except Exception as er:
                print(f'ERROR while connecting to database: {er}')
                print(f'ERROR while connecting to database: {er}', file=log)
                exit(1)

        endTime = datetime.datetime.now()
        endTime = endTime.strftime('%H:%M:%S')
        print(f'Execution ended at {endTime}')
        print(f'Execution ended at {endTime}', file=log)