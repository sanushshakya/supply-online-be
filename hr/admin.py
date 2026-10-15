"""
HR Admin Configuration
======================
Provides a comprehensive Django admin interface for the UK HR system.
All models are registered with appropriate list displays, search fields,
filters, inlines and custom actions.
"""

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.db.models import Q

from .models import (
    Department,
    JobRole,
    Employee,
    EmergencyContact,
    RightToWork,
    ImmigrationStatus,
    StudentVisaRestriction,
    Contract,
    AnnualLeaveEntitlement,
    LeaveRequest,
    SickLeaveRecord,
    WorkingHoursLog,
    DisciplinaryRecord,
    GrievanceRecord,
    TrainingRecord,
    PerformanceReview,
    RedundancyRecord,
    SSP_WEEKLY_RATE,
    STATUTORY_ANNUAL_LEAVE_DAYS,
)


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────
def _status_badge(colour: str, label: str) -> str:
    return format_html(
        '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px">{}</span>',
        colour,
        label,
    )


# ─────────────────────────────────────────────────────────
# DEPARTMENT
# ─────────────────────────────────────────────────────────
@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "manager", "is_active", "employee_count")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "cost_centre")
    list_select_related = ("manager",)

    def employee_count(self, obj):
        return obj.employees.filter(employment_status__in=["ACTIVE", "PROBATION"]).count()

    employee_count.short_description = "Active Employees"


# ─────────────────────────────────────────────────────────
# JOB ROLE
# ─────────────────────────────────────────────────────────
@admin.register(JobRole)
class JobRoleAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "rqf_level", "soc_code", "is_visa_sponsorable", "is_shortage_occupation", "minimum_annual_salary", "is_active")
    list_filter = ("department", "is_visa_sponsorable", "is_shortage_occupation", "rqf_level", "is_active")
    search_fields = ("title", "soc_code", "description")


# ─────────────────────────────────────────────────────────
# EMPLOYEE — INLINES
# ─────────────────────────────────────────────────────────
class EmergencyContactInline(admin.TabularInline):
    model = EmergencyContact
    extra = 1
    fields = ("full_name", "relationship", "phone_primary", "phone_secondary", "is_primary")


class RightToWorkInline(admin.TabularInline):
    model = RightToWork
    extra = 0
    fields = ("check_date", "check_type", "document_type", "document_expiry_date", "follow_up_check_due", "document_copy_retained")
    readonly_fields = ("check_date",)
    ordering = ("-check_date",)
    show_change_link = True


class ContractInline(admin.StackedInline):
    model = Contract
    extra = 0
    fields = (
        ("contract_type", "is_current"),
        ("start_date", "end_date"),
        ("contracted_hours_per_week", "pay_frequency"),
        ("annual_salary", "hourly_rate"),
        ("employee_notice_period", "employee_notice_unit"),
        ("employer_notice_period", "employer_notice_unit"),
        ("probation_period_months",),
        ("remote_arrangement", "work_location"),
    )
    show_change_link = True


class ImmigrationStatusInline(admin.StackedInline):
    model = ImmigrationStatus
    extra = 0
    fields = (
        ("visa_type", "work_restrictions"),
        ("visa_start_date", "visa_expiry_date"),
        ("is_employer_sponsored", "certificate_of_sponsorship_number"),
        ("country_of_nationality", "passport_number", "passport_expiry"),
        ("has_evisa", "no_recourse_to_public_funds"),
        "notes",
    )
    show_change_link = True


class PerformanceReviewInline(admin.TabularInline):
    model = PerformanceReview
    extra = 0
    fk_name = "employee"
    fields = ("review_type", "review_date", "overall_rating", "probation_passed", "reviewed_by")
    readonly_fields = ("review_date",)
    ordering = ("-review_date",)
    show_change_link = True


# ─────────────────────────────────────────────────────────
# EMPLOYEE
# ─────────────────────────────────────────────────────────
@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        "employee_number",
        "full_name_display",
        "department",
        "job_role",
        "employment_type",
        "status_badge",
        "start_date",
        "nationality",
        "rtw_status_badge",
        "nmw_rate_display",
    )
    list_filter = (
        "employment_status",
        "employment_type",
        "department",
        "nationality",
        "gender",
        "pension_enrolled",
        "disability_declared",
    )
    search_fields = (
        "employee_number",
        "first_name",
        "last_name",
        "preferred_name",
        "personal_email",
        "work_email",
        "national_insurance_number",
    )
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "start_date"
    list_select_related = ("department", "job_role", "manager")
    save_on_top = True

    fieldsets = (
        (_("Identity"), {
            "fields": (
                ("employee_number",),
                ("first_name", "middle_names", "last_name"),
                ("preferred_name", "date_of_birth", "gender"),
                ("photo",),
            ),
        }),
        (_("Equality Monitoring (Equality Act 2010 — restricted access)"), {
            "classes": ("collapse",),
            "description": "Special-category data under UK GDPR. Access restricted to authorised HR personnel.",
            "fields": (
                "ethnicity",
                ("disability_declared", "disability_details"),
            ),
        }),
        (_("Contact Information"), {
            "fields": (
                ("personal_email", "work_email", "phone_number"),
                "address_line1",
                "address_line2",
                ("city", "county", "postcode", "country"),
            ),
        }),
        (_("Employment"), {
            "fields": (
                ("job_role", "department"),
                ("manager",),
                ("employment_type", "employment_status"),
                ("start_date", "end_date"),
                ("probation_end_date",),
            ),
        }),
        (_("UK Payroll & HMRC"), {
            "fields": (
                ("national_insurance_number", "tax_code"),
                ("student_loan_plan",),
                ("pension_enrolled", "pension_opt_out", "pension_opt_out_date"),
                ("p45_received",),
            ),
        }),
        (_("Immigration / Nationality"), {
            "fields": (("nationality",),),
        }),
        (_("Notes & Metadata"), {
            "classes": ("collapse",),
            "fields": ("notes", ("created_at", "updated_at")),
        }),
    )

    inlines = [
        EmergencyContactInline,
        RightToWorkInline,
        ImmigrationStatusInline,
        ContractInline,
        PerformanceReviewInline,
    ]

    # ── Custom display columns ────────────────────────────
    def full_name_display(self, obj):
        name = obj.full_name
        if obj.preferred_name:
            name += f' ({obj.preferred_name})'
        return name

    full_name_display.short_description = "Name"

    def status_badge(self, obj):
        colour_map = {
            "ACTIVE": "#2e7d32",
            "PROBATION": "#f57f17",
            "ON_LEAVE": "#0277bd",
            "SUSPENDED": "#c62828",
            "NOTICE_PERIOD": "#6a1b9a",
            "RESIGNED": "#37474f",
            "REDUNDANT": "#37474f",
            "DISMISSED": "#b71c1c",
            "RETIRED": "#546e7a",
            "DECEASED": "#212121",
        }
        colour = colour_map.get(obj.employment_status, "#757575")
        return _status_badge(colour, obj.get_employment_status_display())

    status_badge.short_description = "Status"

    def rtw_status_badge(self, obj):
        """Show latest RTW check status."""
        latest = obj.right_to_work_checks.order_by("-check_date").first()
        if not latest:
            return _status_badge("#c62828", "⚠ No RTW Check")
        if latest.is_permission_expired:
            return _status_badge("#c62828", "⚠ EXPIRED")
        days = latest.days_until_expiry
        if days is not None and days <= 28:
            return _status_badge("#f57f17", f"⚠ Expires {days}d")
        return _status_badge("#2e7d32", "✓ Valid")

    rtw_status_badge.short_description = "RTW"

    def nmw_rate_display(self, obj):
        return f"£{obj.applicable_nmw_rate}/hr"

    nmw_rate_display.short_description = "Min Wage"

    # ── Custom Actions ────────────────────────────────────
    actions = [
        "mark_as_active",
        "flag_for_rtw_review",
    ]

    @admin.action(description="Mark selected employees as Active")
    def mark_as_active(self, request, queryset):
        updated = queryset.update(employment_status="ACTIVE")
        self.message_user(request, f"{updated} employee(s) marked as Active.")

    @admin.action(description="Flag selected employees for Right to Work review")
    def flag_for_rtw_review(self, request, queryset):
        count = 0
        for emp in queryset:
            latest_rtw = emp.right_to_work_checks.order_by("-check_date").first()
            if not latest_rtw or latest_rtw.is_permission_expired:
                count += 1
        self.message_user(
            request,
            f"{count} of the selected employees have expired or missing RTW checks. "
            "Please review the RTW Check records.",
        )


# ─────────────────────────────────────────────────────────
# RIGHT TO WORK
# ─────────────────────────────────────────────────────────
@admin.register(RightToWork)
class RightToWorkAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "check_date",
        "check_type",
        "document_type",
        "document_list",
        "document_expiry_date",
        "follow_up_check_due",
        "expiry_status_badge",
        "document_copy_retained",
    )
    list_filter = ("check_type", "document_list", "document_type", "document_copy_retained")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_number", "share_code")
    date_hierarchy = "check_date"
    readonly_fields = ("created_at",)
    list_select_related = ("employee",)

    fieldsets = (
        (_("Employee"), {"fields": ("employee",)}),
        (_("Check Details"), {
            "fields": (
                ("check_type", "check_date"),
                ("document_list", "document_type"),
            ),
        }),
        (_("eVisa / Share Code"), {
            "description": "Complete only for online share code checks (non-British/Irish with eVisa).",
            "fields": (("share_code", "date_of_birth_used_for_check"),),
        }),
        (_("Validity & Follow-up"), {
            "fields": (
                ("document_expiry_date", "follow_up_check_due"),
                ("permitted_work_type",),
            ),
        }),
        (_("Compliance Record"), {
            "description": (
                "Home Office requirement: retain record for duration of employment + 2 years. "
                "Employers who fail to keep dated copies have no statutory excuse."
            ),
            "fields": (("checked_by", "document_copy_retained"), "notes"),
        }),
        (_("Metadata"), {"classes": ("collapse",), "fields": ("created_at",)}),
    )

    def expiry_status_badge(self, obj):
        if obj.document_expiry_date is None:
            return _status_badge("#2e7d32", "Permanent")
        if obj.is_permission_expired:
            return _status_badge("#c62828", "EXPIRED")
        days = obj.days_until_expiry
        if days is not None and days <= 28:
            return _status_badge("#f57f17", f"Expires in {days} days")
        return _status_badge("#2e7d32", f"Valid ({days}d)")

    expiry_status_badge.short_description = "Expiry Status"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("employee")


# ─────────────────────────────────────────────────────────
# IMMIGRATION STATUS
# ─────────────────────────────────────────────────────────
class StudentVisaRestrictionInline(admin.StackedInline):
    model = StudentVisaRestriction
    extra = 0
    fields = (
        ("study_level", "institution_name"),
        ("cas_number", "institution_is_licensed_sponsor"),
        ("course_start_date", "course_end_date"),
        ("term_time_max_hours_per_week",),
        ("is_currently_in_vacation", "vacation_evidence_on_file"),
        ("studies_completed", "completion_evidence_date"),
        "notes",
    )


@admin.register(ImmigrationStatus)
class ImmigrationStatusAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "visa_type",
        "country_of_nationality",
        "visa_expiry_date",
        "visa_expiry_badge",
        "is_employer_sponsored",
        "work_restrictions",
        "has_evisa",
        "no_recourse_to_public_funds",
    )
    list_filter = (
        "visa_type",
        "work_restrictions",
        "is_employer_sponsored",
        "has_evisa",
        "no_recourse_to_public_funds",
    )
    search_fields = (
        "employee__first_name",
        "employee__last_name",
        "employee__employee_number",
        "country_of_nationality",
        "visa_reference_number",
        "certificate_of_sponsorship_number",
        "passport_number",
    )
    list_select_related = ("employee",)
    readonly_fields = ("created_at", "updated_at")

    inlines = [StudentVisaRestrictionInline]

    fieldsets = (
        (_("Employee"), {"fields": ("employee",)}),
        (_("Visa / Immigration Status"), {
            "fields": (
                ("visa_type", "work_restrictions"),
                ("visa_reference_number",),
                ("visa_start_date", "visa_expiry_date"),
                ("no_recourse_to_public_funds",),
            ),
        }),
        (_("Sponsorship (Skilled Worker / Health & Care)"), {
            "classes": ("collapse",),
            "description": "Complete this section if the employer is sponsoring the worker under the Skilled Worker route.",
            "fields": (
                ("is_employer_sponsored",),
                ("certificate_of_sponsorship_number", "sponsor_licence_number", "soc_code_on_cos"),
                ("immigration_skills_charge_paid",),
            ),
        }),
        (_("Travel Document"), {
            "fields": (
                ("country_of_nationality",),
                ("passport_number", "passport_expiry"),
            ),
        }),
        (_("eVisa"), {
            "description": "Since 31 Oct 2024, BRPs are no longer issued. eVisa is the primary digital status record.",
            "fields": (("has_evisa", "ukvi_account_reference"),),
        }),
        (_("Notes & Metadata"), {"classes": ("collapse",), "fields": ("notes", ("created_at", "updated_at"))}),
    )

    def visa_expiry_badge(self, obj):
        if obj.visa_expiry_date is None:
            return _status_badge("#2e7d32", "No expiry")
        if obj.is_visa_expired:
            return _status_badge("#c62828", "EXPIRED")
        days = obj.days_until_visa_expiry
        if days is not None and days <= 60:
            return _status_badge("#f57f17", f"{days} days left")
        return _status_badge("#2e7d32", f"Valid ({days}d)")

    visa_expiry_badge.short_description = "Visa Status"


# ─────────────────────────────────────────────────────────
# CONTRACT
# ─────────────────────────────────────────────────────────
@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "contract_type",
        "is_current",
        "start_date",
        "end_date",
        "contracted_hours_per_week",
        "annual_salary",
        "hourly_rate",
        "pay_frequency",
        "nmw_compliant_badge",
    )
    list_filter = ("contract_type", "is_current", "pay_frequency", "remote_arrangement")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_number")
    date_hierarchy = "start_date"
    list_select_related = ("employee",)

    def nmw_compliant_badge(self, obj):
        rate = obj.effective_hourly_rate
        if rate is None:
            return _status_badge("#757575", "N/A")
        nmw = float(obj.employee.applicable_nmw_rate)
        if rate >= nmw:
            return _status_badge("#2e7d32", f"✓ £{rate:.2f}/hr")
        return _status_badge("#c62828", f"⚠ BELOW NMW £{rate:.2f}/hr (min £{nmw:.2f})")

    nmw_compliant_badge.short_description = "NMW Compliance"


# ─────────────────────────────────────────────────────────
# ANNUAL LEAVE
# ─────────────────────────────────────────────────────────
@admin.register(AnnualLeaveEntitlement)
class AnnualLeaveEntitlementAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "leave_year_start",
        "leave_year_end",
        "total_entitlement_days",
        "carried_over_days",
        "days_taken",
        "days_approved_pending",
        "days_remaining_display",
        "bank_holidays_included",
    )
    list_filter = ("bank_holidays_included",)
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_number")
    list_select_related = ("employee",)

    def days_remaining_display(self, obj):
        remaining = obj.days_remaining
        if remaining < 0:
            return _status_badge("#c62828", f"{remaining} (OVERBOOKED)")
        if remaining <= 2:
            return _status_badge("#f57f17", str(remaining))
        return _status_badge("#2e7d32", str(remaining))

    days_remaining_display.short_description = "Days Remaining"


# ─────────────────────────────────────────────────────────
# LEAVE REQUESTS
# ─────────────────────────────────────────────────────────
@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "leave_type",
        "start_date",
        "end_date",
        "number_of_days",
        "status",
        "approved_by",
        "approved_at",
    )
    list_filter = ("leave_type", "status")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_number")
    date_hierarchy = "start_date"
    list_select_related = ("employee", "approved_by")
    readonly_fields = ("approved_at", "created_at", "updated_at")

    actions = ["approve_leave", "reject_leave"]

    @admin.action(description="Approve selected leave requests")
    def approve_leave(self, request, queryset):
        updated = queryset.filter(status="PENDING").update(
            status="APPROVED",
            approved_at=timezone.now(),
        )
        self.message_user(request, f"{updated} leave request(s) approved.")

    @admin.action(description="Reject selected leave requests")
    def reject_leave(self, request, queryset):
        updated = queryset.filter(status="PENDING").update(status="REJECTED")
        self.message_user(request, f"{updated} leave request(s) rejected.")


# ─────────────────────────────────────────────────────────
# SICK LEAVE
# ─────────────────────────────────────────────────────────
@admin.register(SickLeaveRecord)
class SickLeaveRecordAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "start_date",
        "end_date",
        "calendar_days_display",
        "ssp_eligible",
        "ssp_weekly_rate_applied",
        "fit_note_received",
        "return_to_work_interview_done",
    )
    list_filter = ("ssp_eligible", "self_certified", "fit_note_received", "return_to_work_interview_done", "company_sick_pay_applies")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_number")
    date_hierarchy = "start_date"
    list_select_related = ("employee",)
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (_("Employee & Dates"), {
            "fields": (
                "employee",
                ("start_date", "end_date"),
                "reason",
            ),
        }),
        (_("Medical Certification"), {
            "description": (
                "Employees may self-certify for the first 7 consecutive calendar days. "
                "A fit note (Med 3) is required for absences exceeding 7 days."
            ),
            "fields": (
                ("self_certified", "fit_note_received"),
                ("fit_note_date", "fit_note_expiry"),
                ("fit_note_recommendation",),
            ),
        }),
        (_("Statutory Sick Pay (SSP)"), {
            "description": (
                f"From 6 April 2026: SSP is payable from day ONE at £{SSP_WEEKLY_RATE}/week "
                "(or 80% of weekly earnings if below the Lower Earnings Limit of £129/week). "
                "All employees are now eligible — the Lower Earnings Limit barrier has been removed."
            ),
            "fields": (
                ("ssp_eligible", "ssp_weekly_rate_applied"),
                ("company_sick_pay_applies", "company_sick_pay_days_remaining"),
            ),
        }),
        (_("Return to Work"), {
            "fields": (
                ("return_to_work_date",),
                ("return_to_work_interview_done", "return_to_work_interview_date"),
                ("phased_return_agreed",),
            ),
        }),
        (_("Notes"), {"classes": ("collapse",), "fields": ("notes", ("created_at", "updated_at"))}),
    )

    def calendar_days_display(self, obj):
        return obj.calendar_days_absent

    calendar_days_display.short_description = "Days Absent"


# ─────────────────────────────────────────────────────────
# WORKING HOURS LOG
# ─────────────────────────────────────────────────────────
@admin.register(WorkingHoursLog)
class WorkingHoursLogAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "week_start_date",
        "total_hours_display",
        "overtime_hours",
        "on_call_hours",
        "student_visa_compliance_badge",
        "wtr_48hr_badge",
    )
    list_filter = ("week_start_date",)
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_number")
    date_hierarchy = "week_start_date"
    list_select_related = ("employee",)

    def total_hours_display(self, obj):
        total = float(obj.total_hours_including_overtime)
        return f"{total:.1f} hrs"

    total_hours_display.short_description = "Total Hours"

    def wtr_48hr_badge(self, obj):
        total = float(obj.total_hours_including_overtime)
        if total > 48:
            return _status_badge("#f57f17", f"⚠ {total:.1f}h > 48h WTR")
        return _status_badge("#2e7d32", "✓ WTR OK")

    wtr_48hr_badge.short_description = "WTR Limit"

    def student_visa_compliance_badge(self, obj):
        try:
            immigration = obj.employee.immigration_status
            if immigration.visa_type != "STUDENT":
                return "—"
            restriction = immigration.student_restrictions
            max_hours = restriction.current_max_hours
            if max_hours is None:
                return _status_badge("#2e7d32", "Full-time OK")
            total = float(obj.total_hours_including_overtime)
            if total > max_hours:
                return _status_badge("#c62828", f"⚠ {total:.1f}h > {max_hours}h VISA LIMIT")
            return _status_badge("#2e7d32", f"✓ {total:.1f}/{max_hours}h")
        except (ImmigrationStatus.DoesNotExist, StudentVisaRestriction.DoesNotExist):
            return "—"

    student_visa_compliance_badge.short_description = "Student Visa Hours"


# ─────────────────────────────────────────────────────────
# DISCIPLINARY
# ─────────────────────────────────────────────────────────
@admin.register(DisciplinaryRecord)
class DisciplinaryRecordAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "record_type",
        "incident_date",
        "action_date",
        "expiry_date",
        "status",
        "live_badge",
        "investigation_conducted",
        "appeal_lodged",
    )
    list_filter = ("record_type", "status", "investigation_conducted", "appeal_lodged")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_number", "reason")
    date_hierarchy = "action_date"
    list_select_related = ("employee", "issued_by")
    readonly_fields = ("created_at", "updated_at")

    def live_badge(self, obj):
        if obj.is_live:
            return _status_badge("#c62828", "Live")
        return _status_badge("#2e7d32", "Spent")

    live_badge.short_description = "Warning Status"


# ─────────────────────────────────────────────────────────
# GRIEVANCE
# ─────────────────────────────────────────────────────────
@admin.register(GrievanceRecord)
class GrievanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "date_raised",
        "subject",
        "status",
        "involves_harassment",
        "involves_sexual_harassment",
        "is_whistleblowing",
        "involves_discrimination",
        "resolved_date",
    )
    list_filter = (
        "status",
        "involves_harassment",
        "involves_sexual_harassment",
        "is_whistleblowing",
        "involves_discrimination",
        "involves_pay_dispute",
    )
    search_fields = ("employee__first_name", "employee__last_name", "subject", "description")
    date_hierarchy = "date_raised"
    list_select_related = ("employee", "handled_by")
    readonly_fields = ("created_at", "updated_at")


# ─────────────────────────────────────────────────────────
# TRAINING
# ─────────────────────────────────────────────────────────
@admin.register(TrainingRecord)
class TrainingRecordAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "training_type",
        "title",
        "start_date",
        "completion_date",
        "status",
        "expiry_date",
        "expiry_badge",
        "mandatory",
        "cost_gbp",
    )
    list_filter = ("training_type", "status", "mandatory")
    search_fields = ("employee__first_name", "employee__last_name", "title", "provider")
    date_hierarchy = "start_date"
    list_select_related = ("employee",)

    actions = ["mark_completed"]

    def expiry_badge(self, obj):
        if not obj.expiry_date:
            return "—"
        if obj.is_certification_expired:
            return _status_badge("#c62828", "EXPIRED")
        days = (obj.expiry_date - timezone.now().date()).days
        if days <= 30:
            return _status_badge("#f57f17", f"Expires {days}d")
        return _status_badge("#2e7d32", "Valid")

    expiry_badge.short_description = "Cert. Expiry"

    @admin.action(description="Mark selected training records as Completed")
    def mark_completed(self, request, queryset):
        updated = queryset.update(status="COMPLETED", completion_date=timezone.now().date())
        self.message_user(request, f"{updated} training record(s) marked as Completed.")


# ─────────────────────────────────────────────────────────
# PERFORMANCE REVIEW
# ─────────────────────────────────────────────────────────
@admin.register(PerformanceReview)
class PerformanceReviewAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "review_type",
        "review_date",
        "overall_rating",
        "probation_passed",
        "reviewed_by",
        "employee_acknowledged",
        "next_review_date",
    )
    list_filter = ("review_type", "overall_rating", "probation_passed", "employee_acknowledged")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_number")
    date_hierarchy = "review_date"
    list_select_related = ("employee", "reviewed_by")
    readonly_fields = ("created_at", "updated_at")


# ─────────────────────────────────────────────────────────
# REDUNDANCY
# ─────────────────────────────────────────────────────────
@admin.register(RedundancyRecord)
class RedundancyRecordAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "redundancy_type",
        "at_risk_notification_date",
        "effective_redundancy_date",
        "complete_years_service",
        "statutory_redundancy_pay",
        "collective_consultation_required",
        "hr_1_form_submitted",
        "employee_pregnant_or_maternity",
    )
    list_filter = ("redundancy_type", "collective_consultation_required", "employee_pregnant_or_maternity", "hr_1_form_submitted")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_number")
    list_select_related = ("employee",)
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (_("Employee"), {"fields": ("employee",)}),
        (_("Redundancy Type & Timeline"), {
            "fields": (
                ("redundancy_type",),
                ("at_risk_notification_date",),
                ("consultation_start_date", "consultation_end_date"),
                ("effective_redundancy_date",),
            ),
        }),
        (_("Statutory Redundancy Pay Calculation"), {
            "description": (
                "Statutory formula (April 2026 weekly pay cap: £751): "
                "0.5 week × years under 22 | 1 week × years 22–40 | 1.5 weeks × years 41+. "
                "Max 20 years counted. Employer should use the calculate_statutory_redundancy_pay() method "
                "and then store the result in the field below."
            ),
            "fields": (
                ("complete_years_service", "weekly_pay_for_calculation"),
                ("statutory_redundancy_pay", "enhanced_redundancy_pay"),
                ("notice_pay", "payment_in_lieu_of_notice"),
            ),
        }),
        (_("Process"), {
            "fields": (
                ("selection_criteria_applied",),
                ("alternatives_considered",),
                ("employee_pregnant_or_maternity",),
                ("collective_consultation_required", "hr_1_form_submitted"),
            ),
        }),
        (_("Notes"), {"classes": ("collapse",), "fields": ("notes", ("created_at", "updated_at"))}),
    )