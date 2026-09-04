"""Convert meeting attendance codes to daily attendance codes when thresholds are exceeded, reprocessing the last several days each run.

https://github.com/Philip-Greyson/D118-PS-Attendance-Dailies

Runs daily to check the last NUM_DAYS_BACK+1 days (today plus that many days back) of meeting attendance and create/update daily attendance
records if thresholds are met. Existing daily codes are overridden if the underlying meeting attendance has since changed (e.g. a parent
called in the next day to excuse an absence), and a final pass each day corrects students who no longer meet any threshold back to present.

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
DB_CS = os.environ.get('POWERSCHOOL_PROD_DB')
API_URL = os.environ.get('POWERSCHOOL_PROD_URL')

# Configuration
SCHOOL_IDS = [5]  # List of school IDs to process
MT_HALFDAY_THRESHOLD = 3  # Number of codes in a single day on Mon-Thurs before it counts as a half-day absence
F_HALFDAY_THRESHOLD = 2  # Number of codes in a single day on Friday before it counts as a half-day absence
MT_FULLDAY_THRESHOLD = 7  # Number of codes in a single day on Mon-Thurs before it counts as a full-day absence
F_FULLDAY_THRESHOLD = 6  # Number of codes in a single day on Friday before it counts as a full-day absence
TOTAL_PERIODS = 8  # Total number of periods in a day, used to determine if a student has other codes besides the special codes that should be in every period
NUM_DAYS_BACK = 7  # How many days prior to today to also reprocess on every run, in addition to today itself (e.g. 7 means today plus the 7 days before it = 8 total days processed)
SCRIPT_RUN_DATE = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)  # The real-world date this script is actually executed, used to anchor the day-lookback loop below and to timestamp any changes in updates
TODAY = SCRIPT_RUN_DATE  # The date currently being processed. This gets reassigned every pass through the day-lookback loop in __main__ below, so treat it as a moving pointer rather than a true constant, even though the rest of the functions in this file read it as a plain global

# define lists of meeting codes by type
UNEXCUSED_PERIOD_CODES = ['UP', 'UA', 'UH', 'SA']  # The meeting attendance codes to count as unexcused
EXCUSED_PERIOD_CODES = ['EP', 'AB', 'HA', 'CV']  # the meeting attendance codes to count as excused
SUSPENDED_PERIOD_CODES = ['OSS', 'OSSH']  # meeting attendance codes to count as suspensions
SPECIAL_ONLY_DAY_CODES = ['MH', 'HBT', 'HOS', 'DC', 'PRM', 'TR', 'TH', 'ME']  # codes that if there are even one of, it will mark the day with the same code. These are typically special attendance codes that override any other attendance for the day.
ELEARNING_PERIOD_CODES = ['PEL']  # weird ones where get the PEL code if they are present all day but an excused half day if they have less than the full day threshold

# define the daily attendance codes to apply for each type of absence or special case
ELEARNING_FULLDAY_PRESENT_CODE = 'PEL'  # The daily attendance code to apply for the daily attendance for a full day e-learning attendance
UNEXCUSED_ABSENCE_HALFDAY_CODE = 'UH'  # The half-day attendance code to apply for the daily attendance for an unexcused half day
UNEXCUSED_ABSENCE_FULLDAY_CODE = 'UA'  # The daily attendance code to apply for the daily attendance for an unexcused day
EXCUSED_ABSENCE_HALFDAY_CODE = 'HA'  # The half-day attendance code to apply for the daily attendance for an excused half day
EXCUSED_ABSENCE_FULLDAY_CODE = 'AB'  # The daily attendance code to apply for the daily attendance for an excused day
SUSPENDED_ABSENCE_HALFDAY_CODE = 'OSSH'  # the attendance code to apply for a half day suspension
SUSPENDED_ABSENCE_FULLDAY_CODE = 'OSS'  # the attendance code to apply for a full day suspension
ADMIN_PRESENT_OVERRIDE_CODE = 'PRM'  # the code to override any existing code with if a student no longer meets any threshold for any of the above codes and needs to be corrected back to present

ADMIN_OVERRIDE_CHECK_CODES = [UNEXCUSED_ABSENCE_FULLDAY_CODE, UNEXCUSED_ABSENCE_HALFDAY_CODE, EXCUSED_ABSENCE_FULLDAY_CODE, EXCUSED_ABSENCE_HALFDAY_CODE, SUSPENDED_ABSENCE_FULLDAY_CODE, SUSPENDED_ABSENCE_HALFDAY_CODE, *SPECIAL_ONLY_DAY_CODES]  # every daily code the end-of-day admin override pass should look for when deciding if a student needs correcting back to present. E-learning/PEL is intentionally excluded from this list

OVERRIDE_EXISTING_DAYCODE = True  # Whether to override existing daily attendance codes for the day. True by default now that this script reprocesses recent days and needs to correct codes whose underlying meeting attendance changed

DRY_RUN = True  # If True, will not make any changes, just log what would be done

print(f'DBUG: DB Username: {DB_UN} | DB Password: {DB_PW} | DB Server: {DB_CS}')
print(f'DBUG: Dry Run is set to {DRY_RUN}')

def create_daily_attendance(ps: any, school_id: int, calendar_day: int, student_id: int, year_id: int, attendance_code_id: int, comment: str, log: any) -> None:
    """Create or update a daily attendance record via PowerSchool API."""
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

def get_attendance_code_id(cur: any, school_id: int, code: str) -> int | None:
    """Get the attendance code ID for a given attendance code and school for the current TODAY date, or None if it cannot be found (e.g. misconfiguration or a date outside any term)."""
    cur.execute('SELECT ac.id FROM attendance_code ac LEFT JOIN terms t ON ac.yearid = t.yearid \
                WHERE ac.att_code = :code AND ac.schoolid = :school AND t.isyearrec = 1 AND t.schoolid = :school \
                AND :today BETWEEN t.firstday AND t.lastday', code=code, school=school_id, today=TODAY)
    result = cur.fetchone()
    if result is not None:
        print(f'DBUG: Found attendance code ID: {result[0]} for code {code} at building {school_id}')
        print(f'DBUG: Found attendance code ID: {result[0]} for code {code} at building {school_id}', file=log)
        return result[0]
    else:
        print(f'ERROR: Could not find {code} attendance code at building {school_id} for {TODAY}')
        print(f'ERROR: Could not find {code} attendance code at building {school_id} for {TODAY}', file=log)
        return None

def get_year_id(cur: any, school_id: int) -> int | None:
    """Get the current year ID for a given school for the current TODAY date, or None if TODAY doesn't fall within any defined year (e.g. summer break)."""
    cur.execute('SELECT yearid FROM terms WHERE isyearrec = 1 AND schoolid = :school AND :today BETWEEN firstday AND lastday', school=school_id, today=TODAY)
    result = cur.fetchone()
    if result is not None:
        print(f'DBUG: Found current year ID: {result[0]} for building {school_id} for date {TODAY}')
        print(f'DBUG: Found current year ID: {result[0]} for building {school_id} for date {TODAY}', file=log)
        return result[0]
    else:
        print(f'ERROR: Could not find current year ID at building {school_id} for date {TODAY}, it may be summer break or the year has not been set up yet.')
        print(f'ERROR: Could not find current year ID at building {school_id} for date {TODAY}, it may be summer break or the year has not been set up yet.', file=log)
        return None

def get_calendar_day_id(cur: any, school_id: int) -> int | None:
    """Get the calendar day ID for a given school and the current TODAY date, or None if no calendar day exists for that date (e.g. a weekend or holiday, which is common now that this script reprocesses recent days)."""
    cur.execute('SELECT id FROM calendar_day WHERE schoolid = :school AND date_value = :today', school=school_id, today=TODAY)
    result = cur.fetchone()
    if result is not None:
        print(f'DBUG: Found calendar day ID: {result[0]} for building {school_id} for date {TODAY}')
        print(f'DBUG: Found calendar day ID: {result[0]} for building {school_id} for date {TODAY}', file=log)
        return result[0]
    else:
        print(f'ERROR: Could not find calendar day ID at building {school_id} for date {TODAY}')
        print(f'ERROR: Could not find calendar day ID at building {school_id} for date {TODAY}', file=log)
        return None

def process_elearning(codes: list, elearning_fullday_code_id: int, calendar_day: int, year_id: int, school: int) -> None:
    """Process the special e-learning attendance code for students who have the PEL code.

    Operates kinda in reverse of absences, they need 6-7 PEL codes to get the full day.
    However for 2/3-6/7 PELs, due to technically being .5 PEL and .5 UA, we still put in a full PEL and just make a note in the comment.
    If they have less than 3 PEL codes, they get nothing. This is because the PEL code is a present code, not an absence code, and their absence will get caught by the other functions.
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

                if present_count >= fullday_threshold:
                    if existing_daily and existing_daily[0] == ELEARNING_FULLDAY_PRESENT_CODE:  # already correctly coded, dont waste an API call re-writing the same value
                        print(f'DBUG: Student {stu_name} with student number {stu_num} already has the correct e-learning code of {ELEARNING_FULLDAY_PRESENT_CODE}, skipping update')
                        print(f'DBUG: Student {stu_name} with student number {stu_num} already has the correct e-learning code of {ELEARNING_FULLDAY_PRESENT_CODE}, skipping update', file=log)
                    elif existing_daily and existing_daily[0] is not None and not OVERRIDE_EXISTING_DAYCODE:
                        print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of daily attendance code of {ELEARNING_FULLDAY_PRESENT_CODE} due to configuration of OVERRIDE_EXISTING_DAYCODE being {OVERRIDE_EXISTING_DAYCODE}.')
                        print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of daily attendance code of {ELEARNING_FULLDAY_PRESENT_CODE} due to configuration of OVERRIDE_EXISTING_DAYCODE being {OVERRIDE_EXISTING_DAYCODE}.', file=log)
                    else:
                        if existing_daily and existing_daily[0] is not None:  # note what the code is changing from and when the correction was made
                            comment_string = f"E-Learning full-day present code auto-generated from {present_count} meeting {meet_code} codes which met the threshold of {fullday_threshold} for a full-day e-learning attendance, changed from previous code {existing_daily[0]} by an admin override run on {SCRIPT_RUN_DATE.strftime('%Y-%m-%d')}"
                        else:
                            comment_string = f"E-Learning full-day present code auto-generated from {present_count} meeting {meet_code} codes which met the threshold of {fullday_threshold} for a full-day e-learning attendance"
                        if not DRY_RUN:
                            create_daily_attendance(ps, school, calendar_day, stu_id, year_id, elearning_fullday_code_id, comment_string, log)  # create/update the daily attendance record via API for a full day e-learning attendance
                        else:
                            print(f'WARN: Dry run enabled, would have created/updated full-day e-learning attendance for student {stu_name} with student number {stu_num}. Comment string: {comment_string}')
                            print(f'WARN: Dry run enabled, would have created/updated full-day e-learning attendance for student {stu_name} with student number {stu_num}. Comment string: {comment_string}', file=log)
                elif halfday_threshold <= present_count < fullday_threshold:
                    if existing_daily and existing_daily[0] == ELEARNING_FULLDAY_PRESENT_CODE:
                        print(f'DBUG: Student {stu_name} with student number {stu_num} already has the correct e-learning code of {ELEARNING_FULLDAY_PRESENT_CODE}, skipping update')
                        print(f'DBUG: Student {stu_name} with student number {stu_num} already has the correct e-learning code of {ELEARNING_FULLDAY_PRESENT_CODE}, skipping update', file=log)
                    elif existing_daily and existing_daily[0] is not None and not OVERRIDE_EXISTING_DAYCODE:
                        print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of daily attendance code of {ELEARNING_FULLDAY_PRESENT_CODE} due to configuration of OVERRIDE_EXISTING_DAYCODE being {OVERRIDE_EXISTING_DAYCODE}.')
                        print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of daily attendance code of {ELEARNING_FULLDAY_PRESENT_CODE} due to configuration of OVERRIDE_EXISTING_DAYCODE being {OVERRIDE_EXISTING_DAYCODE}.', file=log)
                    else:
                        if existing_daily and existing_daily[0] is not None:
                            comment_string = f"E-Learning half-day code auto-generated from {present_count} meeting {meet_code} codes which met the threshold of {halfday_threshold} for a half-day e-learning attendance, changed from previous code {existing_daily[0]} by an admin override run on {SCRIPT_RUN_DATE.strftime('%Y-%m-%d')}"
                        else:
                            comment_string = f"E-Learning half-day code auto-generated from {present_count} meeting {meet_code} codes which met the threshold of {halfday_threshold} for a half-day e-learning attendance"
                        if not DRY_RUN:
                            create_daily_attendance(ps, school, calendar_day, stu_id, year_id, elearning_fullday_code_id, comment_string, log)  # create/update the daily attendance record via API for a half day e-learning attendance
                        else:
                            print(f'WARN: Dry run enabled, would have created/updated half-day e-learning attendance for student {stu_name} with student number {stu_num}. Comment string {comment_string}')
                            print(f'WARN: Dry run enabled, would have created/updated half-day e-learning attendance for student {stu_name} with student number {stu_num}. Comment string {comment_string}', file=log)
        except Exception as er:
            print(f'ERROR while querying or processing meeting attendance for code {meet_code}: {er}')
            print(f'ERROR while querying or processing meeting attendance for code {meet_code}: {er}', file=log)

def process_special_day_codes(codes: list, calendar_day: int, year_id: int, school: int) -> set[int]:
    """Process the special codes that should be in every period, so if there is even one, mark the day code as the same code. Returns the set of student IDs that had at least one occurrence of a special code today, so the caller can union it with the sets returned by process_absences() for the admin override correction pass.

    We want to log any other codes that are in the meeting attendance day, since there SHOULD not be anything else.
    """
    student_other_codes = {}  # Dictionary to hold student IDs and their other codes so we can log them if they have any other codes besides the special code
    threshold_students = set()  # Set of studentids who had at least one occurrence of any special code today - a single occurrence is this code's "threshold"
    for special_code in codes:
        print(f'INFO: Processing special attendance code {special_code} at building {school} for {TODAY}')
        print(f'INFO: Processing special attendance code {special_code} at building {school} for {TODAY}', file=log)

        # look up the attendance code ID once per special code (not per student, since its the same ID for every student who matches it)
        special_code_id = get_attendance_code_id(cur, school, special_code)
        if special_code_id is None:  # if this code cant be resolved for this school/date, skip it entirely rather than fail every student that has it
            print(f'ERROR: Could not resolve attendance code ID for special code {special_code} at building {school}, skipping this code for {TODAY}')
            print(f'ERROR: Could not resolve attendance code ID for special code {special_code} at building {school}, skipping this code for {TODAY}', file=log)
            continue

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
                threshold_students.add(stu_id)  # any occurrence at all meets this code's threshold of 1
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

                if existing_daily and existing_daily[0] == special_code:  # already correctly coded, dont waste an API call re-writing the same value
                    print(f'DBUG: Student {stu_name} with student number {stu_num} already has the correct daily code of {special_code} for today, skipping update')
                    print(f'DBUG: Student {stu_name} with student number {stu_num} already has the correct daily code of {special_code} for today, skipping update', file=log)
                elif existing_daily and existing_daily[0] is not None and not OVERRIDE_EXISTING_DAYCODE:  # a different code exists but we're configured not to override it, warn and skip
                    print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of daily attendance code of {special_code} due to configuration of OVERRIDE_EXISTING_DAYCODE being {OVERRIDE_EXISTING_DAYCODE}.')
                    print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of daily attendance code of {special_code} due to configuration of OVERRIDE_EXISTING_DAYCODE being {OVERRIDE_EXISTING_DAYCODE}.', file=log)
                else:  # either no existing code, or a different one we're allowed to override
                    if existing_daily and existing_daily[0] is not None:  # note what the code is changing from and when the correction was made
                        comment_string = f"Auto-generated from presence of meeting code {special_code} which overrides any other attendance meeting codes for the day, changed from previous code {existing_daily[0]} by an admin override run on {SCRIPT_RUN_DATE.strftime('%Y-%m-%d')}"
                    else:
                        comment_string = f"Auto-generated from presence of meeting code {special_code} which overrides any other attendance meeting codes for the day"
                    if not DRY_RUN:
                        create_daily_attendance(ps, school, calendar_day, stu_id, year_id, special_code_id, comment_string, log)
                    else:
                        print(f'WARN: Dry run enabled, would have created/updated day code {special_code} for student {stu_name} with student number {stu_num}. Comment string: {comment_string}')
                        print(f'WARN: Dry run enabled, would have created/updated day code {special_code} for student {stu_name} with student number {stu_num}. Comment string: {comment_string}', file=log)
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
    return threshold_students

def process_absences(abs_type: str, codes: list, fullday_code_id: int, halfday_code_id: int, fullday_code: str, halfday_code: str, calendar_day: int, year_id: int, school: int) -> set[int]:
    """Process absences for each school, create/update daily attendance records if thresholds are met, and return the set of student IDs that met a threshold today so the caller can build the combined admin override check set."""
    student_absences = {}  # Dictionary to hold student IDs and their absence counts so we can total between different codes
    student_info = {}  # Dictionary to hold student info (student number, name, studentid) so we can use it later when creating the daily attendance record via API
    threshold_students = set()  # studentids that met either the half-day or full-day threshold today, returned for the admin override correction pass

    print(f'INFO: Processing {abs_type} absences for building {school} for {TODAY}')
    print(f'INFO: Processing {abs_type} absences for building {school} for {TODAY}', file=log)
    # do a loop of all the period codes we want to check for today and process them one at a time
    for abs_code in codes:
        print(f'INFO: Processing attendance for {abs_type} period code {abs_code} at building {school} for {TODAY}')
        print(f'INFO: Processing attendance for {abs_type} period code {abs_code} at building {school} for {TODAY}', file=log)

        # get the meeting attendance from today using the pssis_attendance_meeting view, filtering to just entries that have our period code
        # use count and group by to get the number of codes per student for today so we dont have to count them in python
        try:
            cur.execute('SELECT name, student_number, studentid, count(*) as count FROM pssis_attendance_meeting \
                        WHERE att_code = :code AND schoolid = :school AND att_date = :today \
                        GROUP BY student_number, name, student_number, studentid', code=abs_code, school=school, today=TODAY)
            absences = cur.fetchall()
            for absence in absences:
                stu_name = absence[0]
                stu_num = str(int(absence[1]))
                stu_id = absence[2]
                absence_count = absence[3]
                student_absences[stu_num] = student_absences.get(stu_num, 0) + absence_count  # add the count of this code to the total for this student
                student_info[stu_num] = {'name': stu_name, 'id': stu_id}  # store student info for later use
                print(f'DBUG: Student {stu_name} with student number {stu_num} has {absence_count} {abs_code} absences today')
                print(f'DBUG: Student {stu_name} with student number {stu_num} has {absence_count} {abs_code} absences today', file=log)
        except Exception as er:
            print(f'ERROR while querying or processing meeting attendance for code {abs_code}: {er}')
            print(f'ERROR while querying or processing meeting attendance for code {abs_code}: {er}', file=log)

    # now go through each student that we had absences for and process the daily code
    for stu_num, absence_count in student_absences.items():
        stu_name = student_info[stu_num]['name']
        stu_id = student_info[stu_num]['id']
        print(f'DBUG: Student {stu_name} with student number {stu_num} has a total of {absence_count} {abs_type} period absences today')
        print(f'DBUG: Student {stu_name} with student number {stu_num} has a total of {absence_count} {abs_type} period absences today', file=log)
        # check to see if there is already a daily attendance record for this student for today
        cur.execute('SELECT att_code FROM pssis_attendance_daily WHERE studentid = :stuID AND schoolid = :school AND att_date = :today', stuID=stu_id, school=school, today=TODAY)
        existing_daily = cur.fetchone()

        if halfday_threshold <= absence_count < fullday_threshold:
            threshold_students.add(stu_id)  # met the half-day threshold, track for the admin override pass
            print(f'INFO: Student {stu_name} with student number {stu_num} meets half day {abs_type} threshold with {absence_count} {abs_type} period absences today')
            print(f'INFO: Student {stu_name} with student number {stu_num} meets half day {abs_type} threshold with {absence_count} {abs_type} period absences today', file=log)
            if existing_daily and existing_daily[0] == halfday_code:  # already correctly coded, dont waste an API call re-writing the same value
                print(f'DBUG: Student {stu_name} with student number {stu_num} already has the correct half-day {abs_type} code of {halfday_code}, skipping update')
                print(f'DBUG: Student {stu_name} with student number {stu_num} already has the correct half-day {abs_type} code of {halfday_code}, skipping update', file=log)
            elif existing_daily and existing_daily[0] is not None and not OVERRIDE_EXISTING_DAYCODE:  # a different code exists but we're configured not to override it, warn and skip
                print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of half-day {abs_type} absence due to configuration of OVERRIDE_EXISTING_DAYCODE being {OVERRIDE_EXISTING_DAYCODE}.')
                print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of half-day {abs_type} absence due to configuration of OVERRIDE_EXISTING_DAYCODE being {OVERRIDE_EXISTING_DAYCODE}.', file=log)
            else:  # either no existing code, or a different one we're allowed to override
                if existing_daily and existing_daily[0] is not None:  # note what the code is changing from and when the correction was made
                    comment_string = f"Auto-generated from {absence_count} meeting {abs_type} codes which met the threshold of {halfday_threshold} for a half-day {abs_type} absence, changed from previous code {existing_daily[0]} by an admin override run on {SCRIPT_RUN_DATE.strftime('%Y-%m-%d')}"
                else:
                    comment_string = f"Auto-generated from {absence_count} meeting {abs_type} codes which met the threshold of {halfday_threshold} for a half-day {abs_type} absence"
                if not DRY_RUN:
                    create_daily_attendance(ps, school, calendar_day, stu_id, year_id, halfday_code_id, comment_string, log)  # create/update the daily attendance record via API for a half day absence
                else:
                    print(f'WARN: Dry run enabled, would have created/updated half-day {abs_type} attendance for student {stu_name} with student number {stu_num}. Comment string: {comment_string}')
                    print(f'WARN: Dry run enabled, would have created/updated half-day {abs_type} attendance for student {stu_name} with student number {stu_num}. Comment string: {comment_string}', file=log)

        elif absence_count >= fullday_threshold:
            threshold_students.add(stu_id)  # met the full-day threshold, track for the admin override pass
            print(f'INFO: Student {stu_name} with student number {stu_num} meets full day {abs_type} threshold with {absence_count} {abs_type} period absences today')
            print(f'INFO: Student {stu_name} with student number {stu_num} meets full day {abs_type} threshold with {absence_count} {abs_type} period absences today', file=log)
            if existing_daily and existing_daily[0] == fullday_code:  # already correctly coded, dont waste an API call re-writing the same value
                print(f'DBUG: Student {stu_name} with student number {stu_num} already has the correct full-day {abs_type} code of {fullday_code}, skipping update')
                print(f'DBUG: Student {stu_name} with student number {stu_num} already has the correct full-day {abs_type} code of {fullday_code}, skipping update', file=log)
            elif existing_daily and existing_daily[0] is not None and not OVERRIDE_EXISTING_DAYCODE:  # a different code exists but we're configured not to override it, warn and skip
                print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of full-day {abs_type} absence due to configuration of OVERRIDE_EXISTING_DAYCODE being {OVERRIDE_EXISTING_DAYCODE}.')
                print(f'WARN: Student {stu_name} with student number {stu_num} already has a daily attendance record for today with code {existing_daily[0]}. Skipping creation of full-day {abs_type} absence due to configuration of OVERRIDE_EXISTING_DAYCODE being {OVERRIDE_EXISTING_DAYCODE}.', file=log)
            else:  # either no existing code, or a different one we're allowed to override
                if existing_daily and existing_daily[0] is not None:  # note what the code is changing from and when the correction was made
                    comment_string = f"Auto-generated from {absence_count} meeting {abs_type} codes which met the threshold of {fullday_threshold} for a full-day {abs_type} absence, changed from previous code {existing_daily[0]} by an admin override run on {SCRIPT_RUN_DATE.strftime('%Y-%m-%d')}"
                else:
                    comment_string = f"Auto-generated from {absence_count} meeting {abs_type} codes which met the threshold of {fullday_threshold} for a full-day {abs_type} absence"
                if not DRY_RUN:
                    create_daily_attendance(ps, school, calendar_day, stu_id, year_id, fullday_code_id, comment_string, log)  # create/update the daily attendance record via API for a full day absence
                else:
                    print(f'WARN: Dry run enabled, would have created/updated full-day {abs_type} attendance for student {stu_name} with student number {stu_num}. Comment string: {comment_string}')
                    print(f'WARN: Dry run enabled, would have created/updated full-day {abs_type} attendance for student {stu_name} with student number {stu_num}. Comment string: {comment_string}', file=log)

    return threshold_students

def process_present_overrides(threshold_students: set[int], override_code_id: int, calendar_day: int, year_id: int, school: int) -> None:
    """Correct students holding a managed daily code who no longer meet any threshold today, applying ADMIN_PRESENT_OVERRIDE_CODE instead."""
    print(f'INFO: Processing admin override corrections for building {school} for {TODAY}')
    print(f'INFO: Processing admin override corrections for building {school} for {TODAY}', file=log)
    try:
        # Oracle IN clauses need individually named bind variables rather than accepting a python list directly, so build one placeholder per code we care about
        code_placeholders = ', '.join(f':code{i}' for i in range(len(ADMIN_OVERRIDE_CHECK_CODES)))
        bind_vars = {f'code{i}': code for i, code in enumerate(ADMIN_OVERRIDE_CHECK_CODES)}  # map each placeholder name to its actual code value for the query below
        # print(f'DBUG: code placeholders for present override check: {code_placeholders}')
        # print(f'DBUG: code placeholders for present override check: {code_placeholders}', file=log)
        # print(f'DBUG: bind vars for present override check: {bind_vars}')
        # print(f'DBUG: bind vars for present override check: {bind_vars}', file=log)
        cur.execute(f'SELECT name, student_number, studentid, att_code FROM pssis_attendance_daily \
                    WHERE schoolid = :school AND att_date = :today AND att_code IN ({code_placeholders})', school=school, today=TODAY, **bind_vars)
        existing_coded_students = cur.fetchall()

        for row in existing_coded_students:
            stu_name = row[0]
            stu_num = str(int(row[1]))
            stu_id = row[2]
            existing_code = row[3]

            if stu_id not in threshold_students:  # this student has one of the managed codes but no longer meets any threshold that would justify it, needs correcting back to present
                print(f'INFO: Student {stu_name} with student number {stu_num} has code {existing_code} but no longer meets any threshold, correcting to {ADMIN_PRESENT_OVERRIDE_CODE}')
                print(f'INFO: Student {stu_name} with student number {stu_num} has code {existing_code} but no longer meets any threshold, correcting to {ADMIN_PRESENT_OVERRIDE_CODE}', file=log)
                comment_string = f"Auto-corrected by admin override pass on {SCRIPT_RUN_DATE.strftime('%Y-%m-%d')}, previous code of {existing_code} no longer meets any absence threshold for {TODAY.strftime('%Y-%m-%d')}"
                if not DRY_RUN:
                    create_daily_attendance(ps, school, calendar_day, stu_id, year_id, override_code_id, comment_string, log)
                else:
                    print(f'WARN: Dry run enabled, would have corrected student {stu_name} with student number {stu_num} from {existing_code} to {ADMIN_PRESENT_OVERRIDE_CODE}. Comment string: {comment_string}')
                    print(f'WARN: Dry run enabled, would have corrected student {stu_name} with student number {stu_num} from {existing_code} to {ADMIN_PRESENT_OVERRIDE_CODE}. Comment string: {comment_string}', file=log)
    except Exception as er:
        print(f'ERROR while processing admin overrides for building {school} for {TODAY}: {er}')
        print(f'ERROR while processing admin overrides for building {school} for {TODAY}: {er}', file=log)

if __name__ == '__main__':
    with open('MeetingAttConversionLog.txt', 'w') as log:
        startTime = datetime.datetime.now()
        startTime = startTime.strftime('%H:%M:%S')
        print(f'Execution started at {startTime}')
        print(f'Execution started at {startTime}', file=log)
        print(f'DBUG: Will process {NUM_DAYS_BACK + 1} day(s) total, from {SCRIPT_RUN_DATE.strftime("%Y-%m-%d")} back through {(SCRIPT_RUN_DATE - datetime.timedelta(days=NUM_DAYS_BACK)).strftime("%Y-%m-%d")}')
        print(f'DBUG: Will process {NUM_DAYS_BACK + 1} day(s) total, from {SCRIPT_RUN_DATE.strftime("%Y-%m-%d")} back through {(SCRIPT_RUN_DATE - datetime.timedelta(days=NUM_DAYS_BACK)).strftime("%Y-%m-%d")}', file=log)

        try:
            # open a single database connection and PowerSchool API session for the entire run, reused across every day and every school processed below
            with oracledb.connect(user=DB_UN, password=DB_PW, dsn=DB_CS) as con:
                with con.cursor() as cur:
                    print('INFO: Database connection established')
                    print('INFO: Database connection established', file=log)
                    ps = acme_powerschool.api(API_URL, client_id=D118_API_ID, client_secret=D118_API_SECRET)  # start the single PowerSchool API session for the whole run

                    # loop backwards from today through NUM_DAYS_BACK prior days, reprocessing each one so corrections made to meeting attendance after the fact get picked up
                    for days_back in range(NUM_DAYS_BACK + 1):
                        TODAY = SCRIPT_RUN_DATE - datetime.timedelta(days=days_back)  # move the processing date backwards one day at a time from today
                        print(f'INFO: Now processing attendance date {TODAY}')
                        print(f'INFO: Now processing attendance date {TODAY}', file=log)

                        # determine which thresholds to use based on the day of the week of the date being processed (Friday has different thresholds than Mon-Thurs)
                        if TODAY.weekday() == 4:  # if the date being processed is a Friday
                            halfday_threshold = F_HALFDAY_THRESHOLD
                            fullday_threshold = F_FULLDAY_THRESHOLD
                            print(f'DBUG: {TODAY} is a Friday, using Friday thresholds of {halfday_threshold} for half-day and {fullday_threshold} for full-day')
                            print(f'DBUG: {TODAY} is a Friday, using Friday thresholds of {halfday_threshold} for half-day and {fullday_threshold} for full-day', file=log)
                        elif TODAY.weekday() == 5 or TODAY.weekday() == 6:  # if the date being processed is a Saturday or Sunday
                            print(f'INFO: {TODAY} is a weekend day, skipping processing of the day')
                            print(f'INFO: {TODAY} is a weekend day, skipping processing of the day', file=log)
                            continue  # skip weekends entirely since there is no meeting attendance on those days
                        else:
                            halfday_threshold = MT_HALFDAY_THRESHOLD
                            fullday_threshold = MT_FULLDAY_THRESHOLD
                            print(f'DBUG: {TODAY} is Mon-Thurs, using Mon-Thurs thresholds of {halfday_threshold} for half-day and {fullday_threshold} for full-day')
                            print(f'DBUG: {TODAY} is Mon-Thurs, using Mon-Thurs thresholds of {halfday_threshold} for half-day and {fullday_threshold} for full-day', file=log)

                        for school in SCHOOL_IDS:
                            print(f'INFO: Processing attendance at building {school} for {TODAY}')
                            print(f'INFO: Processing attendance at building {school} for {TODAY}', file=log)
                            try:
                                # the calendar day may not exist for non-attendance days like holiday/summer breaks, which can fall within the lookback window - skip this building/date rather than treating it as fatal
                                calendar_day = get_calendar_day_id(cur, school)
                                if calendar_day is None:
                                    print(f'ERROR: No calendar day found for building {school} on {TODAY}, likely a non-attendance day, skipping')
                                    print(f'ERROR: No calendar day found for building {school} on {TODAY}, likely a non-attendance day, skipping', file=log)
                                    continue

                                year_id = get_year_id(cur, school)
                                if year_id is None:
                                    print(f'ERROR: No active school year found for building {school} on {TODAY}, skipping')
                                    print(f'ERROR: No active school year found for building {school} on {TODAY}, skipping', file=log)
                                    continue

                                # resolve every attendance code ID we need for today, freshly each time, since the applicable term/year can differ by date
                                unexcused_fullday_code_id = get_attendance_code_id(cur, school, UNEXCUSED_ABSENCE_FULLDAY_CODE)
                                unexcused_halfday_code_id = get_attendance_code_id(cur, school, UNEXCUSED_ABSENCE_HALFDAY_CODE)
                                excused_fullday_code_id = get_attendance_code_id(cur, school, EXCUSED_ABSENCE_FULLDAY_CODE)
                                excused_halfday_code_id = get_attendance_code_id(cur, school, EXCUSED_ABSENCE_HALFDAY_CODE)
                                elearning_fullday_code_id = get_attendance_code_id(cur, school, ELEARNING_FULLDAY_PRESENT_CODE)
                                suspension_fullday_code_id = get_attendance_code_id(cur, school, SUSPENDED_ABSENCE_FULLDAY_CODE)
                                suspension_halfday_code_id = get_attendance_code_id(cur, school, SUSPENDED_ABSENCE_HALFDAY_CODE)
                                admin_override_code_id = get_attendance_code_id(cur, school, ADMIN_PRESENT_OVERRIDE_CODE)

                                # check to make sure all the codes we need for this school/date were resolved, if any are None then skip this building/date rather than risk writing bad data
                                resolved_code_ids = [unexcused_fullday_code_id, unexcused_halfday_code_id, excused_fullday_code_id, excused_halfday_code_id, elearning_fullday_code_id, suspension_fullday_code_id, suspension_halfday_code_id, admin_override_code_id]
                                if None in resolved_code_ids:  # if any code couldnt be resolved for this school/date, skip this building/date rather than risk writing bad data
                                    print(f'ERROR: Could not resolve one or more attendance codes for building {school} on {TODAY}, skipping this building/date')
                                    print(f'ERROR: Could not resolve one or more attendance codes for building {school} on {TODAY}, skipping this building/date', file=log)
                                    continue

                                # process in reverse-priority order so that with OVERRIDE_EXISTING_DAYCODE enabled, later categories correctly overwrite earlier ones:
                                # excused first (lowest priority), then unexcused, then suspension, then special day codes, then e-learning last (highest priority, since presence should win)
                                threshold_students = set()  # running set of studentids who met some threshold today at this building, used by the admin override correction pass below
                                # do the excused absences first, take the output of the students who met the thresholds and union them to the threshold_students set
                                threshold_students |= process_absences('excused', EXCUSED_PERIOD_CODES, excused_fullday_code_id, excused_halfday_code_id, EXCUSED_ABSENCE_FULLDAY_CODE, EXCUSED_ABSENCE_HALFDAY_CODE, calendar_day, year_id, school)

                                # do the unexcused absences next, take the output of the students who met the thresholds and union them to the threshold_students set
                                threshold_students |= process_absences('unexcused', UNEXCUSED_PERIOD_CODES, unexcused_fullday_code_id, unexcused_halfday_code_id, UNEXCUSED_ABSENCE_FULLDAY_CODE, UNEXCUSED_ABSENCE_HALFDAY_CODE, calendar_day, year_id, school)

                                # do the suspension absences next, take the output of the students who met the thresholds and union them to the threshold_students set
                                threshold_students |= process_absences('suspension', SUSPENDED_PERIOD_CODES, suspension_fullday_code_id, suspension_halfday_code_id, SUSPENDED_ABSENCE_FULLDAY_CODE, SUSPENDED_ABSENCE_HALFDAY_CODE, calendar_day, year_id, school)

                                # do the special day codes next, take the output of the students who met the thresholds and union them to the threshold_students set
                                threshold_students |= process_special_day_codes(SPECIAL_ONLY_DAY_CODES, calendar_day, year_id, school)

                                # do the e-learning presence last, but we do not need to track the students who met the thresholds for this one since it is a presence code and will not be used in the admin override correction pass
                                process_elearning(ELEARNING_PERIOD_CODES, elearning_fullday_code_id, calendar_day, year_id, school)  # runs last since e-learning presence should override any absence code written above

                                # final pass for the day: catch anyone still coded with a managed absence/special code who no longer actually meets any threshold, and correct them back to present
                                if OVERRIDE_EXISTING_DAYCODE:
                                    process_present_overrides(threshold_students, admin_override_code_id, calendar_day, year_id, school)

                            except Exception as er:
                                print(f'ERROR while processing building {school} for {TODAY}: {er}')
                                print(f'ERROR while processing building {school} for {TODAY}: {er}', file=log)
                                continue  # move on to the next school/day rather than aborting the whole multi-day run over one bad building/date

        except Exception as er:
            print(f'ERROR while connecting to database: {er}')
            print(f'ERROR while connecting to database: {er}', file=log)
            exit(1)

        endTime = datetime.datetime.now()
        endTime = endTime.strftime('%H:%M:%S')
        print(f'Execution ended at {endTime}')
        print(f'Execution ended at {endTime}', file=log)
