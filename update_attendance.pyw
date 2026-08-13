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
DB_CS = os.environ.get('POWERSCHOOL_RES_DB')
API_URL = os.environ.get('POWERSCHOOL_RES_URL')

# Configuration
SCHOOL_IDS = [5]  # List of school IDs to process
MT_HALFDAY_THRESHOLD = 3  # Number of codes in a single day on Mon-Thurs before it counts as a half-day absence
F_HALFDAY_THRESHOLD = 2  # Number of codes in a single day on Friday before it counts as a half-day absence
MT_FULLDAY_THRESHOLD = 7  # Number of codes in a single day on Mon-Thurs before it counts as a full-day absence
F_FULLDAY_THRESHOLD = 6  # Number of codes in a single day on Friday before it counts as a full-day absence
TOTAL_PERIODS = 8  # Total number of periods in a day, used to determine if a student has other codes besides the special codes that should be in every period
TODAY = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=6)  # Today's date, can change for testing purposes if needed
UNEXCUSED_PERIOD_CODES = ['UP', 'UA', 'UH', 'OSS', 'OSSH', 'CV', 'SA']  # The meeting attendance codes to count
EXCUSED_PERIOD_CODES = ['EP', 'AB', 'HA']
SPECIAL_ONLY_DAY_CODES = ['MH', 'HBT', 'HOS', 'DC', 'PRM', 'TR', 'TH', 'ME']  # codes that if there are even one of, it will mark the day with the same code. These are typically special attendance codes that override any other attendance for the day.
ELEARNING_PERIOD_CODES = ['PEL']  # weird ones where get the PEL code if they are present all day but an excused half day if they have less than the full day threshold
ELEARNING_FULLDAY_PRESENT_CODE = 'PEL'  # The daily attendance code to apply for the daily attendance for a full day e-learning attendance
UNEXCUSED_ABSENCE_HALFDAY_CODE = 'UH'  # The half-day attendance code to apply for the daily attendance for an unexcused half day
UNEXCUSED_ABSENCE_FULLDAY_CODE = 'UA'  # The daily attendance code to apply for the daily attendance for an unexcused day
EXCUSED_ABSENCE_HALFDAY_CODE = 'HA'  # The half-day attendance code to apply for the daily attendance for an excused half day
EXCUSED_ABSENCE_FULLDAY_CODE = 'AB'  # The daily attendance code
OVERRIDE_EXISTING_DAYCODE = False  # Whether to override existing daily attendance codes for the day

DRY_RUN = False  # If True, will not make any changes, just log what would be done

print(f'DBUG: DB Username: {DB_UN} | DB Password: {DB_PW} | DB Server: {DB_CS}')
print(f'DBUG: Dry Run is set to {DRY_RUN}')

def create_daily_attendance(ps: any, school_id: int, calendar_day: int, student_id: int, year_id: int, attendance_code_id: int, comment: str, log: any) -> None:
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
                            "att_comment": comment,
                            "att_date": TODAY.strftime('%Y-%m-%d'),
                            "programid": "0"
                        }
                    }
                }
            ]
        }

        result = ps.post('ws/attendance/daily_time', data=json.dumps(data))
        if result.status_code != 200:
            print(f'ERROR: Failed to create daily attendance for student ID {student_id}: {result} {result.text}')
            print(f'ERROR: Failed to create daily attendance for student ID {student_id}: {result} {result.text}', file=log)
    except Exception as er:
        print(f'ERROR while creating daily attendance for student ID {student_id}: {er}')
        print(f'ERROR while creating daily attendance for student ID {student_id}: {er}', file=log)

def get_attendance_code_id(cur: any, school_id: int, code: str) -> int:
    """Get the attendance code ID for a given attendance code and school."""
    cur.execute('SELECT ac.id FROM attendance_code ac LEFT JOIN terms t ON ac.yearid = t.yearid \
                WHERE ac.att_code = :code AND ac.schoolid = :school AND t.isyearrec = 1 AND t.schoolid = :school \
                AND :today BETWEEN t.firstday AND t.lastday', code=code, school=school_id, today=TODAY)
    result = cur.fetchone()
    if result is not None:
        print(f'DBUG: Found attendance code ID: {result[0]} for code {code} at building {school_id}')
        print(f'DBUG: Found attendance code ID: {result[0]} for code {code} at building {school_id}', file=log)
        return result[0]
    else:
        print(f'ERROR: Could not find {code} attendance code at building {school_id}')
        print(f'ERROR: Could not find {code} attendance code at building {school_id}', file=log)
        exit(1)

def get_year_id(cur: any, school_id: int) -> int:
    """Get the current year ID for a given school."""
    cur.execute('SELECT yearid FROM terms WHERE isyearrec = 1 AND schoolid = :school AND :today BETWEEN firstday AND lastday', school=school_id, today=TODAY)
    result = cur.fetchone()
    if result is not None:
        print(f'DBUG: Found current year ID: {result[0]} for building {school_id} for date {TODAY}')
        print(f'DBUG: Found current year ID: {result[0]} for building {school_id} for date {TODAY}', file=log)
        return result[0]
    else:
        print(f'ERROR: Could not find current year ID at building {school_id} for date {TODAY}, it may be summer break or the year has not been set up yet.')
        print(f'ERROR: Could not find current year ID at building {school_id} for date {TODAY}, it may be summer break or the year has not been set up yet.', file=log)
        exit(1)

def get_calendar_day_id(cur: any, school_id: int) -> int:
    """Get the calendar day ID for a given school and date."""
    cur.execute('SELECT id FROM calendar_day WHERE schoolid = :school AND date_value = :today', school=school_id, today=TODAY)
    result = cur.fetchone()
    if result is not None:
        print(f'DBUG: Found calendar day ID: {result[0]} for building {school_id} for date {TODAY}')
        print(f'DBUG: Found calendar day ID: {result[0]} for building {school_id} for date {TODAY}', file=log)
        return result[0]
    else:
        print(f'ERROR: Could not find calendar day ID at building {school_id} for date {TODAY}')
        print(f'ERROR: Could not find calendar day ID at building {school_id} for date {TODAY}', file=log)
        exit(1)

def process_elearning(codes: list, elearning_fullday_code_id: int, excused_halfday_code_id: int, calendar_day: int, year_id: int, school: int) -> None:
    """Process the special e-learning attendance code for students who have the PEL code.

    Operates kinda in reverse of absences, they need 7 PEL codes to get the full day, and 3-6 to get an excused half day.
    If they have less than 3 PEL codes, they get nothing. This is because the PEL code is a present code, not an absence code.
    """
    for meet_code in codes:
        print(f'INFO: Processing e-learning attendance for period code {meet_code} at building {school} for {TODAY}')
        print(f'INFO: Processing e-learning attendance for period code {meet_code} at building {school} for {TODAY}', file=log)
        try:
            cur.execute('SELECT name, student_number, studentid, count(*) as count FROM pssis_attendance_meeting \
                        WHERE att_code = :code AND schoolid = :school AND att_date = :today \
                        GROUP BY student_number, name, student_number, studentid', code=meet_code, school=school, today=TODAY)
            absences = cur.fetchall()
            for absence in absences:
                stu_name = absence[0]
                stu_num = str(int(absence[1]))
                stu_id = absence[2]
                present_count = absence[3]
                print(f'DBUG: Student {stu_name} with student number {stu_num} has {present_count} {meet_code} present codes today')
                print(f'DBUG: Student {stu_name} with student number {stu_num} has {present_count} {meet_code} present codes today', file=log)

                # check to see if there is already a daily attendance record for this student for today
                cur.execute('SELECT att_code FROM pssis_attendance_daily WHERE studentid = :stuID AND schoolid = :school AND att_date = :today', stuID=stu_id, school=school, today=TODAY)
                existing_daily = cur.fetchone()
                # print(f'DBUG: Existing daily attendance code for {stu_name}: {existing_daily[0]}')
                # print(f'DBUG: Existing daily attendance code for {stu_name}: {existing_daily[0]}', file=log)

                if present_count >= fullday_threshold:
                    if existing_daily and existing_daily[0] is not None and not OVERRIDE_EXISTING_DAYCODE:  # if there is already a daily attendance record and we are not overriding existing codes, skip creating the special code and just warn
                        print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of daily attendance code of {elearning_fullday_code_id} due to configuration.')
                        print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of daily attendance code of {elearning_fullday_code_id} due to configuration.', file=log)
                    else:
                        comment_string = f"E-Learning present code auto-generated from {present_count} meeting {meet_code} codes which met the threshold of {fullday_threshold} for a full-day e-learning attendance"
                        if not DRY_RUN:
                            create_daily_attendance(ps, school, calendar_day, stu_id, year_id, elearning_fullday_code_id, comment_string, log)  # create the daily attendance record via API for a full day e-learning attendance
                        else:
                            print(f'WARN: Dry run enabled, would have created full-day e-learning attendance for student {stu_name} with student number {stu_num}')
                            print(f'WARN: Dry run enabled, would have created full-day e-learning attendance for student {stu_name} with student number {stu_num}', file=log)
                elif halfday_threshold <= present_count < fullday_threshold:
                    if existing_daily and existing_daily[0] is not None and not OVERRIDE_EXISTING_DAYCODE:  # if there is already a daily attendance record and we are not overriding existing codes, skip creating the special code and just warn
                        print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of daily attendance code of {elearning_fullday_code_id} due to configuration.')
                        print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of daily attendance code of {elearning_fullday_code_id} due to configuration.', file=log)
                    else:
                        comment_string = f"E-Learning half-day code auto-generated from {present_count} meeting {meet_code} codes which met the threshold of {halfday_threshold} for a half-day e-learning attendance"
                        if not DRY_RUN:
                            create_daily_attendance(ps, school, calendar_day, stu_id, year_id, excused_halfday_code_id, comment_string, log)  # create the daily attendance record via API for a half day e-learning attendance
                        else:
                            print(f'WARN: Dry run enabled, would have created half-day e-learning attendance for student {stu_name} with student number {stu_num}')
                            print(f'WARN: Dry run enabled, would have created half-day e-learning attendance for student {stu_name} with student number {stu_num}', file=log)
        except Exception as er:
            print(f'ERROR while querying or processing meeting attendance for code {meet_code}: {er}')
            print(f'ERROR while querying or processing meeting attendance for code {meet_code}: {er}', file=log)

def process_special_day_codes(codes: list, calendar_day: int, year_id: int, school: int) -> None:
    """Process the special codes that should be in every period, so if there is even one, mark the day code as the same code.

    We want to log any other codes that are in the meeting attendance day, since there SHOULD not be anything else.
    """
    student_other_codes = {}  # Dictionary to hold student IDs and their other codes so we can log them if they have any other codes besides the special code
    for special_code in codes:
        print(f'INFO: Processing special attendance code {special_code} at building {school} for {TODAY}')
        print(f'INFO: Processing special attendance code {special_code} at building {school} for {TODAY}', file=log)
        try:
            cur.execute('SELECT name, student_number, studentid, count(*) as count FROM pssis_attendance_meeting \
                        WHERE att_code = :code AND schoolid = :school AND att_date = :today \
                        GROUP BY student_number, name, studentid', code=special_code, school=school, today=TODAY)
            special_codes = cur.fetchall()
            for special in special_codes:
                stu_name = special[0]
                stu_num = str(int(special[1]))
                stu_id = special[2]
                absence_count = special[3]
                print(f'DBUG: Student {stu_name} with student number {stu_num} has a {absence_count} occurrence(s) of special attendance code {special_code} today')
                print(f'DBUG: Student {stu_name} with student number {stu_num} has a {absence_count} occurrence(s) of special attendance code {special_code} today', file=log)

                if absence_count < TOTAL_PERIODS:  # if they have less than the total number of periods occurrences of the special code, check to see if they have any other codes for today and log them
                    cur.execute('SELECT att_code, count(*) as count FROM pssis_attendance_meeting \
                                WHERE studentid = :stuID AND schoolid = :school AND att_date = :today AND att_code != :code \
                                GROUP BY att_code', stuID=stu_id, school=school, today=TODAY, code=special_code)
                    other_codes = cur.fetchall()
                    if other_codes:
                        student_other_codes[stu_num] = {'name': stu_name, 'id': stu_id, 'main_code': special_code, 'other_codes': other_codes}
                        print(f'WARN: Student {stu_name} with student number {stu_num} has other attendance codes for today besides the special code {special_code}: {other_codes}')
                        print(f'WARN: Student {stu_name} with student number {stu_num} has other attendance codes for today besides the special code {special_code}: {other_codes}', file=log)
                # check to see if there is already a daily attendance record for this student for today
                cur.execute('SELECT att_code FROM pssis_attendance_daily WHERE studentid = :stuID AND schoolid = :school AND att_date = :today', stuID=stu_id, school=school, today=TODAY)
                existing_daily = cur.fetchone()
                # print(f'DBUG: Existing daily attendance code for {stu_name}: {existing_daily[0]}')
                # print(f'DBUG: Existing daily attendance code for {stu_name}: {existing_daily[0]}', file=log)
                if existing_daily and existing_daily[0] is not None and not OVERRIDE_EXISTING_DAYCODE:  # if there is already a daily attendance record and we are not overriding existing codes, skip creating the special code and just warn
                    print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of daily attendance code of {special_code} due to configuration.')
                    print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of daily attendance code of {special_code} due to configuration.', file=log)
                else:  # otherwise if they dont have a daily attendance record or we are overriding existing codes, create the special code
                    comment_string = f"Auto-generated from presence of meeting code {special_code} which override any other attendance meeting codes for the day"
                    if not DRY_RUN:
                        create_daily_attendance(ps, school, calendar_day, stu_id, year_id, get_attendance_code_id(cur, school, special_code), comment_string, log)
                    else:
                        print(f'WARN: Dry run enabled, would have created day code {special_code} for student {stu_name} with student number {stu_num}')
                        print(f'WARN: Dry run enabled, would have created day code {special_code} for student {stu_name} with student number {stu_num}', file=log)
        except Exception as er:
            print(f'ERROR while querying or processing meeting attendance for special code {special_code}: {er}')
            print(f'ERROR while querying or processing meeting attendance for special code {special_code}: {er}', file=log)
    # print out all the students who had other codes in their meeting attendance besides the special codes
    for student in student_other_codes.keys():
        code_string = ''
        print(student)
        spec_code = student_other_codes[student].get('main_code')
        for code, quantity in student_other_codes[student].get('other_codes'):
            code_string = f'{code_string} {quantity} {code} code(s),'
        print(f'ERROR: Student {student} had {code_string} in addition to their special code of {spec_code}')

def process_absences(abs_type: str, codes: list, fullday_code_id: int, halfday_code_id: int, calendar_day: int, year_id: int, school: int) -> None:
    """Process absences for each school and create daily attendance records if thresholds are met."""
    student_absences = {}  # Dictionary to hold student IDs and their absence counts so we can total between different codes
    student_info = {}  # Dictionary to hold student info (student number, name, studentid) so we can use it later when creating the daily attendance record via API

    print(f'INFO: Processing {abs_type} absences for building {school} for {TODAY}')
    print(f'INFO: Processing {abs_type} absences for building {school} for {TODAY}', file=log)
    # do a loop of all the unexcused period codes we want to check for today and process them one at a time
    for abs_code in codes:
        print(f'INFO: Processing attendance for {abs_type} period code {abs_code} at building {school} for {TODAY}')
        print(f'INFO: Processing attendance for {abs_type} period code {abs_code} at building {school} for {TODAY}', file=log)

        # get the meeting attendance from today using the pssis_attendance_meeting view, filtering to just entries that have our unexcused period code
        # use count and group by to get the number of codes per student for today so we dont have to count them in python
        try:
            cur.execute('SELECT name, student_number, studentid, count(*) as count FROM pssis_attendance_meeting \
                        WHERE att_code = :code AND schoolid = :school AND att_date = :today \
                        GROUP BY student_number, name, student_number, studentid', code=abs_code, school=school, today=TODAY)
            absences = cur.fetchall()
            # print(absences)
            for absence in absences:
                stu_name = absence[0]
                stu_num = str(int(absence[1]))
                stu_id = absence[2]
                absence_count = absence[3]
                # existing_daily = False
                student_absences[stu_num] = student_absences.get(stu_num, 0) + absence_count  # add the count of this code to the total for this student
                student_info[stu_num] = {'name': stu_name, 'id': stu_id}  # store student info for later use
                print(f'DBUG: Student {stu_name} with student number {stu_num} has {absence_count} {abs_code} absences today')
                print(f'DBUG: Student {stu_name} with student number {stu_num} has {absence_count} {abs_code} absences today', file=log)
                # print(student_absences)  # debug to see how the dictionary is being built up with counts of absences for each student
                # print(student_info)  # debug to see how the dictionary is being built up with student info for each student
        except Exception as er:
            print(f'ERROR while querying or processing meeting attendance for code {abs_code}: {er}')
            print(f'ERROR while querying or processing meeting attendance for code {abs_code}: {er}', file=log)

    # now go through each student that we had unexcused absences for and process the daily code
    for stu_num, absence_count in student_absences.items():
        stu_name = student_info[stu_num]['name']
        stu_id = student_info[stu_num]['id']
        print(f'DBUG: Student {stu_name} with student number {stu_num} has a total of {absence_count} {abs_type} period absences today')
        print(f'DBUG: Student {stu_name} with student number {stu_num} has a total of {absence_count} {abs_type} period absences today', file=log)
        # check to see if there is already a daily attendance record for this student for today
        cur.execute('SELECT att_code FROM pssis_attendance_daily WHERE studentid = :stuID AND schoolid = :school AND att_date = :today', stuID=stu_id, school=school, today=TODAY)
        existing_daily = cur.fetchone()
        # print(existing_daily)

        if halfday_threshold <= absence_count < fullday_threshold:
            print(f'INFO: Student {stu_name} with student number {stu_num} meets half day {abs_type} threshold with {absence_count} {abs_type} period absences today')
            print(f'INFO: Student {stu_name} with student number {stu_num} meets half day {abs_type} threshold with {absence_count} {abs_type} period absences today', file=log)
            comment_string = f"Auto-generated from {absence_count} meeting {abs_type} codes which met the threshold of {halfday_threshold} for a half-day {abs_type} absence"
            if existing_daily and existing_daily[0] is not None and not OVERRIDE_EXISTING_DAYCODE:  # if there is already a daily attendance record and we are not overriding existing codes, skip creating the half-day absence and just warn
                print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of half-day {abs_type} absence due to configuration.')
                print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of half-day {abs_type} absence due to configuration.', file=log)
            else:  # otherwise if they dont have a daily attendance record or we are overriding existing codes, create the half-day absence
                if not DRY_RUN:
                    create_daily_attendance(ps, school, calendar_day, stu_id, year_id, halfday_code_id, comment_string, log)  # create the daily attendance record via API for a half day absence
                else:
                    print(f'WARN: Dry run enabled, would have created half-day {abs_type} attendance for student {stu_name} with student number {stu_num}')
                    print(f'WARN: Dry run enabled, would have created half-day {abs_type} attendance for student {stu_name} with student number {stu_num}', file=log)

        elif absence_count >= fullday_threshold:
            print(f'INFO: Student {stu_name} with student number {stu_num} meets full day {abs_type} threshold with {absence_count} {abs_type} period absences today')
            print(f'INFO: Student {stu_name} with student number {stu_num} meets full day {abs_type} threshold with {absence_count} {abs_type} period absences today', file=log)
            comment_string = f"Auto-generated from {absence_count} meeting {abs_type} codes which met the threshold of {fullday_threshold} for a full-day {abs_type} absence"
            if existing_daily and existing_daily[0] is not None and not OVERRIDE_EXISTING_DAYCODE:  # if there is already a daily attendance record and we are not overriding existing codes, skip creating the half-day absence and just warn
                print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of full-day {abs_type} absence due to configuration.')
                print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of full-day {abs_type} absence due to configuration.', file=log)
            else:  # otherwise if they dont have a daily attendance record or we are overriding existing codes, create the full-day absence
                if not DRY_RUN:
                    create_daily_attendance(ps, school, calendar_day, stu_id, year_id, fullday_code_id, comment_string, log)  # create the daily attendance record via API for a full day absence
                else:
                    print(f'WARN: Dry run enabled, would have created full-day {abs_type} attendance for student {stu_name} with student number {stu_num}')
                    print(f'WARN: Dry run enabled, would have created full-day {abs_type} attendance for student {stu_name} with student number {stu_num}', file=log)

if __name__ == '__main__':
    with open('MeetingAttConversionLog.txt', 'w') as log:
        startTime = datetime.datetime.now()
        startTime = startTime.strftime('%H:%M:%S')
        print(f'Execution started at {startTime}')
        print(f'Execution started at {startTime}', file=log)

        # determine which thresholds to use based on the day of the week (Friday has different thresholds than Mon-Thurs)
        if TODAY.weekday() == 4:  # if today is Friday
            halfday_threshold = F_HALFDAY_THRESHOLD
            fullday_threshold = F_FULLDAY_THRESHOLD
            print(f'DBUG: Today is Friday, using Friday thresholds of {halfday_threshold} for half-day and {fullday_threshold} for full-day')
            print(f'DBUG: Today is Friday, using Friday thresholds of {halfday_threshold} for half-day and {fullday_threshold} for full-day', file=log)
        else:
            halfday_threshold = MT_HALFDAY_THRESHOLD
            fullday_threshold = MT_FULLDAY_THRESHOLD
            print(f'DBUG: Today is Mon-Thurs, using Mon-Thurs thresholds of {halfday_threshold} for half-day and {fullday_threshold} for full-day')
            print(f'DBUG: Today is Mon-Thurs, using Mon-Thurs thresholds of {halfday_threshold} for half-day and {fullday_threshold} for full-day', file=log)

        for school in SCHOOL_IDS:
            print(f'INFO: Processing attendance at building {school} for {TODAY}')
            print(f'INFO: Processing attendance at building {school} for {TODAY}', file=log)
            try:
                with oracledb.connect(user=DB_UN, password=DB_PW, dsn=DB_CS) as con:
                    with con.cursor() as cur:
                        print('INFO: Database connection established')
                        print('INFO: Database connection established', file=log)
                        ps = acme_powerschool.api(API_URL, client_id=D118_API_ID, client_secret=D118_API_SECRET)  # start the PowerSchool API session

                        # Get the attendance code ID for our full-day absent code so we can use it to insert the daily absence later via API
                        unexcused_fullday_code_id = get_attendance_code_id(cur, school, UNEXCUSED_ABSENCE_FULLDAY_CODE)
                        unexcused_halfday_code_id = get_attendance_code_id(cur, school, UNEXCUSED_ABSENCE_HALFDAY_CODE)
                        excused_fullday_code_id = get_attendance_code_id(cur, school, EXCUSED_ABSENCE_FULLDAY_CODE)
                        excused_halfday_code_id = get_attendance_code_id(cur, school, EXCUSED_ABSENCE_HALFDAY_CODE)
                        elearning_fullday_code_id = get_attendance_code_id(cur, school, ELEARNING_FULLDAY_PRESENT_CODE)

                        # get the current year ID for this school so we can use it to insert the daily absence later via API
                        year_id = get_year_id(cur, school)

                        # get the calendar day ID for today to use when inserting daily attendance
                        calendar_day = get_calendar_day_id(cur, school)

                        # process e-learning attendance for this school first, since those codes should go in first on e-learning days
                        process_elearning(ELEARNING_PERIOD_CODES, elearning_fullday_code_id, excused_halfday_code_id, calendar_day, year_id, school)

                        # process special codes that should be in every period, so if there is even one, mark the day code as the same code
                        process_special_day_codes(SPECIAL_ONLY_DAY_CODES, calendar_day, year_id, school)

                        # process unexcused absences for this school
                        process_absences("unexcused", UNEXCUSED_PERIOD_CODES, unexcused_fullday_code_id, unexcused_halfday_code_id, calendar_day, year_id, school)

                        # process excused absences for this school
                        process_absences("excused", EXCUSED_PERIOD_CODES, excused_fullday_code_id, excused_halfday_code_id, calendar_day, year_id, school)


            except Exception as er:
                print(f'ERROR while connecting to database: {er}')
                print(f'ERROR while connecting to database: {er}', file=log)
                exit(1)

        endTime = datetime.datetime.now()
        endTime = endTime.strftime('%H:%M:%S')
        print(f'Execution ended at {endTime}')
        print(f'Execution ended at {endTime}', file=log)
