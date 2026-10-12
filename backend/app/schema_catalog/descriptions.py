"""Rule-based table/column descriptions and search hints for Space DBs."""

from __future__ import annotations

import re

_TABLE_HINTS: dict[str, tuple[str, list[str]]] = {
    "Events": (
        "Core event/meeting records with title, location, schedule, and notes",
        ["event", "meeting", "schedule", "location", "agenda parent"],
    ),
    "Event_Agenda": (
        "Agenda items belonging to events/meetings",
        ["agenda", "agenda item", "meeting agenda", "topics"],
    ),
    "Event_Information": (
        "Event dimension metadata (region, vertical, etc.) linked to events",
        ["event information", "dimension", "region", "vertical"],
    ),
    "Event_Attendee": (
        "People attending events",
        ["attendee", "participant", "who attended"],
    ),
    "Event_Attachment": (
        "Files attached to events",
        ["attachment", "event file", "upload"],
    ),
    "Event_Task": (
        "Tasks under an event",
        ["event task", "action item", "follow up"],
    ),
    "Event_Task_Log": (
        "Activity log for event tasks",
        ["task log", "history"],
    ),
    "Project": (
        "Core project master records (code, name, status, site address, dates)",
        ["project", "projects", "site", "site address", "project code", "project name"],
    ),
    "Project_Location": (
        "Locations belonging to a project",
        ["project location", "location", "site location"],
    ),
    "Project_SubLocation": (
        "Sub-locations under a project location",
        ["sublocation", "sub location", "project sublocation"],
    ),
    "Project_LMS_Configuration": (
        "LMS / labour compliance configuration for a project",
        ["lms", "labour", "compliance", "working hours", "contractor"],
    ),
    # Space Common
    "PersonOfTheMonth": (
        "Person of the Month award records",
        [
            "person of the month",
            "potm",
            "employee of the month",
            "award",
            "recognition",
        ],
    ),
    "PersonOfTheMonth_Attachment": (
        "Attachments linked to Person of the Month entries",
        ["person of the month attachment", "potm file", "award attachment"],
    ),
    "PersonOfTheMonth_Nomination": (
        "Nominations for Person of the Month",
        ["nomination", "nominate", "person of the month nomination"],
    ),
    # Space UM (user management)
    "Users": (
        "Core user/employee master records",
        ["user", "users", "employee", "employees", "people", "staff profile"],
    ),
    "User_Contact": (
        "User contact details (email, phone, address)",
        ["user contact", "email", "phone", "contact details"],
    ),
    "User_Auth": (
        "User authentication / login related records",
        ["user auth", "login", "authentication"],
    ),
    "User_Assignment": (
        "User role/project assignments",
        ["user assignment", "assigned to", "assignment", "reporting"],
    ),
    "User_Employment": (
        "Employment history for users",
        ["employment", "job history", "employer"],
    ),
    "User_Education": (
        "Education records for users",
        ["education", "degree", "qualification"],
    ),
    "User_Certification": (
        "Certifications held by users",
        ["certification", "certificate", "licensed"],
    ),
    "User_Achievement": (
        "Achievements and awards for users",
        ["achievement", "award", "recognition"],
    ),
    "User_ProfessionalInformation": (
        "Professional profile information for users",
        ["professional information", "profile", "designation"],
    ),
    "User_Attachment": (
        "Files attached to a user profile",
        ["user attachment", "user file", "profile document"],
    ),
    "User_Favorite": (
        "User favorites / bookmarks",
        ["favorite", "bookmark"],
    ),
    "User_Setting": (
        "Per-user application settings",
        ["user setting", "preferences"],
    ),
    # Space DMS
    "Document": (
        "Document management system master records (title, status, metadata)",
        ["document", "documents", "dms", "file document", "document management"],
    ),
    "Document_File": (
        "Physical/logical files belonging to a DMS document",
        ["document file", "document files", "dms file", "file version"],
    ),
    "Document_MetaData": (
        "Metadata fields attached to DMS documents",
        ["document metadata", "document properties", "tags"],
    ),
    "Document_Author": (
        "Authors linked to DMS documents",
        ["document author", "authors", "authored by"],
    ),
    "Document_Access": (
        "Access control entries for DMS documents",
        ["document access", "permissions", "acl"],
    ),
    "Document_Access_Matrix": (
        "Access matrix defining who can access which documents",
        ["access matrix", "document permissions matrix"],
    ),
    "Document_AccessRequest": (
        "Requests for access to DMS documents",
        ["access request", "request access"],
    ),
    "Document_DownloadHistory": (
        "History of document downloads",
        ["download history", "downloaded", "who downloaded"],
    ),
    "Document_ExternalShare": (
        "External sharing links for documents",
        ["external share", "share link", "shared externally"],
    ),
    "Document_UserShare": (
        "Documents shared with specific users",
        ["user share", "shared with user"],
    ),
    "Document_UserGroupShare": (
        "Documents shared with user groups",
        ["group share", "shared with group"],
    ),
    "Document_Reference": (
        "Cross-references between documents",
        ["document reference", "related document"],
    ),
    "Document_Provisional": (
        "Provisional / draft document records",
        ["provisional document", "draft document"],
    ),
    # Space Attachment (storage)
    "Attachment": (
        "Stored file attachments (blob/file metadata)",
        ["attachment", "attachments", "uploaded file", "file storage", "blob"],
    ),
    "Attachment_Provisional": (
        "Provisional attachment uploads pending finalize",
        ["provisional attachment", "pending upload"],
    ),
    "AttachmentReference": (
        "Links between attachments and owning entities",
        ["attachment reference", "linked attachment", "attachment link"],
    ),
    "AttachmentSyncStatus": (
        "Sync status for attachment storage",
        ["attachment sync", "sync status"],
    ),
    # Space LMS (labour)
    "Labour": (
        "Labour / workforce master records",
        ["labour", "labor", "worker", "workers", "workforce", "lms labour"],
    ),
    "Labour_Attendance": (
        "Daily labour attendance records",
        ["attendance", "labour attendance", "present", "absent", "punch"],
    ),
    "Labour_Attendance_History": (
        "Historical labour attendance records",
        ["attendance history", "past attendance"],
    ),
    "Labour_Attendance_Log": (
        "Attendance punch/event log",
        ["attendance log", "punch log"],
    ),
    "Labour_Wage": (
        "Labour wage configuration / rates",
        ["wage", "wages", "pay rate", "salary"],
    ),
    "Labour_Contact_Information": (
        "Contact details for labourers",
        ["labour contact", "worker phone", "worker email"],
    ),
    "Labour_KYC": (
        "KYC documents/details for labourers",
        ["labour kyc", "kyc", "identity"],
    ),
    "Contractor": (
        "Contractor master records in LMS",
        ["contractor", "contractors", "vendor contractor"],
    ),
    "Contractor_Contact_Information": (
        "Contact details for contractors",
        ["contractor contact", "contractor phone"],
    ),
    "Employment": (
        "Employment / engagement records linking labour to projects",
        ["employment", "engaged labour", "labour assignment"],
    ),
    "Device": (
        "Attendance / biometric devices",
        ["device", "devices", "biometric", "punch device"],
    ),
    "MinimumWage": (
        "Minimum wage master configuration",
        ["minimum wage", "min wage"],
    ),
    "ComplianceConfiguration": (
        "LMS compliance configuration",
        ["compliance", "lms compliance"],
    ),
    # Space HSE
    "Environmental_Review": (
        "Environmental HSE review records",
        ["environmental review", "environment", "hse environment", "ehs"],
    ),
    "Environmental_Review_Activity": (
        "Activities under an environmental review",
        ["environmental activity", "environment checklist"],
    ),
    "Occupational_Review": (
        "Occupational health & safety review records",
        ["occupational review", "occupational safety", "ohs", "hse"],
    ),
    "Occupational_Review_Activity": (
        "Activities under an occupational review",
        ["occupational activity", "safety checklist"],
    ),
    # Space Incident
    "Incident_Information": (
        "Core incident / accident information records",
        ["incident", "incidents", "accident", "near miss", "safety incident"],
    ),
    "Incident_Description": (
        "Narrative descriptions of incidents",
        ["incident description", "what happened"],
    ),
    "Incident_InjuredPerson": (
        "People injured in an incident",
        ["injured person", "injury", "casualty"],
    ),
    "Incident_Investigation": (
        "Incident investigation records",
        ["investigation", "incident investigation", "root cause"],
    ),
    "Incident_Prevention": (
        "Preventive actions after an incident",
        ["prevention", "corrective action", "preventive action"],
    ),
    "Incident_Reason": (
        "Reasons / causes recorded for an incident",
        ["incident reason", "cause", "why happened"],
    ),
    "Incident_Review": (
        "Incident review / approval records",
        ["incident review", "reviewed incident"],
    ),
    "Incident_Cost": (
        "Costs associated with an incident",
        ["incident cost", "loss cost"],
    ),
    "Incident_Attachment": (
        "Files attached to an incident",
        ["incident attachment", "incident photo", "incident file"],
    ),
    "Incident_Spectator": (
        "Witnesses / spectators of an incident",
        ["spectator", "witness", "bystander"],
    ),
    "Suggestion": (
        "Suggestions related to incident/safety improvement",
        ["suggestion", "safety suggestion"],
    ),
    # Space Admin
    "Company": (
        "Company master records",
        ["company", "companies", "organization", "organisation"],
    ),
    "Vendor": (
        "Vendor master records",
        ["vendor", "vendors", "supplier"],
    ),
    "Material": (
        "Material master records",
        ["material", "materials", "item master"],
    ),
    "Holiday": (
        "Holiday calendar records",
        ["holiday", "holidays", "leave calendar"],
    ),
    "Region": (
        "Region master records",
        ["region", "regions", "geography"],
    ),
    "Zone": (
        "Zone master records",
        ["zone", "zones"],
    ),
    "Vertical": (
        "Business vertical master records",
        ["vertical", "verticals", "business unit"],
    ),
    "Function": (
        "Function / department master records",
        ["function", "functions", "department"],
    ),
    "Position": (
        "Job position master records",
        ["position", "positions", "designation master"],
    ),
    "Feature": (
        "Application feature catalog",
        ["feature", "features", "module feature"],
    ),
    "Module": (
        "Application module catalog",
        ["module", "modules"],
    ),
    "User_Group": (
        "Admin user group memberships",
        ["user group", "user groups", "group membership"],
    ),
    "PickListItem": (
        "Pick-list / dropdown item values",
        ["picklist", "pick list", "dropdown", "lookup value"],
    ),
    # Space BMS (bid management)
    "ProjectBD": (
        "Bid / tender opportunity master records (BMS)",
        ["bid", "bids", "tender", "tenders", "bidding", "bms", "project bd"],
    ),
    "ProjectBDBidding": (
        "Bidding details for a project bid",
        ["bidding details", "bid submission"],
    ),
    "ProjectBDClient": (
        "Clients linked to bid opportunities",
        ["bid client", "tender client", "bms client"],
    ),
    "ProjectBDBidOutcome": (
        "Outcome of a bid (won/lost/etc.)",
        ["bid outcome", "won lost", "tender result"],
    ),
    "ProjectBDRiskRegister": (
        "Risk register entries for bids",
        ["bid risk", "risk register", "tender risk"],
    ),
    "ProjectBDDocuments": (
        "Documents attached to bid opportunities",
        ["bid document", "tender document"],
    ),
    "ProjectBDTopSheet": (
        "Bid top-sheet summary records",
        ["top sheet", "bid summary"],
    ),
    # Space CHKWP (checkpoints / submissions)
    "Submission": (
        "Checkpoint / checklist submission records",
        ["submission", "submissions", "checkpoint submission", "checklist"],
    ),
    "Submission_Observation": (
        "Observations recorded on a submission",
        ["submission observation", "checkpoint observation"],
    ),
    "Submission_CheckPoint_Response": (
        "Responses to checkpoint questions on a submission",
        ["checkpoint response", "checklist answer"],
    ),
    "Template_Definition": (
        "Checkpoint / checklist template definitions",
        ["template", "checklist template", "checkpoint template"],
    ),
    "Template_CheckPoint_Question": (
        "Questions within a checkpoint template",
        ["checkpoint question", "template question"],
    ),
    # Space CMS (contract management)
    "ProjectCM": (
        "Contract management master records (CMS)",
        ["contract", "contracts", "cms", "project cm", "contract management"],
    ),
    "ProjectCMDispute": (
        "Contract disputes",
        ["dispute", "disputes", "contract dispute"],
    ),
    "ProjectCMDisputeActions": (
        "Actions taken on contract disputes",
        ["dispute action", "dispute actions"],
    ),
    "ProjectCMDocuments": (
        "Documents linked to contracts",
        ["contract document", "cms document"],
    ),
    "ProjectCMCommuncationLogs": (
        "Communication logs for contracts",
        ["contract communication", "cms communication log"],
    ),
    "ProjectCMRegisters": (
        "Contract registers",
        ["contract register", "cms register"],
    ),
    "ProjectCMKeyContractDates": (
        "Key dates for contracts",
        ["contract dates", "key contract dates"],
    ),
    "ProjectCMClauseInfo": (
        "Contract clause information",
        ["contract clause", "clause info"],
    ),
    # Space Dashboard aggregates
    "Dashboard_Master_Project": (
        "Dashboard master list of projects",
        ["dashboard project", "dashboard projects"],
    ),
    "Dashboard_Master_User": (
        "Dashboard master list of users",
        ["dashboard user", "dashboard users"],
    ),
    "Dashboard_Labour_Count": (
        "Dashboard labour headcount metrics",
        ["dashboard labour", "labour count", "workforce count"],
    ),
    "Dashboard_Hse_IncidentSummary": (
        "Dashboard HSE incident summary metrics",
        ["dashboard incident", "hse dashboard", "incident summary"],
    ),
    "Dashboard_Finance_Kpi": (
        "Dashboard finance KPI metrics",
        ["finance kpi", "dashboard finance", "financial kpi"],
    ),
    "Dashboard_ContractDispute_DisputeList": (
        "Dashboard list of contract disputes",
        ["dashboard dispute", "dispute list"],
    ),
    "Dashboard_PnL": (
        "Dashboard profit and loss records",
        ["pnl", "profit and loss", "dashboard pnl"],
    ),
    "Dashboard_Project_Details": (
        "Dashboard project detail records",
        ["dashboard project details"],
    ),
    # Space Notification
    "Notification": (
        "Notification / alert master records",
        ["notification", "notifications", "alert", "alerts"],
    ),
    "NotificationRecipient": (
        "Recipients of notifications",
        ["notification recipient", "alert recipient"],
    ),
    "NotificationSchedule": (
        "Schedules for notifications",
        ["notification schedule", "alert schedule"],
    ),
    "NotificationChannel": (
        "Channels used to deliver notifications",
        ["notification channel", "email channel", "sms channel"],
    ),
    "NotificationExecution": (
        "Execution runs of notifications",
        ["notification execution", "notification sent"],
    ),
    # Space Analytics (DA charts / wage analytics)
    "DA_Chart_Device_Status": (
        "Analytics chart data for device / biometric status",
        ["device status", "analytics device", "biometric status chart"],
    ),
    "DA_Chart_Donut_Wages": (
        "Analytics donut chart of wage distribution",
        ["wage chart", "donut wages", "analytics wages"],
    ),
    "DA_Chart_Grid_Labour_at_site_average": (
        "Analytics grid of average labour at site",
        ["labour at site", "site labour average", "analytics labour"],
    ),
    "DA_Chart_Labour_Contractor_wages": (
        "Analytics of labour contractor wages",
        ["contractor wages", "labour wages analytics"],
    ),
    "DA_Chart_Line_Punch_In_Out": (
        "Analytics line chart of punch in/out trends",
        ["punch in out", "attendance punch chart", "analytics punch"],
    ),
    "DA_Chart_Odd_Punches": (
        "Analytics of odd / exception punches",
        ["odd punches", "punch exceptions", "analytics odd punch"],
    ),
    "DA_Chart_Work_and_OT_hours": (
        "Analytics of work hours and overtime",
        ["ot hours", "overtime", "work hours", "analytics ot"],
    ),
    "DA_Compliance_Exceptions": (
        "Analytics compliance exception records",
        ["compliance exceptions", "analytics compliance"],
    ),
    "LMS_LabourWages_Monthly": (
        "Monthly labour wage analytics aggregates",
        ["monthly wages", "labour wages monthly", "analytics monthly wage"],
    ),
    "WH_OT_Hours": (
        "Warehouse / work-hour OT analytics",
        ["ot hours warehouse", "wh ot"],
    ),
    "CPU_Memory_Usage": (
        "Server CPU and memory usage metrics",
        ["cpu", "memory", "server usage", "analytics cpu"],
    ),
    "DA_DBConfiguration": (
        "Analytics database configuration",
        ["analytics config", "da configuration"],
    ),
    "DA_ErrorLog": (
        "Analytics processing error log",
        ["analytics error", "da error log"],
    ),
}


def describe_table(
    table_name: str, *, source_label: str = "Space"
) -> tuple[str, list[str]]:
    if table_name in _TABLE_HINTS:
        return _TABLE_HINTS[table_name]
    words = re.sub(r"[_\-]+", " ", table_name).strip()
    return (f"{source_label} table {table_name}", [words.lower(), table_name.lower()])


def describe_column(table_name: str, column_name: str, data_type: str) -> str:
    col = column_name.lower()
    if col.endswith("id") and col != "id":
        return f"Identifier linking or uniquely identifying {column_name}"
    if "title" in col or col == "name":
        return "Display title/name"
    if "agenda" in col:
        return "Agenda text content"
    if "location" in col:
        return "Location / place"
    if "date" in col or "time" in col:
        return "Date/time field"
    if col.startswith("is"):
        return "Boolean flag"
    if "note" in col or "information" in col or "description" in col:
        return "Free-text description/notes"
    return f"{column_name} ({data_type})"
