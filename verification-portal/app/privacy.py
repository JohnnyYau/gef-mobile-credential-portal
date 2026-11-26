"""privacy.py — one place that decides what a person profile may contain.

Batch U5.3. Before this module the masking rules were correct but *implicit*:
``person_context._profile`` happened to read only a few fields, so "DOB is
never included" was true because nobody had written it, not because anything
enforced it. A privacy rule that lives in the shape of an ad-hoc dict is one
refactor away from leaking.

So the rules are now data:

``PROFILE_WHITELIST``  — the only fields a profile may be built from, per
                         document section. Anything else is dropped, not
                         "remembered to omit".
``NEVER_DISCLOSE``     — keys that must not appear anywhere in a profile,
                         checked recursively by ``violations()``. Reading them
                         is allowed here (the policy must know what to drop);
                         emitting them is not.

``PRIVACY`` is the single instance everything else uses.
"""

import logging

logger = logging.getLogger("privacy")

# Document sections we are willing to discuss, and the exact fields inside them.
PROFILE_WHITELIST = {
    "PersonalParticulars": ("Surname", "GivenNames", "StudentID"),
    "AcademicInfo": ("DegreeName", "DegreeStartDate", "DegreeEndDate", "Honour"),
    "DocumentInfo": ("DocType", "IssuingO", "IssuingOU", "DateOfIssue"),
}

# Never in a profile, never in a RAG record, never in a web query.
NEVER_DISCLOSE = frozenset({
    "DOB", "DateOfBirth", "BirthDate", "Birthday", "BirthPlace",
    "Sex", "Gender", "Nationality", "CountryOfBirth",
    "Email", "Phone", "Mobile", "Address", "PostalAddress",
    "IDCardNo", "PassportNo", "HKID",
})

# Student ID masking: keep a 4-char prefix so a human can still tell two
# students apart when both are in play, and never the whole number.
MASK_VISIBLE_PREFIX = 4
MASK_CHAR = "*" * 4


class PrivacyPolicy:
    """Whitelist + denylist + masking, as one object."""

    def __init__(self, whitelist=None, never_disclose=None):
        self.whitelist = dict(whitelist or PROFILE_WHITELIST)
        self.never_disclose = frozenset(never_disclose or NEVER_DISCLOSE)

    # -- field access -----------------------------------------------------

    def fields(self, section):
        return tuple(self.whitelist.get(section, ()))

    def is_allowed(self, section, field):
        return field in self.whitelist.get(section, ())

    def build(self, section, source):
        """Copy only whitelisted, non-forbidden fields out of ``source``."""
        out = {}
        for field in self.fields(section):
            if field in self.never_disclose:
                continue
            if field in source and source[field] not in (None, ""):
                out[field] = source[field]
        return out

    # -- masking ----------------------------------------------------------

    def mask_student_id(self, value):
        sid = str(value or "")
        if not sid:
            return ""
        if len(sid) <= MASK_VISIBLE_PREFIX:
            return MASK_CHAR
        return sid[:MASK_VISIBLE_PREFIX] + MASK_CHAR

    # -- verification -----------------------------------------------------

    def violations(self, obj, path=""):
        """Walk a structure and report every forbidden key that survived."""
        found = []
        if isinstance(obj, dict):
            for key, value in obj.items():
                here = f"{path}.{key}" if path else str(key)
                if str(key) in self.never_disclose:
                    found.append(here)
                found.extend(self.violations(value, here))
        elif isinstance(obj, (list, tuple)):
            for i, value in enumerate(obj):
                found.extend(self.violations(value, f"{path}[{i}]"))
        return found

    def assert_clean(self, obj, label="profile"):
        """Strip nothing — report. Callers keep the guarantee by construction."""
        found = self.violations(obj)
        if found:
            logger.error("privacy violation in %s: %s", label, ", ".join(found))
        return found


PRIVACY = PrivacyPolicy()
