"""Regenerate the sample corpus in ``samples/``.

The generated files are committed, so you only need this when you want to edit
the sample content. Run it from the repository root:

    python scripts/make_samples.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdfwriter import write_pdf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


INTERN_HANDBOOK = """Analytics and Data Science Internship Handbook
Northwind Analytics | Revision 4.2 | Effective 1 March 2026

1. Programme overview
The Data Science Internship is a 24-week placement in the Analytics and Insight function. Interns
join one of three pods: Customer Analytics, Risk Modelling, or Platform and Tooling. The programme
runs twice a year, starting in March and September, and is open to students in their penultimate or
final year of a quantitative degree.

2. Responsibilities of a data science intern
A data science intern is expected to:
Clean, validate and document datasets before they are used in any downstream model or report.
Build and evaluate baseline models under the supervision of an assigned mentor, and record every
experiment in the team's experiment tracker.
Write reproducible analysis code in Python, with unit tests for any transformation that feeds a
production dashboard.
Present findings at the fortnightly pod review, including the limitations and assumptions behind
each result.
Maintain data documentation in the internal catalogue, including field definitions, refresh
cadence and known quality issues.
Raise data quality defects in the tracker within one working day of discovering them.
Complete the mandatory data protection and information security training within the first two
weeks of the placement.
Interns are not permitted to deploy models to production, alter production pipelines, or share
analysis outputs outside the company without written approval from their supervising manager.

3. Reporting line and mentorship
Every intern reports to a pod lead and is assigned a mentor, who is a mid-level or senior data
scientist. The mentor holds a 45-minute one-to-one every week and is responsible for the intern's
technical development plan. Escalations that the mentor cannot resolve go to the Head of Analytics.

4. Working hours and location
The standard week is 37.5 hours, Monday to Friday. The team operates a hybrid pattern: interns
attend the office on Tuesdays and Wednesdays and may work remotely on other days. Core
collaboration hours are 10:00 to 16:00 local time. Overtime is not expected and must be approved
in advance by the pod lead.

5. Tooling and access
Interns receive a managed laptop, an account on the analytics platform, read access to the curated
data warehouse layer, and a personal sandbox schema. Access to raw customer tables and to any
dataset classified as Restricted is not granted to interns. Requests for additional access go
through the Helpdesk and require pod lead approval.

6. Compensation
The internship is paid at a monthly stipend of 2,400 units of local currency, paid on the last
working day of each month. Interns are eligible for the commuting allowance and for the same
subsidised canteen rate as permanent staff. Interns do not accrue company bonus entitlement.

7. Leave during the placement
Interns accrue paid leave at 2 days per completed month, up to a maximum of 12 days across the
placement. Leave requests follow the standard company approval workflow and must be submitted at
least five working days in advance. Sick leave is covered by the company sick leave policy.

8. Evaluation and conversion to a graduate offer
Interns are assessed at week 12 and week 22 against four criteria: technical execution, analytical
judgement, communication, and collaboration. A conversion offer to the Graduate Data Scientist
programme requires an overall rating of "strong" or above at week 22, a positive mentor
recommendation, and an available headcount in the pod. Conversion decisions are communicated within
three weeks of the final review.

9. Code of conduct
Interns are bound by the company code of conduct, the information security policy and the data
protection policy. Any suspected breach must be reported to the security team immediately. Sharing
credentials, exporting data to personal storage, and using production data in personal projects
are all grounds for immediate termination of the placement.
"""


SECURITY_POLICY = """Information Security Policy
Northwind Analytics | Document ISP-001 | Version 7.1 | Approved 14 January 2026

1. Purpose and scope
This policy defines how Northwind Analytics protects the confidentiality, integrity and
availability of its information assets. It applies to all employees, contractors, interns and
third parties who access company systems or data, on any device, in any location.

2. Data classification
All information must be classified into one of four levels. Public: approved for release outside
the company. Internal: default for day-to-day business information; not for external release.
Confidential: commercially sensitive information, including contracts, financial forecasts and
unreleased product plans. Restricted: personal data, authentication secrets, security findings and
anything whose disclosure would cause severe harm. Restricted data may only be processed on managed
devices and may never be copied to personal storage or unapproved cloud services.

3. Access control
Access is granted on the principle of least privilege and must be approved by the data owner.
All accounts require multi-factor authentication. Passwords must be at least 14 characters,
generated by the company password manager, and unique to each system. Shared accounts are
prohibited. Access rights are reviewed quarterly, and are revoked within 24 hours of an employee
leaving or changing role.

4. Device security
Company laptops and phones must have full-disk encryption enabled, an automatic screen lock after
10 minutes of inactivity, and the managed endpoint agent installed and running. Operating system
and browser updates must be applied within 14 days of release, and within 48 hours where the
update fixes a vulnerability rated critical. Personal devices may access company email and chat
only through the managed application container.

5. Acceptable use
Company systems are provided for business use. Incidental personal use is permitted where it does
not interfere with work, incur cost, or introduce risk. Staff must not disable security controls,
connect unapproved devices to the corporate network, install unlicensed software, or use generative
AI services with Confidential or Restricted data unless the service appears on the approved list
maintained by the security team.

6. Incident reporting
Any suspected or actual security incident must be reported to the security team within one hour of
discovery, by email to security@northwind.example or by calling the 24-hour security hotline.
Reportable events include lost or stolen devices, suspected phishing, accidental disclosure of
data, malware alerts and unauthorised access. Staff must not attempt to investigate or remediate an
incident themselves, and must preserve evidence, including keeping the affected device powered on
and connected. The security team acknowledges every report within two hours and assigns a severity
within four hours. Incidents rated severity 1 are escalated to the executive team immediately and
regulators are notified within 72 hours where personal data is involved.

7. Third parties and suppliers
Suppliers who process company data must complete a security assessment before contract signature
and must be re-assessed annually. Contracts must include breach notification within 24 hours, a
right to audit, and defined data deletion obligations at the end of the engagement. Third-party
access is time-limited and granted through the supplier portal, never by sharing staff credentials.

8. Data retention and disposal
Business records are retained for seven years unless a longer statutory period applies. Personal
data is retained only as long as needed for the purpose it was collected for, as recorded in the
processing register. Electronic media is wiped to the current NIST purge standard before disposal,
and paper records containing Confidential or Restricted information are cross-cut shredded.

9. Business continuity
Critical systems are backed up daily, with backups replicated to a second region and tested by
restore at least twice a year. The recovery time objective for critical systems is four hours and
the recovery point objective is one hour.

10. Compliance and exceptions
Breaches of this policy may lead to disciplinary action up to and including dismissal, and to
termination of contract for third parties. Exceptions must be requested in writing, carry a
business justification and a compensating control, and are approved by the Chief Information
Security Officer for a maximum of 90 days. This policy is reviewed annually, or sooner after a
severity 1 incident or a material change in regulation.
"""


LEAVE_POLICY = """EMPLOYEE LEAVE POLICY
Northwind Analytics | HR-014 | Version 3.0 | Effective 1 April 2026

1. SCOPE
This policy covers all permanent and fixed-term employees. Interns are covered by the separate
provisions in the internship handbook. Contractors are covered by their engagement terms.

2. ANNUAL LEAVE
Full-time employees receive 24 days of paid annual leave per calendar year, in addition to public
holidays. Entitlement is pro-rated for part-time employees and for anyone joining or leaving
part-way through the year. Annual leave accrues monthly at two days per completed month of service.

Employees may carry over a maximum of 5 unused days into the following year. Carried-over days
must be taken by 31 March, after which they lapse without payment. Carry-over above 5 days is
granted only where the employee was prevented from taking leave by business demands, and requires
approval from a department head.

After five years of continuous service, annual leave increases to 27 days per year, effective from
the January following the fifth anniversary.

3. REQUESTING LEAVE
Leave requests are submitted in the HR system. The required notice is twice the length of the
absence, with a minimum of five working days. Requests of ten days or more require fifteen working
days' notice. Managers respond within five working days. Where two requests conflict and the team
cannot cover both, the request submitted first takes precedence.

Leave may be refused where it falls in a declared business-critical period, but no employee may be
refused so often that they cannot take their full entitlement within the leave year.

4. PUBLIC HOLIDAYS
Employees receive all statutory public holidays for their country of employment. Staff required to
work a public holiday receive a day off in lieu, to be taken within three months.

5. SICK LEAVE
Employees receive 12 days of paid sick leave per calendar year. Absence must be reported to the
line manager before 10:00 on the first day of absence. A medical certificate is required for any
absence of more than three consecutive working days, and for any absence immediately before or
after a period of annual leave. Unused sick leave does not carry over and is not paid out.

6. PARENTAL LEAVE
The primary caregiver is entitled to 26 weeks of leave, of which the first 18 weeks are paid at
full salary. The secondary caregiver is entitled to 8 weeks at full salary. Parental leave must
start within 12 months of the birth or placement. Employees returning from parental leave may
request a phased return of up to 8 weeks at 80 percent hours on full pay.

7. COMPASSIONATE AND EMERGENCY LEAVE
Up to 5 paid days per event are available on the death of an immediate family member, and up to 2
paid days for a family emergency such as the sudden illness of a dependant. Further time may be
granted as unpaid leave at the manager's discretion.

8. UNPAID LEAVE AND SABBATICAL
Unpaid leave of up to 3 months may be approved by a department head where the absence can be
covered. After five years of continuous service, employees may apply for a sabbatical of up to 3
months; the role is held open and benefits continue, but salary is suspended for the period.

9. LEAVE ON EXIT
On leaving the company, unused accrued annual leave is paid in the final salary payment. Leave
taken in excess of the accrued entitlement is deducted from the final payment. Sick leave,
compassionate leave and carried-over days that have lapsed are not paid out.
"""


HELPDESK_FAQ = """IT HELPDESK - FREQUENTLY ASKED QUESTIONS
Northwind Analytics | Internal Support Wiki | Last updated 20 February 2026

HOW DO I CONTACT THE HELPDESK?
Raise a ticket in the service portal, or email helpdesk@northwind.example. The desk is staffed
08:00-18:00 on working days. Outside those hours, only severity 1 outages are handled, through the
on-call number listed on the intranet home page. Note that security incidents do not go to the
helpdesk: they go to the security team within one hour, as set out in the information security
policy.

WHAT ARE THE RESPONSE TARGETS?
Severity 1, a full outage of a business-critical system: response within 30 minutes, around the
clock. Severity 2, a major function unavailable for a team: response within 2 working hours.
Severity 3, an individual blocked: response within 1 working day. Severity 4, a request or
question: response within 3 working days.

I HAVE FORGOTTEN MY PASSWORD. WHAT DO I DO?
Use the self-service reset link on the sign-in page. It requires your registered phone for
multi-factor authentication. If your phone is also unavailable, the helpdesk can verify your
identity over a video call with photo ID and issue a temporary password valid for one hour. The
helpdesk will never ask for your existing password, and will never send a password over chat.

WHEN AM I ELIGIBLE FOR A REPLACEMENT LAPTOP?
Standard laptops are refreshed every 3 years. Earlier replacement is approved where a repair would
cost more than half the replacement price, where the device cannot run supported software, or after
accidental damage, which requires manager approval. Loan devices are available from the office
front desk for up to 5 working days.

HOW LONG DOES NEW-STARTER EQUIPMENT TAKE?
Hardware is delivered to the starter's registered address at least 2 working days before the start
date, provided HR confirmed the start date at least 10 working days in advance. Accounts and access
are provisioned overnight before day one. Requests raised inside the 10-day window are fulfilled on
a best-effort basis.

HOW DO I GET SOFTWARE INSTALLED?
Anything on the approved software catalogue can be installed by the user from the self-service
portal without a ticket. Software outside the catalogue needs a ticket with a business
justification, a manager approval, and, where the software processes company data, a security
review. Typical turnaround for a catalogue addition is 10 working days.

HOW DO I CONNECT TO THE VPN?
The VPN client is pre-installed on managed laptops and connects automatically on untrusted
networks. If it fails, sign out and back in, then restart the client from the system tray. Persistent
failures are usually an expired device certificate, which the helpdesk renews remotely in a few
minutes. The VPN is not required for the analytics platform, which is reached over the managed
identity provider.

CAN I USE A PERSONAL DEVICE FOR WORK?
Email and chat are available on personal phones through the managed application container. Personal
laptops must not be used for company work, and Confidential or Restricted data must never be
processed on them.

HOW DO I CLAIM AN EXPENSE?
Submit the claim in the expenses system within 60 days of the spend, with an itemised receipt.
Claims are approved by the line manager and paid in the next payroll run after approval. Claims
older than 60 days require a director-level exception.
"""


WAREHOUSE_MANUAL = """FULFILMENT CENTRE EQUIPMENT AND SAFETY MANUAL
Northwind Logistics | OPS-220 | Revision 9 | Issued 5 January 2026

SECTION 1 - PURPOSE
This manual sets out the safe operation of material handling equipment in Northwind fulfilment
centres. It applies to all site staff, agency workers and visiting contractors. Site induction
must be completed before entering the operational floor for the first time.

SECTION 2 - PERSONAL PROTECTIVE EQUIPMENT
The following PPE is mandatory across the whole operational floor: high-visibility vest or jacket,
steel toe-capped safety footwear, and, in the racking aisles and goods-in bays, a bump cap. Cut
resistant gloves are mandatory when handling banding, opening cartons with a knife, or handling
glass. Hearing protection is mandatory in the baler area and in any zone marked with the yellow ear
protection sign. Loose clothing, jewellery and untied long hair are not permitted near conveyors.

SECTION 3 - POWERED PALLET TRUCKS AND FORKLIFTS
Only staff holding a valid in-date licence for the specific truck class may operate it. Licences
are valid for 3 years and require a refresher assessment to renew. Every operator completes a
pre-use inspection at the start of each shift, covering forks, mast, hydraulics, brakes, horn,
lights, tyres and battery state, and records the result on the truck's check sheet. Any defect
found makes the truck out of service: attach a red tag, remove the key, and report it to the shift
supervisor immediately.

Site speed limit is 8 km/h in aisles and 5 km/h at junctions and in pedestrian zones. Forks are
carried no more than 150 mm above the floor when travelling. Never travel with a raised load, never
carry a passenger, and never lift a person on the forks. Pedestrians always have right of way;
sound the horn at every blind corner and at every aisle end.

SECTION 4 - RACKING AND LOAD HANDLING
Maximum load per pallet position is displayed on the rack beam label and must never be exceeded.
Damaged racking must be reported and the bay taken out of use immediately. Manual lifting is
limited to 25 kg for a single person; heavier items require two people or a lifting aid. Cartons
must not be stacked above shoulder height on a manual pallet.

SECTION 5 - CONVEYORS AND LOCKOUT/TAGOUT
Conveyor guards must be in place before any conveyor is started. Any maintenance, clearing of a
jam, or work inside a guard requires full lockout/tagout: isolate the energy source, apply a
personal lock and tag, verify zero energy by attempting a start, then perform the work. Only the
person who applied a lock may remove it. Reaching into a running conveyor for any reason is a
dismissible offence.

SECTION 6 - BATTERY CHARGING
Charging takes place only in the designated charging bay, which must remain clear of combustible
material. Wear a face shield and acid-resistant gloves when connecting lead-acid batteries. The
eyewash station in the charging bay is checked weekly and the check is recorded. Do not disconnect
a battery under load.

SECTION 7 - ACCIDENT AND NEAR-MISS REPORTING
All accidents, injuries and near misses must be reported to the shift supervisor before the end of
the shift, and recorded in the site incident log the same day. Injuries requiring more than first
aid are reported to the site manager immediately and to the health and safety lead within 24 hours.
Near misses are reviewed weekly at the site safety meeting. Reporting a near miss never results in
disciplinary action against the reporter.

SECTION 8 - EMERGENCIES
On hearing the continuous alarm, stop work, make equipment safe where it is, and leave by the
nearest marked exit to the assembly point shown on the zone plan. Do not use lifts. Fire marshals
sweep their zones and report to the incident controller at the assembly point. Do not re-enter the
building until the incident controller gives the all-clear.

SECTION 9 - TRAINING RECORDS
Site induction is refreshed annually. Manual handling training is refreshed every 2 years, and
lockout/tagout authorisation every year. Training records are held by the site administrator and
audited quarterly.
"""


def _write_docx(path: Path, title: str, body: str) -> None:
    import docx

    document = docx.Document()
    document.add_heading(title, level=0)
    for paragraph in body.strip().split("\n\n"):
        lines = paragraph.strip().split("\n")
        first = lines[0].strip()
        # A short line ending without punctuation is a section heading.
        if len(lines) == 1 and len(first) < 70 and not first.endswith("."):
            document.add_heading(first, level=1)
            continue
        document.add_paragraph(" ".join(line.strip() for line in lines))
    document.save(str(path))


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)

    body = INTERN_HANDBOOK.split("\n", 1)[1]
    _write_docx(
        SAMPLES / "data-science-intern-handbook.docx",
        "Analytics and Data Science Internship Handbook",
        body,
    )

    write_pdf(
        SAMPLES / "information-security-policy.pdf",
        SECURITY_POLICY.strip().split("\n"),
        title="Information Security Policy",
    )

    (SAMPLES / "employee-leave-policy.txt").write_text(
        LEAVE_POLICY.strip() + "\n", encoding="utf-8"
    )
    (SAMPLES / "it-helpdesk-faq.txt").write_text(HELPDESK_FAQ.strip() + "\n", encoding="utf-8")
    (SAMPLES / "warehouse-safety-manual.txt").write_text(
        WAREHOUSE_MANUAL.strip() + "\n", encoding="utf-8"
    )

    for path in sorted(SAMPLES.iterdir()):
        print(f"{path.name:<44} {path.stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
