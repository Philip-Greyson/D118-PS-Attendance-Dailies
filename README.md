
# D118-PS-Meeting-Attendance-Auto-Conversion

Script to automatically convert unexcused period absences into daily absence codes in PowerSchool.

## Overview

This script is designed to run daily (typically in the afternoon after all class attendance has been taken) and automatically create daily absence records for students who have accumulated too many unexcused period/meeting absences for that day.

The script queries PowerSchool for all meeting (period-level) attendance entries for the current day that have a defined unexcused code. It counts how many of these codes each student has accumulated, and if they meet or exceed a threshold, it creates a daily attendance record with either a half-day or full-day absence code. This threshold is set to be different for Fridays versus Monday-Thursday, as many schools have different schedules on Fridays including ours.

The script processes one or more schools (configurable), and for each school it:

1. Connects to the PowerSchool database to retrieve attendance codes and calendar information for that school.

2. Queries the database for students with unexcused period absences for the current day.

3. Counts the number of unexcused period absences per student

4. Checks if a daily attendance record already exists for each student

5. Creates a daily attendance record via the PowerSchool API if thresholds are met and no conflicting record exists

The script includes a dry run mode for testing, extensive logging of all actions, and configurability for different schools and thresholds.

## Requirements

The following environment variables must be set on the machine running the script:

- POWERSCHOOL_API_ID_2

- POWERSCHOOL_API_SECRET_2

- POWERSCHOOL_READ_USER

- POWERSCHOOL_DB_PASSWORD

- POWERSCHOOL_PROD_DB

These are fairly self explanatory, and just relate to the usernames, passwords, and host IP/URLs for PowerSchool, as well as the plugin API credentials. If you wish to directly edit the script and include these credentials, you can.

As this uses the PowerSchool API, you must have a plugin installed that gives you access to the API endpoints. This plugin is where you get the API ID and API secret that are included in the environment variables.
In the plugin.xml file included inside the plugin, the following fields are required to be able to write the attendance entry. There may be a few more, I have hundreds of fields included in my plugin.xml but these are the ones that are directly called by the API post in this script.

- `<field table="ATTENDANCE" field="ATTENDANCE_CODEID" access="FullAccess" />`

- `<field table="ATTENDANCE" field="CALENDAR_DAYID" access="FullAccess" />`

- `<field table="ATTENDANCE" field="SCHOOLID" access="FullAccess" />`

- `<field table="ATTENDANCE" field="YEARID" access="FullAccess" />`

- `<field table="ATTENDANCE" field="STUDENTID" access="FullAccess" />`

- `<field table="ATTENDANCE" field="ATT_MODE_CODE" access="FullAccess" />`

- `<field table="ATTENDANCE" field="ATT_COMMENT" access="FullAccess" />`

- `<field table="ATTENDANCE" field="ATT_DATE" access="FullAccess" />`

- `<field table="ATTENDANCE" field="PROGRAMID" access="FullAccess" />`

In addition, the following Python modules installed (links to installation guides below):

- [Python-oracledb](https://python-oracledb.readthedocs.io/en/latest/user_guide/installation.html)

- [ACME PowerSchool Python Library](https://easyregpro.com/acme.php)

## Customization

This script is somewhat customized for our use case at D118, but it should be able to be adapted fairly easily as long as the general logic is the same.

The constants define a lot of the thresholds and attendance codes, and should be updated for your use:

- `SCHOOL_IDS` - List of school IDs to process. Set this to the school numbers you want to run the script for. Example: `[5, 10, 15]` for multiple schools or `[5]` for a single school.

- `MT_HALFDAY_THRESHOLD` - Number of unexcused period codes on Monday-Thursday before a half-day absence is created. Default is `2`.

- `F_HALFDAY_THRESHOLD` - Number of unexcused period codes on Friday before a half-day absence is created. Default is `1` (since Fridays often have fewer periods).

- `MT_FULLDAY_THRESHOLD` - Number of unexcused period codes on Monday-Thursday before a full-day absence is created. Default is `5`.

- `F_FULLDAY_THRESHOLD` - Number of unexcused period codes on Friday before a full-day absence is created. Default is `5`.

- `UNEXCUSED_PERIOD_CODE` - The attendance code that represents an unexcused period absence. Default is `'UP'`. Change this to match your district's attendance codes.

- `ABSENT_HALFDAY_CODE` - The attendance code to use for half-day absences. Default is `'UH'`. Change this to match your district's attendance codes.

- `ABSENT_FULLDAY_CODE` - The attendance code to use for full-day absences. Default is `'UN'`. Change this to match your district's attendance codes.

- `OVERRIDE_EXISTING_DAYCODE` - Boolean flag that determines whether to override existing daily attendance codes. Default is `False`, meaning if a student already has a daily attendance code for today, the script will not create a new one. Set to `True` if you want the script to override existing codes.

- `DRY_RUN` - Boolean flag for testing. When `True`, the script will log what it would do but won't actually create any attendance records. Set to `False` for production use.

**Day-of-Week Logic**
The script currently has different thresholds for Fridays versus other weekdays because many schools have shorter schedules on Fridays. If your district has a different schedule pattern (e.g., early release on Wednesdays), you can modify the day-of-week check in the main script:

```python
if  TODAY.weekday() ==  2: # Wednesday is index 2 (Monday=0, Tuesday=1, etc.)
```

**Error Handling**

The script will exit with an error if it cannot find the required attendance codes or calendar day ID for a school. You may want to modify this behavior to skip the school and continue processing others, rather than exiting entirely.
