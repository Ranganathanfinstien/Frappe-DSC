"""
Certificate Expiry Notifications — daily scheduled task.

Checks all active DSC Profiles and sends warnings when certificates
are approaching expiry (at configured day thresholds: 60, 30, 7 days).
"""

import frappe
from frappe.utils import add_days, getdate, now_datetime


def notify_upcoming_expiries():
	"""Daily job: check all active DSC Profiles for upcoming certificate expiry."""
	settings = frappe.get_single("DSC Settings")
	if not settings.enable_expiry_warnings:
		return

	warning_days = [row.days for row in settings.expiry_warning_days]
	if not warning_days:
		return

	today = getdate(now_datetime())

	profiles = frappe.get_all(
		"DSC Profile",
		filters={"is_active": 1, "certificate_not_after": ["is", "set"]},
		fields=["name", "profile_name", "certificate_common_name", "certificate_not_after"],
	)

	for profile in profiles:
		expiry_date = getdate(profile.certificate_not_after)
		days_until_expiry = (expiry_date - today).days

		if days_until_expiry in warning_days:
			send_expiry_warning(profile, days_until_expiry)


def send_expiry_warning(profile, days_remaining):
	"""Send certificate expiry warning to DSC Administrators."""
	admins = frappe.get_all(
		"Has Role",
		filters={"role": "DSC Administrator", "parenttype": "User"},
		fields=["parent"],
	)

	for admin in admins:
		frappe.sendmail(
			recipients=[admin.parent],
			subject=f"DSC Certificate Expiring in {days_remaining} Days — {profile.profile_name}",
			message=(
				f"The certificate for DSC Profile <b>{profile.profile_name}</b> "
				f"({profile.certificate_common_name}) will expire in "
				f"<b>{days_remaining} days</b> on {profile.certificate_not_after}.<br><br>"
				f"Please arrange for certificate renewal."
			),
		)
