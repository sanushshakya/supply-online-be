"""
HR Models — UK Employment Law Compliant
=======================================
Covers:
  • Employment Rights Act 1996 & Employment Rights Act 2025
  • Equality Act 2010 (protected characteristics)
  • UK Immigration Rules (Skilled Worker, Graduate, Student, eVisa, share codes)
  • Right to Work checks (digital eVisa / share code, IDVT, manual)
  • National Minimum Wage / National Living Wage (April 2026 rates)
  • Statutory Sick Pay (day-one entitlement from April 2026)
  • Annual Leave Records (6-year retention duty, April 2026)
  • Student Visa work restrictions (20 hrs/week degree; 10 hrs/week below degree)
  • Border Security, Asylum and Immigration Act 2025 (extended RTW scope)
  • GDPR / UK GDPR — sensitive data handling notes throughout

References:
  ACAS, GOV.UK, Home Office Employer's Guide (26 June 2025),
  Employment Rights Act 2025 (Royal Assent 18 December 2025).
"""

from decimal import Decimal
from django.db import models
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


# ─────────────────────────────────────────────────────────
# STATUTORY CONSTANTS (April 2026)
# ─────────────────────────────────────────────────────────
NMW_21_PLUS = Decimal("12.71")        # National Living Wage (aged 21+)
NMW_18_TO_20 = Decimal("10.85")
NMW_UNDER_18 = Decimal("8.00")
NMW_APPRENTICE = Decimal("8.00")

SSP_WEEKLY_RATE = Decimal("123.25")   # Statutory Sick Pay from 6 April 2026
SSP_LOW_EARNER_RATE = Decimal("0.80") # 80% of weekly earnings if below LEL
LOWER_EARNINGS_LIMIT = Decimal("129.00")  # Weekly LEL from April 2026

STATUTORY_ANNUAL_LEAVE_DAYS = 28      # Minimum (5.6 weeks × 5 days)
REDUNDANCY_WEEKLY_PAY_CAP = Decimal("751.00")  # From April 2026

# Student Visa hour limits
STUDENT_DEGREE_TERM_MAX_HOURS = 20
STUDENT_BELOW_DEGREE_TERM_MAX_HOURS = 10

NI_REGEX = RegexValidator(
    r'^[A-CEGHJ-PR-TW-Z]{1}[A-CEGHJ-NPR-TW-Z]{1}[0-9]{6}[A-D ]{1}$',
    "Enter a valid UK National Insurance number (e.g. AB 12 34 56 C)",
)


# ─────────────────────────────────────────────────────────
# DEPARTMENT
# ─────────────────────────────────────────────────────────
class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True, help_text="Short department code (e.g. FIN, HR, OPS)")
    description = models.TextField(blank=True)
    cost_centre = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    manager = models.ForeignKey(
        "Employee",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_departments",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} — {self.name}"


# ─────────────────────────────────────────────────────────
# JOB ROLE
# ─────────────────────────────────────────────────────────
class JobRole(models.Model):
    RQF_LEVEL_CHOICES = [(i, f"RQF Level {i}") for i in range(1, 9)]

    title = models.CharField(max_length=150)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="job_roles")
    soc_code = models.CharField(
        max_length=10, blank=True,
        help_text=(
            "Standard Occupational Classification (SOC 2020) code. "
            "Required for Skilled Worker visa sponsorship. "
            "From 22 July 2025, only RQF Level 6+ roles are sponsorable (with MAC exceptions)."
        ),
    )
    rqf_level = models.PositiveSmallIntegerField(
        null=True, blank=True,
        choices=RQF_LEVEL_CHOICES,
        help_text="Required Qualifications Framework level (1–8). Level 6 = bachelor's degree.",
    )
    is_shortage_occupation = models.BooleanField(
        default=False,
        help_text=(
            "On the UK Temporary Shortage List (Skilled Worker visa). "
            "Workers on this list cannot bring dependants to the UK."
        ),
    )
    is_visa_sponsorable = models.BooleanField(
        default=False,
        help_text="Eligible for Skilled Worker visa sponsorship under current immigration rules.",
    )
    minimum_annual_salary = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Minimum annual salary for this role (£). Must meet NMW and visa salary threshold (£41,700 from 2025).",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return f"{self.title} ({self.department.name})"


# ─────────────────────────────────────────────────────────
# EMPLOYEE  (Core model)
# ─────────────────────────────────────────────────────────
class Employee(models.Model):
    """
    Core employee record.
    Sensitive personal data is held here under UK GDPR (legitimate interest /
    legal obligation basis). Ethnic origin and disability are special-category
    data — minimise access via Django permissions.
    """

    # ── Identity ──────────────────────────────────────────
    GENDER_CHOICES = [
        ("MALE", "Male"),
        ("FEMALE", "Female"),
        ("NON_BINARY", "Non-binary"),
        ("SELF_DESCRIBE", "Self-describe"),
        ("PNS", "Prefer not to say"),
    ]

    # Ethnicity categories from ONS / Equality Act 2010 monitoring
    ETHNICITY_CHOICES = [
        ("WHITE_BRITISH", "White — English / Welsh / Scottish / N. Irish / British"),
        ("WHITE_IRISH", "White — Irish"),
        ("WHITE_GYPSY_TRAVELLER", "White — Gypsy or Irish Traveller"),
        ("WHITE_ROMA", "White — Roma"),
        ("WHITE_OTHER", "White — Any other White background"),
        ("MIXED_WHITE_BLACK_CARIB", "Mixed — White and Black Caribbean"),
        ("MIXED_WHITE_BLACK_AFRICAN", "Mixed — White and Black African"),
        ("MIXED_WHITE_ASIAN", "Mixed — White and Asian"),
        ("MIXED_OTHER", "Mixed — Any other Mixed / Multiple ethnic background"),
        ("ASIAN_INDIAN", "Asian / Asian British — Indian"),
        ("ASIAN_PAKISTANI", "Asian / Asian British — Pakistani"),
        ("ASIAN_BANGLADESHI", "Asian / Asian British — Bangladeshi"),
        ("ASIAN_CHINESE", "Asian / Asian British — Chinese"),
        ("ASIAN_OTHER", "Asian / Asian British — Any other Asian background"),
        ("BLACK_AFRICAN", "Black / African / Caribbean / Black British — African"),
        ("BLACK_CARIBBEAN", "Black / African / Caribbean / Black British — Caribbean"),
        ("BLACK_OTHER", "Black / African / Caribbean / Black British — Other"),
        ("OTHER_ARAB", "Other Ethnic Group — Arab"),
        ("OTHER_OTHER", "Other Ethnic Group — Any other ethnic group"),
        ("PNS", "Prefer not to say"),
    ]

    # ── Employment status ────────────────────────────────
    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("PROBATION", "On Probation"),
        ("ON_LEAVE", "On Leave"),
        ("SUSPENDED", "Suspended (Pending Investigation)"),
        ("NOTICE_PERIOD", "Serving Notice Period"),
        ("RESIGNED", "Resigned"),
        ("REDUNDANT", "Made Redundant"),
        ("DISMISSED", "Dismissed"),
        ("RETIRED", "Retired"),
        ("DECEASED", "Deceased"),
    ]

    EMPLOYMENT_TYPE_CHOICES = [
        ("FULL_TIME", "Full-time"),
        ("PART_TIME", "Part-time"),
        ("ZERO_HOURS", "Zero-hours Contract"),
        ("FIXED_TERM", "Fixed-term Contract"),
        ("TEMPORARY", "Temporary"),
        ("AGENCY", "Agency Worker"),
        ("CASUAL", "Casual Worker"),
        ("APPRENTICE", "Apprentice"),
        ("INTERN", "Intern / Work Experience"),
        ("VOLUNTEER", "Volunteer"),
        ("CONTRACTOR", "Contractor / Self-employed"),
    ]

    NATIONALITY_CHOICES = [
        ("BRITISH", "British Citizen"),
        ("IRISH", "Irish Citizen"),
        ("EEA_EU", "EEA / EU National"),
        ("COMMONWEALTH", "Commonwealth National"),
        ("OTHER", "Other Nationality"),
    ]

    STUDENT_LOAN_PLAN_CHOICES = [
        ("", "No student loan"),
        ("PLAN1", "Plan 1"),
        ("PLAN2", "Plan 2"),
        ("PLAN4", "Plan 4 (Scotland)"),
        ("POSTGRAD", "Postgraduate Loan"),
        ("PLAN1_POSTGRAD", "Plan 1 + Postgraduate Loan"),
        ("PLAN2_POSTGRAD", "Plan 2 + Postgraduate Loan"),
    ]

    # ── Personal Information ──────────────────────────────
    employee_number = models.CharField(
        max_length=20, unique=True,
        help_text="Unique internal employee ID (e.g. EMP-001)",
    )
    first_name = models.CharField(max_length=100)
    middle_names = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=100)
    preferred_name = models.CharField(max_length=100, blank=True, help_text="Name the employee wishes to be called")
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES)

    # Equality Act 2010 monitoring data (special-category — restrict admin access)
    ethnicity = models.CharField(
        max_length=40, choices=ETHNICITY_CHOICES, blank=True,
        help_text="For equality monitoring under the Equality Act 2010. Voluntary.",
    )
    disability_declared = models.BooleanField(
        null=True, blank=True,
        help_text="Has the employee disclosed a disability? (Equality Act 2010 — voluntary)",
    )
    disability_details = models.TextField(
        blank=True,
        help_text="Nature of disability and any reasonable adjustments required.",
    )

    # ── Contact ───────────────────────────────────────────
    personal_email = models.EmailField(unique=True)
    work_email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    county = models.CharField(max_length=100, blank=True)
    postcode = models.CharField(
        max_length=10,
        validators=[RegexValidator(r"^[A-Z]{1,2}[0-9][0-9A-Z]?\s?[0-9][A-Z]{2}$", "Enter a valid UK postcode")],
    )
    country = models.CharField(max_length=100, default="United Kingdom")

    # ── Employment Details ────────────────────────────────
    job_role = models.ForeignKey(JobRole, on_delete=models.PROTECT, related_name="employees")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="employees")
    manager = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="direct_reports",
    )
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES)
    employment_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PROBATION")
    start_date = models.DateField()
    end_date = models.DateField(
        null=True, blank=True,
        help_text="Termination / contract end date. Leave blank for open-ended employment.",
    )
    probation_end_date = models.DateField(
        null=True, blank=True,
        help_text=(
            "Probation end date. "
            "ERA 2025 recommends a max of 9 months. "
            "Employees have unfair dismissal rights from day 1 from January 2027."
        ),
    )

    # ── UK Payroll / HMRC ─────────────────────────────────
    national_insurance_number = models.CharField(
        max_length=13, blank=True,
        validators=[NI_REGEX],
        help_text="UK National Insurance number (e.g. AB 12 34 56 C). Required for PAYE.",
    )
    tax_code = models.CharField(
        max_length=10, blank=True,
        help_text="HMRC tax code assigned to this employee (e.g. 1257L, K800, BR, 0T).",
    )
    student_loan_plan = models.CharField(
        max_length=20, choices=STUDENT_LOAN_PLAN_CHOICES, blank=True,
    )
    pension_enrolled = models.BooleanField(
        default=False,
        help_text="Auto-enrolment: workers aged 22–66 earning above £10,000/yr must be enrolled.",
    )
    pension_opt_out = models.BooleanField(default=False)
    pension_opt_out_date = models.DateField(null=True, blank=True)
    p45_received = models.BooleanField(
        default=False,
        help_text="P45 received from previous employer on joining?",
    )

    # ── Nationality (for RTW context) ─────────────────────
    nationality = models.CharField(max_length=20, choices=NATIONALITY_CHOICES)

    # ── Metadata ──────────────────────────────────────────
    photo = models.ImageField(upload_to="hr/employee_photos/", null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = "Employee"
        verbose_name_plural = "Employees"

    def __str__(self):
        return f"[{self.employee_number}] {self.full_name}"

    # ── Properties ────────────────────────────────────────
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def display_name(self) -> str:
        return self.preferred_name or self.first_name

    @property
    def age(self) -> int:
        today = timezone.now().date()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    @property
    def years_of_service(self) -> float:
        end = self.end_date or timezone.now().date()
        return round((end - self.start_date).days / 365.25, 2)

    @property
    def applicable_nmw_rate(self) -> Decimal:
        """Return the legally applicable NMW/NLW rate for this employee (April 2026)."""
        if self.employment_type == "APPRENTICE":
            return NMW_APPRENTICE
        age = self.age
        if age >= 21:
            return NMW_21_PLUS
        if age >= 18:
            return NMW_18_TO_20
        return NMW_UNDER_18

    @property
    def is_active(self) -> bool:
        return self.employment_status in ("ACTIVE", "PROBATION", "ON_LEAVE", "NOTICE_PERIOD")

    # ── Validation ────────────────────────────────────────
    def clean(self):
        errors = {}
        today = timezone.now().date()

        if self.date_of_birth and self.date_of_birth >= today:
            errors["date_of_birth"] = "Date of birth must be in the past."

        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors["end_date"] = "End date cannot be before start date."

        if self.probation_end_date and self.start_date:
            if self.probation_end_date < self.start_date:
                errors["probation_end_date"] = "Probation end date cannot be before start date."

        if errors:
            raise ValidationError(errors)


# ─────────────────────────────────────────────────────────
# EMERGENCY CONTACT
# ─────────────────────────────────────────────────────────
class EmergencyContact(models.Model):
    RELATIONSHIP_CHOICES = [
        ("SPOUSE", "Spouse / Civil Partner"),
        ("PARTNER", "Partner"),
        ("PARENT", "Parent"),
        ("SIBLING", "Sibling"),
        ("CHILD", "Child"),
        ("FRIEND", "Friend"),
        ("CARER", "Carer"),
        ("OTHER", "Other"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="emergency_contacts")
    full_name = models.CharField(max_length=200)
    relationship = models.CharField(max_length=20, choices=RELATIONSHIP_CHOICES)
    phone_primary = models.CharField(max_length=20)
    phone_secondary = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.get_relationship_display()}) — {self.employee.full_name}"


# ─────────────────────────────────────────────────────────
# RIGHT TO WORK  (RTW)
# ─────────────────────────────────────────────────────────
class RightToWork(models.Model):
    """
    Right to Work check record.

    Legal basis: Immigration, Asylum and Nationality Act 2006;
                 Border Security, Asylum and Immigration Act 2025.

    Key 2025-26 rules:
      • BRPs are no longer valid for RTW checks (since 31 Oct 2024).
      • eVisa / share code is now primary method for non-British/Irish.
      • Share codes must start with 'W' (work). 'R' = rent, 'T' = travel.
      • Digital IDVT checks available for British/Irish citizens with valid passports.
      • Records must be kept for duration of employment + 2 years.
      • Fines up to £60,000 per illegal worker (from 2024).
      • From March 2025: checks required for gig economy / zero-hours workers too.
    """

    CHECK_TYPE_CHOICES = [
        ("MANUAL_LIST_A", "Manual Check — List A Document (permanent right)"),
        ("MANUAL_LIST_B", "Manual Check — List B Document (time-limited)"),
        ("ONLINE_SHARE_CODE", "Online Check — eVisa Share Code (Home Office portal)"),
        ("IDVT", "Digital IDVT — Identity Service Provider (British/Irish passport holders)"),
        ("EMPLOYER_CHECKING", "Employer Checking Service (ECS) — Positive Verification Notice"),
    ]

    DOCUMENT_TYPE_CHOICES = [
        # List A — permanent / unrestricted RTW
        ("UK_PASSPORT", "UK Passport (current or expired since age 18 if same nationality)"),
        ("IRISH_PASSPORT", "Irish Passport / Irish Passport Card"),
        ("UK_BIRTH_CERT_NI", "UK Birth / Adoption Certificate + National Insurance document"),
        ("ILR_DOC", "Indefinite Leave to Remain — Home Office letter"),
        ("SETTLED_EUSS", "EU Settlement Scheme — Settled Status (eVisa share code)"),
        ("CERTIFICATE_NATURALISATION", "Certificate of Registration / Naturalisation"),
        # List B — time-limited
        ("PRE_SETTLED_EUSS", "EU Settlement Scheme — Pre-Settled Status (eVisa share code)"),
        ("EVISA_SHARE_CODE", "eVisa — Share Code (Skilled Worker, Graduate, Student, etc.)"),
        ("VISA_VIGNETTE_90D", "Visa Vignette (90-day entry clearance — follow-up online check required)"),
        ("PVN", "Employer Checking Service — Positive Verification Notice"),
        # Legacy (no longer valid for new checks)
        ("BRP_LEGACY", "Biometric Residence Permit (BRP) — Legacy record only, invalid from 31 Oct 2024"),
    ]

    DOCUMENT_LIST_CHOICES = [
        ("A", "List A — Permanent / unlimited right to work"),
        ("B1", "List B Group 1 — Time-limited (ECS Positive Verification Notice)"),
        ("B2", "List B Group 2 — Time-limited (follow-up check required)"),
        ("DIGITAL", "Digital / eVisa (share code)"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="right_to_work_checks")
    check_type = models.CharField(max_length=30, choices=CHECK_TYPE_CHOICES)
    document_list = models.CharField(max_length=10, choices=DOCUMENT_LIST_CHOICES)
    document_type = models.CharField(max_length=40, choices=DOCUMENT_TYPE_CHOICES)

    # For share code checks (eVisa holders)
    share_code = models.CharField(
        max_length=9, blank=True,
        help_text=(
            "9-character share code from gov.uk/view-prove-work-right. "
            "MUST start with 'W' for right to work. "
            "'R' codes (rent) and 'T' codes (travel) are NOT valid."
        ),
    )
    date_of_birth_used_for_check = models.DateField(
        null=True, blank=True,
        help_text="DOB entered into Home Office employer portal alongside share code.",
    )

    # Dates
    check_date = models.DateField(help_text="Date check was performed — MUST be before the employee's first day.")
    document_expiry_date = models.DateField(
        null=True, blank=True,
        help_text="Expiry date of the document or immigration permission as shown in the online system.",
    )
    follow_up_check_due = models.DateField(
        null=True, blank=True,
        help_text=(
            "For List B documents: schedule follow-up check 28 days before permission expires. "
            "System will alert HR when this date approaches."
        ),
    )

    # Compliance
    checked_by = models.CharField(max_length=200, help_text="Full name of the HR officer who performed the check.")
    document_copy_retained = models.BooleanField(
        default=False,
        help_text=(
            "Confirm a dated, legible copy of the document / share code result has been saved. "
            "Retain for duration of employment + 2 years (Home Office requirement)."
        ),
    )
    permitted_work_type = models.TextField(
        blank=True,
        help_text="Any work type restrictions shown in share code result (e.g. student hour limits, specific employer only).",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-check_date"]
        verbose_name = "Right to Work Check"
        verbose_name_plural = "Right to Work Checks"

    def __str__(self):
        return f"RTW [{self.check_date}] — {self.employee.full_name} ({self.get_document_type_display()})"

    # ── Properties ────────────────────────────────────────
    @property
    def is_permission_expired(self) -> bool:
        if self.document_expiry_date:
            return self.document_expiry_date < timezone.now().date()
        return False

    @property
    def days_until_expiry(self):
        if self.document_expiry_date:
            return (self.document_expiry_date - timezone.now().date()).days
        return None

    @property
    def follow_up_required(self) -> bool:
        return self.document_list in ("B1", "B2", "DIGITAL")

    # ── Validation ────────────────────────────────────────
    def clean(self):
        errors = {}
        if self.share_code:
            if not self.share_code.upper().startswith("W"):
                errors["share_code"] = (
                    "Right to work share codes must start with 'W'. "
                    "'R' codes are for right to rent, 'T' codes for travel — neither is valid here."
                )
            if len(self.share_code) != 9:
                errors["share_code"] = "Share code must be exactly 9 characters."
        if self.check_date and self.document_expiry_date:
            if self.document_expiry_date < self.check_date:
                errors["document_expiry_date"] = "Document expiry date cannot be before the check date."
        if errors:
            raise ValidationError(errors)


# ─────────────────────────────────────────────────────────
# IMMIGRATION STATUS
# ─────────────────────────────────────────────────────────
class ImmigrationStatus(models.Model):
    """
    Immigration/visa status for non-British, non-Irish employees.
    One record per employee; historical changes captured via a separate audit log
    if needed (not in scope for v1).

    Key 2025-26 changes:
      • General Skilled Worker salary floor: £41,700 / SOC going rate (whichever higher).
      • Overseas care worker recruitment via Skilled Worker ended 22 July 2025.
      • Graduate visa reduces from 24 to 18 months for UG/Masters from Jan 2027.
      • HPI visa: expanded to top-100 international universities from Nov 2025.
      • Immigration Skills Charge rose 32% from December 2025.
      • English language requirement raised to B2 from 8 January 2026.
    """

    VISA_TYPE_CHOICES = [
        # Work routes
        ("SKILLED_WORKER", "Skilled Worker Visa"),
        ("HEALTH_CARE_WORKER", "Health and Care Worker Visa"),
        ("INTRA_COMPANY", "Intra-company Transfer"),
        ("GLOBAL_TALENT", "Global Talent Visa"),
        ("SCALE_UP", "Scale-up Worker Visa"),
        ("HIGH_POTENTIAL", "High Potential Individual (HPI) Visa"),
        ("GRADUATE", "Graduate Route Visa (post-study work)"),
        ("YOUTH_MOBILITY", "Youth Mobility Scheme (ages 18–35, up to 2 yrs)"),
        ("SEASONAL", "Seasonal Worker Visa"),
        ("TEMP_WORKER", "Temporary Worker Visa (Charity / Creative / Govt Authorised)"),
        # Study
        ("STUDENT", "Student Visa"),
        # Settlement / status
        ("EUSS_SETTLED", "EU Settlement Scheme — Settled Status (ILR equivalent)"),
        ("EUSS_PRE_SETTLED", "EU Settlement Scheme — Pre-Settled Status"),
        ("ILR", "Indefinite Leave to Remain (ILR)"),
        ("ILE", "Indefinite Leave to Enter (ILE)"),
        # Family
        ("SPOUSE_PARTNER", "Spouse / Partner Visa"),
        ("FAMILY", "Family Visa"),
        ("BNO", "British National (Overseas) BN(O) Visa"),
        # Asylum / Protection
        ("REFUGEE", "Refugee Status (Convention or Humanitarian Protection)"),
        ("ASYLUM_SEEKER", "Asylum Seeker (restricted RTW — Home Office permission required)"),
        # Citizenship
        ("BRITISH_CITIZEN", "British Citizen — No immigration control"),
        ("IRISH_CITIZEN", "Irish Citizen — No immigration control"),
        # Other
        ("OTHER", "Other — see notes"),
    ]

    WORK_RESTRICTION_CHOICES = [
        ("NONE", "No restrictions — can work in any role"),
        ("SPONSORED_ROLE_ONLY", "Restricted to sponsored employer / role (Skilled Worker)"),
        ("HOURS_LIMITED", "Limited hours (e.g. Student Visa — see StudentVisaRestriction)"),
        ("NO_SELF_EMPLOYMENT", "No self-employment or freelance work"),
        ("NO_WORK", "Not permitted to work"),
        ("AWAITING_DECISION", "Awaiting Home Office decision (may work if previous leave held)"),
        ("ASYLUM_SEEKER_RESTRICTED", "Asylum seeker — RTW only if Home Office grants permission"),
    ]

    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="immigration_status")
    visa_type = models.CharField(max_length=30, choices=VISA_TYPE_CHOICES)
    visa_reference_number = models.CharField(max_length=80, blank=True, help_text="Visa / vignette reference or GWF number")
    visa_start_date = models.DateField(null=True, blank=True)
    visa_expiry_date = models.DateField(null=True, blank=True)
    work_restrictions = models.CharField(max_length=40, choices=WORK_RESTRICTION_CHOICES, default="NONE")
    no_recourse_to_public_funds = models.BooleanField(
        default=False,
        help_text=(
            "Employee's visa has a 'no recourse to public funds' condition (NRPF). "
            "This affects statutory pay entitlements — seek legal advice."
        ),
    )

    # For sponsored workers (Skilled Worker, Health and Care, etc.)
    is_employer_sponsored = models.BooleanField(default=False)
    certificate_of_sponsorship_number = models.CharField(
        max_length=60, blank=True,
        help_text="Certificate of Sponsorship (COS) reference number issued by this employer.",
    )
    sponsor_licence_number = models.CharField(
        max_length=60, blank=True,
        help_text="UK Visas & Immigration sponsor licence number for this employer.",
    )
    soc_code_on_cos = models.CharField(
        max_length=10, blank=True,
        help_text="SOC code on the Certificate of Sponsorship — must match actual job duties.",
    )
    immigration_skills_charge_paid = models.BooleanField(
        default=False,
        help_text=(
            "Immigration Skills Charge paid? (£1,320/yr SME; £1,000/yr charity; "
            "£6,600 total for 5-yr visa for large sponsors from Dec 2025)."
        ),
    )

    # Passport
    country_of_nationality = models.CharField(max_length=100)
    passport_number = models.CharField(max_length=50, blank=True)
    passport_expiry = models.DateField(null=True, blank=True)

    # eVisa
    has_evisa = models.BooleanField(
        default=False,
        help_text="Does the employee have a UKVI online account (eVisa)?",
    )
    ukvi_account_reference = models.CharField(
        max_length=60, blank=True,
        help_text="UKVI online account / eVisa reference (NOT to be stored without need — UK GDPR).",
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Immigration Status"
        verbose_name_plural = "Immigration Statuses"

    def __str__(self):
        return f"{self.employee.full_name} — {self.get_visa_type_display()}"

    @property
    def is_visa_expired(self) -> bool:
        if self.visa_expiry_date:
            return self.visa_expiry_date < timezone.now().date()
        return False

    @property
    def days_until_visa_expiry(self):
        if self.visa_expiry_date:
            return (self.visa_expiry_date - timezone.now().date()).days
        return None

    def clean(self):
        if self.visa_start_date and self.visa_expiry_date:
            if self.visa_expiry_date <= self.visa_start_date:
                raise ValidationError({"visa_expiry_date": "Visa expiry date must be after start date."})


# ─────────────────────────────────────────────────────────
# STUDENT VISA RESTRICTION
# ─────────────────────────────────────────────────────────
class StudentVisaRestriction(models.Model):
    """
    Tracks UK Student Visa work restrictions for international students.

    Rules (2025-26):
      • Degree level or above:        Max 20 hrs/week during term time (Mon–Sun).
      • Below degree level:           Max 10 hrs/week during term time.
      • Postgraduate researchers:     Max 20 hrs/week year-round (no distinct terms).
      • Vacation periods:             Full-time work permitted (with evidence of vacation).
      • After course completion:      Full-time permitted (max 4 months on Student visa).
      • Cannot be self-employed, freelance, do gig-economy work, or fill a permanent vacancy.
      • Cannot work as professional sportsperson or coach.
      • All unpaid voluntary work counts toward the weekly limit.
      • On-call hours where attendance is required count toward the limit.
      • Multiple employers: combined hours across all jobs must not exceed limit.
      • Employers must verify term dates via university letter or Confirmation of Acceptance
        for Studies (CAS) end date to determine vacation periods.
      • Employers face fines of up to £60,000 per illegal worker if limits are breached.
    """

    STUDY_LEVEL_CHOICES = [
        ("DEGREE_ABOVE", "Degree Level or Above (20 hrs/wk term time)"),
        ("BELOW_DEGREE", "Below Degree Level (10 hrs/wk term time)"),
        ("POSTGRAD_RESEARCH", "Postgraduate Research — Masters/PhD (20 hrs/wk, year-round limit)"),
        ("STUDY_ABROAD", "Study Abroad Programme at Overseas HEI (20 hrs/wk term time)"),
    ]

    immigration_status = models.OneToOneField(
        ImmigrationStatus,
        on_delete=models.CASCADE,
        related_name="student_restrictions",
    )
    study_level = models.CharField(max_length=30, choices=STUDY_LEVEL_CHOICES)
    institution_name = models.CharField(max_length=250)
    institution_is_licensed_sponsor = models.BooleanField(
        default=True,
        help_text=(
            "Students at unlicensed institutions cannot work at all. "
            "Students at private (non-HEI) colleges may have no work rights."
        ),
    )
    cas_number = models.CharField(
        max_length=60, blank=True,
        help_text="Confirmation of Acceptance for Studies (CAS) number. Used to verify term dates.",
    )
    course_start_date = models.DateField()
    course_end_date = models.DateField(
        help_text="CAS end date. Use this (not institution's internal dates) to determine wrap-up period.",
    )

    # Weekly hour limits
    term_time_max_hours_per_week = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(20)],
        help_text="Maximum paid + unpaid work hours per week (Mon–Sun) during term time.",
    )

    # Current status
    is_currently_in_vacation = models.BooleanField(
        default=False,
        help_text=(
            "Is the student currently in a confirmed vacation period? "
            "Full-time work is permitted during vacations. Evidence must be on file."
        ),
    )
    vacation_evidence_on_file = models.BooleanField(
        default=False,
        help_text="University term-date letter or equivalent evidence received and retained.",
    )
    studies_completed = models.BooleanField(
        default=False,
        help_text=(
            "Has the student completed ALL academic requirements? "
            "Full-time work permitted after completion (max 4 months on Student visa unless Graduate visa obtained)."
        ),
    )
    completion_evidence_date = models.DateField(
        null=True, blank=True,
        help_text="Date completion was confirmed (e.g. degree award notification, thesis submission accepted).",
    )
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Student Visa Work Restriction"

    def __str__(self):
        return f"{self.immigration_status.employee.full_name} — Student restriction ({self.get_study_level_display()})"

    @property
    def current_max_hours(self):
        """Returns the current maximum working hours per week, or None if unrestricted."""
        if self.studies_completed or self.is_currently_in_vacation:
            return None  # Full-time work permitted
        return self.term_time_max_hours_per_week

    def clean(self):
        errors = {}
        if self.immigration_status.visa_type != "STUDENT":
            errors["immigration_status"] = "Student visa restrictions can only be applied to Student Visa holders."
        if self.study_level == "BELOW_DEGREE" and self.term_time_max_hours_per_week > 10:
            errors["term_time_max_hours_per_week"] = "Below-degree students are legally limited to 10 hours/week during term time."
        elif self.study_level != "BELOW_DEGREE" and self.term_time_max_hours_per_week > 20:
            errors["term_time_max_hours_per_week"] = "Students at degree level or above are legally limited to 20 hours/week during term time."
        if self.course_start_date and self.course_end_date:
            if self.course_end_date <= self.course_start_date:
                errors["course_end_date"] = "Course end date must be after start date."
        if errors:
            raise ValidationError(errors)


# ─────────────────────────────────────────────────────────
# CONTRACT
# ─────────────────────────────────────────────────────────
class Contract(models.Model):
    """
    Employment contract record.
    ERA 2025: probation max 9 months (recommended). Unfair dismissal from day 1 from Jan 2027.
    Zero-hours workers: right to request guaranteed hours (ERA 2025 — from 2026/27).
    Fire and rehire: stricter restrictions under ERA 2025.
    Holiday records: must be kept for 6 years from April 2026.
    Flexible working: right to request from day 1 since April 2024.
    """

    CONTRACT_TYPE_CHOICES = [
        ("PERMANENT", "Permanent Contract"),
        ("FIXED_TERM", "Fixed-term Contract"),
        ("ZERO_HOURS", "Zero-hours Contract"),
        ("CASUAL", "Casual Worker Agreement"),
        ("APPRENTICESHIP", "Apprenticeship Agreement"),
        ("AGENCY", "Agency Worker Contract"),
    ]

    PAY_FREQUENCY_CHOICES = [
        ("WEEKLY", "Weekly"),
        ("FORTNIGHTLY", "Fortnightly"),
        ("FOUR_WEEKLY", "Four-weekly"),
        ("MONTHLY", "Monthly"),
    ]

    NOTICE_UNIT_CHOICES = [
        ("DAYS", "Days"),
        ("WEEKS", "Weeks"),
        ("MONTHS", "Months"),
    ]

    REMOTE_ARRANGEMENT_CHOICES = [
        ("OFFICE", "Fully office-based"),
        ("HYBRID", "Hybrid"),
        ("REMOTE", "Fully remote"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="contracts")
    contract_type = models.CharField(max_length=20, choices=CONTRACT_TYPE_CHOICES)
    is_current = models.BooleanField(default=True)
    start_date = models.DateField()
    end_date = models.DateField(
        null=True, blank=True,
        help_text="Required for fixed-term contracts.",
    )

    # Pay
    contracted_hours_per_week = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Leave blank for zero-hours contracts.",
    )
    annual_salary = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Annual gross salary (£). Must not result in an hourly rate below NMW.",
    )
    hourly_rate = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Gross hourly rate (£). Must be ≥ applicable NMW/NLW rate.",
    )
    pay_frequency = models.CharField(max_length=20, choices=PAY_FREQUENCY_CHOICES, default="MONTHLY")

    # Notice
    employee_notice_period = models.PositiveSmallIntegerField(default=1)
    employee_notice_unit = models.CharField(max_length=10, choices=NOTICE_UNIT_CHOICES, default="MONTHS")
    employer_notice_period = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            "Statutory minimum: 1 week per complete year of service "
            "(up to 12 weeks max under ERA 1996 s86)."
        ),
    )
    employer_notice_unit = models.CharField(max_length=10, choices=NOTICE_UNIT_CHOICES, default="MONTHS")

    # Probation
    probation_period_months = models.PositiveSmallIntegerField(
        default=6,
        help_text="Probation length in months. ERA 2025 recommends a maximum of 9 months.",
    )

    # Working arrangement
    work_location = models.CharField(max_length=255, blank=True)
    remote_arrangement = models.CharField(
        max_length=10, choices=REMOTE_ARRANGEMENT_CHOICES, blank=True,
    )

    # Flexible working (Employment Relations (Flexible Working) Act 2023)
    flexible_working_request_active = models.BooleanField(
        default=False,
        help_text=(
            "Employee has a live flexible working request. "
            "Since April 2024, employees may request from day 1 (up to 2 requests per 12 months). "
            "Decision must be made within 2 months."
        ),
    )
    flexible_working_decision_due = models.DateField(null=True, blank=True)

    # Zero-hours
    guaranteed_hours_offered = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text=(
            "For zero-hours workers regularly working set hours: "
            "ERA 2025 will give a right to request a guaranteed-hours contract."
        ),
    )

    signed_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.employee.full_name} — {self.get_contract_type_display()} from {self.start_date}"

    @property
    def effective_hourly_rate(self):
        """Derive hourly rate from salary if not directly specified."""
        if self.hourly_rate:
            return float(self.hourly_rate)
        if self.annual_salary and self.contracted_hours_per_week:
            return round(float(self.annual_salary) / (float(self.contracted_hours_per_week) * 52), 2)
        return None

    def clean(self):
        errors = {}
        if self.contract_type == "FIXED_TERM" and not self.end_date:
            errors["end_date"] = "Fixed-term contracts must have an end date."
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors["end_date"] = "Contract end date cannot be before start date."
        if not self.annual_salary and not self.hourly_rate:
            if self.contract_type not in ("ZERO_HOURS", "CASUAL"):
                errors["hourly_rate"] = "Contract must specify either an annual salary or hourly rate."
        if errors:
            raise ValidationError(errors)


# ─────────────────────────────────────────────────────────
# ANNUAL LEAVE
# ─────────────────────────────────────────────────────────
class AnnualLeaveEntitlement(models.Model):
    """
    Annual leave entitlement and balance per leave year.
    UK statutory minimum: 28 days (5.6 weeks) for full-time workers.
    Part-time workers receive a pro-rata equivalent.
    From April 2026: employers must keep holiday records for 6 years.
    """

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="annual_leave_entitlements")
    leave_year_start = models.DateField(help_text="First day of the leave year (e.g. 01/01/2026 or 01/04/2026).")
    leave_year_end = models.DateField(help_text="Last day of the leave year.")

    total_entitlement_days = models.DecimalField(
        max_digits=5, decimal_places=1,
        help_text=f"Total leave entitlement for this year (statutory minimum: {STATUTORY_ANNUAL_LEAVE_DAYS} days full-time).",
    )
    bank_holidays_included = models.BooleanField(
        default=True,
        help_text="Are bank holidays counted within the 28-day entitlement (permitted) or in addition?",
    )
    carried_over_days = models.DecimalField(
        max_digits=5, decimal_places=1, default=Decimal("0.0"),
        help_text="Days carried over from previous leave year.",
    )
    days_taken = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("0.0"))
    days_approved_pending = models.DecimalField(
        max_digits=5, decimal_places=1, default=Decimal("0.0"),
        help_text="Days approved but not yet taken.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("employee", "leave_year_start")
        ordering = ["-leave_year_start"]
        verbose_name = "Annual Leave Entitlement"

    def __str__(self):
        return f"{self.employee.full_name} — Leave year {self.leave_year_start.year}"

    @property
    def days_remaining(self) -> Decimal:
        return (
            self.total_entitlement_days
            + self.carried_over_days
            - self.days_taken
            - self.days_approved_pending
        )

    def clean(self):
        if self.leave_year_end and self.leave_year_start:
            if self.leave_year_end <= self.leave_year_start:
                raise ValidationError({"leave_year_end": "Leave year end must be after start."})


# ─────────────────────────────────────────────────────────
# LEAVE REQUEST
# ─────────────────────────────────────────────────────────
class LeaveRequest(models.Model):
    """
    Individual leave request. Linked to AnnualLeaveEntitlement for balance tracking.
    ERA 2025 introduces day-one paternity and unpaid parental leave from April 2026.
    New: Bereaved Partner's Paternity Leave (up to 52 weeks unpaid) from April 2026.
    Neonatal care leave introduced from April 2025.
    """

    LEAVE_TYPE_CHOICES = [
        # Statutory leave types
        ("ANNUAL", "Annual Leave"),
        ("SICK", "Sick Leave (see SickLeaveRecord)"),
        ("MATERNITY", "Maternity Leave (up to 52 weeks)"),
        ("PATERNITY", "Paternity Leave (day-one right from April 2026)"),
        ("SHARED_PARENTAL", "Shared Parental Leave"),
        ("ADOPTION", "Adoption Leave"),
        ("UNPAID_PARENTAL", "Unpaid Parental Leave (day-one right from April 2026)"),
        ("PARENTAL_BEREAVEMENT", "Parental Bereavement Leave (2 weeks)"),
        ("BEREAVED_PARTNER_PATERNITY", "Bereaved Partner's Paternity Leave (up to 52 weeks, from April 2026)"),
        ("NEONATAL", "Neonatal Care Leave (from April 2025)"),
        # Non-statutory
        ("COMPASSIONATE", "Compassionate / Bereavement Leave"),
        ("JURY_DUTY", "Jury Duty / Public Duties"),
        ("STUDY", "Study / Exam Leave"),
        ("UNPAID", "Unpaid Leave"),
        ("CAREER_BREAK", "Career Break / Sabbatical"),
        ("TOIL", "Time Off in Lieu (TOIL)"),
        ("OTHER", "Other"),
    ]

    STATUS_CHOICES = [
        ("PENDING", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("CANCELLED", "Cancelled by Employee"),
        ("RECALLED", "Recalled by Employer"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.CharField(max_length=40, choices=LEAVE_TYPE_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField()
    number_of_days = models.DecimalField(
        max_digits=5, decimal_places=1,
        help_text="Number of working days requested (accounting for part-time patterns).",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    reason = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        Employee, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_leave_requests",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    annual_leave_entitlement = models.ForeignKey(
        AnnualLeaveEntitlement, null=True, blank=True,
        on_delete=models.SET_NULL,
        help_text="Link to the entitlement record this leave deducts from.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.employee.full_name} — {self.get_leave_type_display()} ({self.start_date} → {self.end_date})"

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Leave end date cannot be before start date."})


# ─────────────────────────────────────────────────────────
# SICK LEAVE RECORD
# ─────────────────────────────────────────────────────────
class SickLeaveRecord(models.Model):
    """
    Individual sickness absence episode for SSP calculation and management.

    From 6 April 2026 (Employment Rights Act 2025):
      • SSP payable from DAY ONE of sickness (no 3-day waiting period).
      • SSP rate: £123.25/week OR 80% of normal weekly earnings, whichever is lower,
        for employees earning below the Lower Earnings Limit (£129/week).
      • No lower earnings limit barrier — all employees now eligible.
      • HMRC requires absence records to be kept for 3 years.
    """

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="sick_leave_records")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text="Leave blank if employee is still absent.")
    reason = models.TextField(blank=True, help_text="General reason for absence (e.g. respiratory illness).")

    # Certification
    self_certified = models.BooleanField(
        default=True,
        help_text="Employee may self-certify for the first 7 consecutive calendar days.",
    )
    fit_note_received = models.BooleanField(
        default=False,
        help_text="Fit note (Med 3) from GP/healthcare professional received for absence > 7 days.",
    )
    fit_note_date = models.DateField(null=True, blank=True)
    fit_note_expiry = models.DateField(null=True, blank=True)
    fit_note_recommendation = models.CharField(
        max_length=40, blank=True,
        choices=[
            ("NOT_FIT", "Not fit for work"),
            ("MAY_BE_FIT", "May be fit for work with adjustments"),
            ("PHASED_RETURN", "Phased return to work"),
            ("AMENDED_DUTIES", "Amended duties"),
            ("WORKPLACE_ADAPTATION", "Workplace adaptation"),
        ],
    )

    # SSP
    ssp_eligible = models.BooleanField(
        default=True,
        help_text="Is the employee eligible for Statutory Sick Pay? (All employees from April 2026.)",
    )
    ssp_weekly_rate_applied = models.DecimalField(
        max_digits=8, decimal_places=2,
        default=SSP_WEEKLY_RATE,
        help_text=f"SSP rate applied (£{SSP_WEEKLY_RATE}/wk from April 2026; or 80% of weekly earnings if below LEL).",
    )
    company_sick_pay_applies = models.BooleanField(
        default=False,
        help_text="Is the employee eligible for enhanced company sick pay above SSP?",
    )
    company_sick_pay_days_remaining = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Remaining company sick pay entitlement days for this leave year.",
    )

    # Return to work
    return_to_work_date = models.DateField(null=True, blank=True)
    return_to_work_interview_done = models.BooleanField(
        default=False,
        help_text="Return-to-work interview completed — recommended ACAS good practice.",
    )
    return_to_work_interview_date = models.DateField(null=True, blank=True)
    phased_return_agreed = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name = "Sick Leave Record"

    def __str__(self):
        return f"{self.employee.full_name} — Sick from {self.start_date}"

    @property
    def calendar_days_absent(self) -> int:
        end = self.end_date or timezone.now().date()
        return (end - self.start_date).days + 1

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Sick leave end date cannot be before start date."})


# ─────────────────────────────────────────────────────────
# WORKING HOURS LOG
# ─────────────────────────────────────────────────────────
class WorkingHoursLog(models.Model):
    """
    Weekly hours log.
    Required for:
      1. ERA 2025 holiday record-keeping obligation (6-year retention, from April 2026).
      2. Working Time Regulations 1998 — 48hr average weekly limit monitoring.
      3. Student Visa compliance — tracking hours Mon–Sun.
      4. NMW compliance cross-check.

    Week runs Monday to Sunday (as per UK visa rules for student monitoring).
    """

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="hours_logs")
    week_start_date = models.DateField(
        help_text="Monday of the working week (weeks run Monday–Sunday for UK visa compliance).",
    )
    monday_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    tuesday_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    wednesday_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    thursday_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    friday_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    saturday_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    sunday_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    overtime_hours = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
        help_text="Additional hours beyond contracted hours (paid or TOIL).",
    )
    on_call_hours = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
        help_text=(
            "On-call hours where the employee is required to be in a specific place "
            "(counts toward Working Time Regulations limit and student visa limits)."
        ),
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("employee", "week_start_date")
        ordering = ["-week_start_date"]
        verbose_name = "Working Hours Log"

    def __str__(self):
        return f"{self.employee.full_name} — week of {self.week_start_date}"

    @property
    def total_hours(self) -> Decimal:
        return (
            self.monday_hours + self.tuesday_hours + self.wednesday_hours
            + self.thursday_hours + self.friday_hours + self.saturday_hours
            + self.sunday_hours
        )

    @property
    def total_hours_including_overtime(self) -> Decimal:
        return self.total_hours + self.overtime_hours + self.on_call_hours

    @property
    def exceeds_48hr_wtr_limit(self) -> bool:
        """Working Time Regulations 1998: 48-hour average limit (opt-out agreements aside)."""
        return self.total_hours_including_overtime > 48

    def clean(self):
        """Validate student visa hour limits."""
        try:
            immigration = self.employee.immigration_status
            if immigration.visa_type == "STUDENT":
                restriction = immigration.student_restrictions
                max_hours = restriction.current_max_hours
                if max_hours is not None:
                    total = float(self.total_hours_including_overtime)
                    if total > max_hours:
                        raise ValidationError(
                            f"Total hours this week ({total:.1f}) exceed the student visa term-time "
                            f"limit of {max_hours} hours (Monday–Sunday). "
                            "Exceeding this limit is a visa violation and may result in Home Office enforcement."
                        )
        except (ImmigrationStatus.DoesNotExist, StudentVisaRestriction.DoesNotExist):
            pass


# ─────────────────────────────────────────────────────────
# DISCIPLINARY RECORD
# ─────────────────────────────────────────────────────────
class DisciplinaryRecord(models.Model):
    """
    Disciplinary action records.
    ACAS Code of Practice on Disciplinary and Grievance Procedures.
    Employees have a statutory right to be accompanied (ERA 1999 s10).
    """

    RECORD_TYPE_CHOICES = [
        ("VERBAL_WARNING", "Verbal Warning"),
        ("WRITTEN_WARNING", "First Written Warning"),
        ("FINAL_WRITTEN_WARNING", "Final Written Warning"),
        ("SUSPENSION_WITH_PAY", "Suspension with Pay (Pending Investigation)"),
        ("SUSPENSION_WITHOUT_PAY", "Suspension without Pay (Post-Hearing)"),
        ("DEMOTION", "Demotion"),
        ("DISMISSAL", "Dismissal (with notice)"),
        ("SUMMARY_DISMISSAL", "Summary Dismissal (Gross Misconduct — no notice)"),
        ("OTHER", "Other Outcome"),
    ]

    STATUS_CHOICES = [
        ("OPEN", "Open"),
        ("INVESTIGATING", "Under Investigation"),
        ("HEARING_SCHEDULED", "Hearing Scheduled"),
        ("APPEAL_PERIOD", "Active — In Appeal Period"),
        ("APPEAL_LODGED", "Appeal Lodged"),
        ("LIVE", "Live (within expiry period)"),
        ("SPENT", "Spent / Expired"),
        ("OVERTURNED", "Overturned on Appeal"),
        ("WITHDRAWN", "Withdrawn"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="disciplinary_records")
    record_type = models.CharField(max_length=30, choices=RECORD_TYPE_CHOICES)
    incident_date = models.DateField(help_text="Date of the alleged misconduct / performance incident.")
    action_date = models.DateField(help_text="Date disciplinary action was formally issued.")
    expiry_date = models.DateField(
        null=True, blank=True,
        help_text="Date the warning expires (typically 6–12 months for warnings; indefinite for dismissal).",
    )
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default="OPEN")

    # Due process (ACAS Code)
    investigation_conducted = models.BooleanField(default=False)
    investigation_date = models.DateField(null=True, blank=True)
    right_to_be_accompanied_advised = models.BooleanField(
        default=True,
        help_text="Employee was informed of their right to be accompanied (ERA 1999 s10).",
    )
    companion_present = models.BooleanField(default=False, help_text="Companion (trade union rep or colleague) attended hearing.")

    reason = models.TextField(help_text="Description of the misconduct / performance concern.")
    outcome = models.TextField(blank=True, help_text="Formal outcome and any conditions imposed.")

    # Appeal
    appeal_deadline = models.DateField(null=True, blank=True)
    appeal_lodged = models.BooleanField(default=False)
    appeal_date = models.DateField(null=True, blank=True)
    appeal_outcome = models.TextField(blank=True)

    employee_acknowledged = models.BooleanField(default=False, help_text="Employee signed / acknowledged the outcome letter.")
    issued_by = models.ForeignKey(
        Employee, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="issued_disciplinary_actions",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-action_date"]

    def __str__(self):
        return f"{self.employee.full_name} — {self.get_record_type_display()} ({self.action_date})"

    @property
    def is_live(self) -> bool:
        if self.expiry_date:
            return self.expiry_date >= timezone.now().date()
        return self.record_type in ("DISMISSAL", "SUMMARY_DISMISSAL")


# ─────────────────────────────────────────────────────────
# GRIEVANCE RECORD
# ─────────────────────────────────────────────────────────
class GrievanceRecord(models.Model):
    """
    Employee grievance record.
    ERA 2025 enhancements:
      • Sexual harassment disclosures are now protected whistleblowing disclosures (from April 2026).
      • Employers must take 'all reasonable steps' to prevent sexual harassment.
      • NDAs cannot prevent reporting of sexual harassment (from October 2025).
    """

    STATUS_CHOICES = [
        ("RAISED", "Raised — Pending Acknowledgement"),
        ("INVESTIGATING", "Under Investigation"),
        ("HEARING_SCHEDULED", "Hearing Scheduled"),
        ("RESOLVED", "Resolved"),
        ("APPEAL_LODGED", "Appeal Lodged"),
        ("CLOSED", "Closed"),
        ("REFERRED_EXTERNALLY", "Referred to External Body (e.g. ACAS, Employment Tribunal)"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="grievances")
    date_raised = models.DateField()
    subject = models.CharField(max_length=250)
    description = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="RAISED")

    # Flags for legal categorisation
    involves_harassment = models.BooleanField(
        default=False,
        help_text="Does this grievance involve any form of harassment (including third-party, per ERA 2025)?",
    )
    involves_sexual_harassment = models.BooleanField(
        default=False,
        help_text=(
            "Involves sexual harassment? From April 2026 this qualifies as a protected whistleblowing disclosure "
            "(ERA 2025). Employer must have taken 'all reasonable steps' to prevent it."
        ),
    )
    involves_discrimination = models.BooleanField(
        default=False,
        help_text="Involves discrimination under the Equality Act 2010 (any protected characteristic)?",
    )
    is_whistleblowing = models.BooleanField(
        default=False,
        help_text="Is this a qualifying protected disclosure under the Public Interest Disclosure Act 1998?",
    )
    involves_pay_dispute = models.BooleanField(default=False)

    right_to_be_accompanied_advised = models.BooleanField(default=True)
    companion_present = models.BooleanField(default=False)

    resolution = models.TextField(blank=True)
    resolved_date = models.DateField(null=True, blank=True)
    appeal_lodged = models.BooleanField(default=False)
    appeal_outcome = models.TextField(blank=True)

    handled_by = models.ForeignKey(
        Employee, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="handled_grievances",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_raised"]

    def __str__(self):
        return f"{self.employee.full_name} — Grievance [{self.date_raised}]: {self.subject}"


# ─────────────────────────────────────────────────────────
# TRAINING RECORD
# ─────────────────────────────────────────────────────────
class TrainingRecord(models.Model):
    """
    Employee training and certification record.
    ERA 2025: employers must take 'all reasonable steps' to prevent sexual harassment —
    documented harassment-prevention training is a key part of demonstrating compliance.
    """

    TRAINING_TYPE_CHOICES = [
        ("INDUCTION", "Induction / Onboarding"),
        ("MANDATORY", "Mandatory Compliance Training"),
        ("HEALTH_SAFETY", "Health & Safety"),
        ("FIRE_SAFETY", "Fire Safety"),
        ("FOOD_HYGIENE", "Food Hygiene"),
        ("DATA_PROTECTION", "Data Protection / GDPR / UK GDPR"),
        ("EQUALITY_DIVERSITY", "Equality, Diversity & Inclusion (Equality Act 2010)"),
        ("HARASSMENT_PREVENTION", "Prevention of Harassment & Bullying (ERA 2025 duty)"),
        ("SAFEGUARDING", "Safeguarding"),
        ("MANUAL_HANDLING", "Manual Handling"),
        ("FIRST_AID", "First Aid"),
        ("COSHH", "COSHH (Hazardous Substances)"),
        ("PROFESSIONAL_DEV", "Professional Development"),
        ("TECHNICAL", "Technical / Role-specific Training"),
        ("LEADERSHIP", "Leadership & Management"),
        ("APPRENTICESHIP", "Apprenticeship On-programme Training"),
        ("LANGUAGE", "English Language Training"),
        ("OTHER", "Other"),
    ]

    STATUS_CHOICES = [
        ("ENROLLED", "Enrolled"),
        ("IN_PROGRESS", "In Progress"),
        ("COMPLETED", "Completed"),
        ("FAILED", "Failed"),
        ("EXPIRED", "Certification Expired"),
        ("CANCELLED", "Cancelled"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="training_records")
    training_type = models.CharField(max_length=30, choices=TRAINING_TYPE_CHOICES)
    title = models.CharField(max_length=255)
    provider = models.CharField(max_length=200, blank=True)
    start_date = models.DateField()
    completion_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ENROLLED")
    certificate_reference = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    cost_gbp = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    mandatory = models.BooleanField(
        default=False,
        help_text="Is this training mandatory for the employee's role?",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.employee.full_name} — {self.title} [{self.get_status_display()}]"

    @property
    def is_certification_expired(self) -> bool:
        if self.expiry_date:
            return self.expiry_date < timezone.now().date()
        return False


# ─────────────────────────────────────────────────────────
# PERFORMANCE REVIEW
# ─────────────────────────────────────────────────────────
class PerformanceReview(models.Model):
    """
    Formal performance review record.
    Probation reviews are critical: ERA 2025 extends unfair dismissal to day-one from Jan 2027.
    A structured probation review process provides important evidence of legitimate dismissal reasons.
    """

    REVIEW_TYPE_CHOICES = [
        ("PROBATION_MID", "Mid-Probation Review"),
        ("PROBATION_FINAL", "Final Probation Review"),
        ("ANNUAL", "Annual Performance Review"),
        ("MID_YEAR", "Mid-year / Six-month Review"),
        ("ONE_TO_ONE", "Informal 1-to-1"),
        ("PIP_KICKOFF", "Performance Improvement Plan (PIP) — Initial"),
        ("PIP_REVIEW", "Performance Improvement Plan (PIP) — Progress Review"),
        ("360", "360° Feedback Review"),
    ]

    RATING_CHOICES = [
        (1, "1 — Unsatisfactory"),
        (2, "2 — Needs Improvement"),
        (3, "3 — Meets Expectations"),
        (4, "4 — Exceeds Expectations"),
        (5, "5 — Outstanding"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="performance_reviews")
    review_type = models.CharField(max_length=20, choices=REVIEW_TYPE_CHOICES)
    review_date = models.DateField()
    review_period_start = models.DateField()
    review_period_end = models.DateField()
    overall_rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES, null=True, blank=True)
    achievements = models.TextField(blank=True)
    areas_for_development = models.TextField(blank=True)
    objectives_agreed = models.TextField(blank=True, help_text="SMART objectives agreed for next period.")
    probation_passed = models.BooleanField(
        null=True, blank=True,
        help_text="For probation reviews: Pass (True), Extend (None), Fail (False).",
    )
    probation_extended_weeks = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="If probation extended, by how many weeks?",
    )
    reviewed_by = models.ForeignKey(
        Employee, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="conducted_reviews",
    )
    employee_acknowledged = models.BooleanField(default=False)
    employee_comments = models.TextField(blank=True)
    next_review_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-review_date"]

    def __str__(self):
        return f"{self.employee.full_name} — {self.get_review_type_display()} ({self.review_date})"


# ─────────────────────────────────────────────────────────
# REDUNDANCY RECORD
# ─────────────────────────────────────────────────────────
class RedundancyRecord(models.Model):
    """
    Redundancy process and statutory redundancy pay record.

    UK rules:
      • Statutory redundancy pay: based on age, weekly pay (capped £751/wk from April 2026),
        and complete years of service (max 20).
      • Half week's pay per complete year under 22.
      • One week's pay per complete year aged 22–40.
      • 1.5 weeks' pay per complete year aged 41+.
      • Collective redundancy (20+ dismissals in 90 days): min 30–45 day consultation.
      • From April 2026: maximum protective award increases to 180 days' pay.
      • ERA 2025: enhanced protection for pregnant workers and those returning from maternity leave.
    """

    REDUNDANCY_TYPE_CHOICES = [
        ("VOLUNTARY", "Voluntary Redundancy"),
        ("COMPULSORY", "Compulsory Redundancy"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="redundancy_records")
    redundancy_type = models.CharField(max_length=20, choices=REDUNDANCY_TYPE_CHOICES)
    at_risk_notification_date = models.DateField(help_text="Date employee was formally placed at risk of redundancy.")
    consultation_start_date = models.DateField()
    consultation_end_date = models.DateField(null=True, blank=True)
    effective_redundancy_date = models.DateField(null=True, blank=True)

    # Pay calculations
    complete_years_service = models.PositiveSmallIntegerField(
        validators=[MaxValueValidator(20)],
        help_text="Complete years of service at effective redundancy date (max 20 counted).",
    )
    weekly_pay_for_calculation = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text=f"Weekly pay used in calculation, capped at £{REDUNDANCY_WEEKLY_PAY_CAP} from April 2026.",
    )
    statutory_redundancy_pay = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
    )
    enhanced_redundancy_pay = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Any additional company redundancy pay above the statutory amount.",
    )
    notice_pay = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    payment_in_lieu_of_notice = models.BooleanField(default=False)

    # Process
    selection_criteria_applied = models.TextField(blank=True)
    alternatives_considered = models.TextField(blank=True, help_text="Suitable alternative roles considered and offered.")
    employee_pregnant_or_maternity = models.BooleanField(
        default=False,
        help_text=(
            "Is the employee pregnant or recently returned from maternity leave? "
            "ERA 2025 strengthens their protection — seek HR/legal advice before proceeding."
        ),
    )
    collective_consultation_required = models.BooleanField(
        default=False,
        help_text="20+ redundancies in 90 days at one establishment — min 30-45 day consultation required.",
    )
    hr_1_form_submitted = models.BooleanField(
        default=False,
        help_text="HR1 advance notification form submitted to Insolvency Service (required for 20+ redundancies).",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-at_risk_notification_date"]

    def __str__(self):
        return f"{self.employee.full_name} — {self.get_redundancy_type_display()}"

    def calculate_statutory_redundancy_pay(self) -> Decimal:
        """
        Calculate statutory redundancy pay per UK formula (April 2026 cap: £751/week).
        Age is evaluated at the effective redundancy date.
        """
        capped_pay = min(self.weekly_pay_for_calculation, REDUNDANCY_WEEKLY_PAY_CAP)
        effective_date = self.effective_redundancy_date or timezone.now().date()
        age_at_redundancy = (
            effective_date.year - self.employee.date_of_birth.year
            - (
                (effective_date.month, effective_date.day)
                < (self.employee.date_of_birth.month, self.employee.date_of_birth.day)
            )
        )
        total = Decimal("0.00")
        years = min(int(self.complete_years_service), 20)

        for year_back in range(years):
            age_in_that_year = age_at_redundancy - year_back
            if age_in_that_year >= 41:
                multiplier = Decimal("1.5")
            elif age_in_that_year >= 22:
                multiplier = Decimal("1.0")
            else:
                multiplier = Decimal("0.5")
            total += multiplier * capped_pay

        return total.quantize(Decimal("0.01"))