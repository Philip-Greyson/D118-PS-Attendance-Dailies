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
SCHOOL_ID = 5  # Your school ID
UP_THRESHOLD = 5  # Number of UP codes in a single day before converting to AB
TODAY = datetime.date.today()  # Today's date
UNEXCUSED_PERIOD_CODE = 'UP'  # The meeting attendance code to count
ABSENT_FULLDAY_CODE = 'AB'  # The daily attendance code to apply

print(f'DBUG: DB Username: {DB_UN} | DB Password: {DB_PW} | DB Server: {DB_CS}')
print(f'DBUG: Processing date: {TODAY}')


if __name__ == '__main__':
    with open('MeetingAttConversionLog.txt', 'w') as log:
        startTime = datetime.datetime.now()
        startTime = startTime.strftime('%H:%M:%S')
        print(f'Execution started at {startTime}')
        print(f'Execution started at {startTime}', file=log)
        print(f'INFO: Processing attendance for {TODAY}')
        print(f'INFO: Processing attendance for {TODAY}', file=log)

        fullday_code_id = None
        
        # Get the AB attendance code ID from the database
        try:
            with oracledb.connect(user=DB_UN, password=DB_PW, dsn=DB_CS) as con:
                with con.cursor() as cur:
                    print('INFO: Database connection established')
                    print('INFO: Database connection established', file=log)
                    ps = acme_powerschool.api('d118-sandbox.info', client_id=D118_API_ID, client_secret=D118_API_SECRET)
                    
                    # Get the attendance code ID for our full-day absent code so we can use it to insert the daily absence later via API
                    cur.execute('SELECT ac.id, t.yearid FROM attendance_code ac LEFT JOIN terms t ON ac.yearid = t.yearid \
                                WHERE ac.att_code = :code AND ac.schoolid = :school AND t.isyearrec = 1 AND t.schoolid = :school \
                                AND :today BETWEEN t.firstday AND t.lastday', code=ABSENT_FULLDAY_CODE, school=SCHOOL_ID, today=TODAY)  # use the between to check for terms that contain today so we can always have the correct year
                    result = cur.fetchone()  # only fetch the first result since there should be only one code per school per year
                    if result:
                        fullday_code_id = result[0]
                        year_id = result[1]
                        print(f'INFO: Found {ABSENT_FULLDAY_CODE} attendance code ID: {fullday_code_id} for year ID: {year_id}')
                        print(f'INFO: Found {ABSENT_FULLDAY_CODE} attendance code ID: {fullday_code_id} for year ID: {year_id}', file=log)
                    else:
                        print(f'ERROR: Could not find {ABSENT_FULLDAY_CODE} attendance code')
                        print(f'ERROR: Could not find {ABSENT_FULLDAY_CODE} attendance code', file=log)
                        exit(1)

                    # get the meeting attendance from today using the pssis_attendance_meeting view, filtering to just entries that have our unexcused period code
                    # use count and group by to get the number of UP codes per student for today so we dont have to count them in python
                    try:
                        cur.execute('SELECT name, student_number, studentid, count(*) as count FROM pssis_attendance_meeting \
                                    WHERE att_code = :code AND schoolid = :school AND att_date = :today \
                                    GROUP BY student_number, name, student_number, studentid', code=UNEXCUSED_PERIOD_CODE, school=SCHOOL_ID, today=TODAY)
                        absences = cur.fetchall()
                        for absence in absences:
                            stuName = absence[0]
                            stuNum = str(int(absence[1]))
                            stuID = absence[2]
                            absenceCount = absence[3]
                            print(f'DBUG: Student {stuName} with student number {stuNum} has {absenceCount} unexcused period absences today')
                            if absenceCount >= UP_THRESHOLD:
                                print(f'INFO: Student {stuName} with student number {stuNum} meets threshold with {absenceCount} unexcused period absences today')
                                print(f'INFO: Student {stuName} with student number {stuNum} meets threshold with {absenceCount} unexcused period absences today', file=log)
                                # create the daily attendance record via API
                                try:
                                    # Get a template for the student and date
                                    templateData = {"studentid": stuID, "dcid": 0, "att_date": TODAY.strftime('%Y-%m-%d')}
                                    template = ps.post('/ws/schema/query/com.pearson.core.attendance.time_attendance_template', data=json.dumps(templateData))
                                    print(template.json())
                                    data = {
                                        "name": "test",
                                        "record":[
                                            {
                                                "name": "test inner",
                                                "tables": 
                                                {
                                                    "attendance": {
                                                        "attendance_codeid": str(fullday_code_id),
                                                        "calendar_dayid": "126664",  # todo: look this up dynamically 
                                                        "schoolid": str(SCHOOL_ID),
                                                        "yearid": str(year_id),
                                                        "studentid": str(stuID),
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
                                    print(result.status_code)
                                    print(result.json())
                                except Exception as er:
                                    print(f'ERROR while creating daily attendance for student ID {stuID}: {er}')
                                    print(f'ERROR while creating daily attendance for student ID {stuID}: {er}', file=log)
                                # create_daily_attendance(ps, SCHOOL_ID, stuID, TODAY, fullday_code_id, absenceCount, log)
                            # print(f'{absence}')
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