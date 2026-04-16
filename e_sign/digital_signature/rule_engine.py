"""
Rules Engine — evaluates DSC Rules against document events.

This module is owned by Ranga. These are stub functions so that
hooks.py doc_events don't crash before implementation.
"""

import frappe


def evaluate_on_submit(doc, method):
	"""Called on every DocType submit. Checks if any DSC Rule matches."""
	pass


def evaluate_on_update(doc, method):
	"""Called on every DocType update_after_submit."""
	pass


def evaluate_on_change(doc, method):
	"""Called on every DocType change. Handles workflow state triggers."""
	pass
