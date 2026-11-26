"""Test tiers (batch U7.1) — one registry, checked by the runner.

Why a registry instead of a decorator per test: the runner needs the tier
*before* it imports a module (it decides whether to spawn the process at all),
and importing 20 app modules to read a marker would defeat the isolation the
runner exists for.

Tiers:
    unit         no app import / no chain writes; pure functions and file-level
                 contracts. Fast enough to run on every save.
    integration  imports the app, uses a temporary chain, exercises endpoints.
    hardening    deliberately hostile input; slow, noisy, run on demand.

``scripts/run_all_tests.py`` refuses to start when a module in its MODULES list
has no tier here, so a new test file cannot silently skip classification.
"""

TIER_BY_MODULE = {
    # unit ------------------------------------------------------------------
    "tests.test_property_crypto": "unit",
    "tests.test_chain_integrity": "unit",
    "tests.test_pdf_extract": "unit",
    "tests.test_frontend": "unit",
    # integration -----------------------------------------------------------
    "tests.test_api": "integration",
    "tests.test_features": "integration",
    "tests.test_extra2": "integration",
    "tests.test_employer_pack": "integration",
    "tests.test_public_mode": "integration",
    "tests.test_rag": "integration",
    "tests.test_person": "integration",
    "tests.test_restart_persistence": "integration",
    "tests.test_issue_batch": "integration",
    "tests.test_custom": "integration",
    "tests.test_disclosure": "integration",
    "tests.test_observability": "integration",
    "tests.test_concurrency": "integration",
    "tests.test_storage_parity": "integration",
    "tests.test_backup": "integration",
    "tests.test_chain_cache": "integration",
    "tests.test_audit_actor": "integration",
    "tests.test_key_at_rest": "integration",
    "tests.test_startup": "unit",
    "tests.test_optional_deps": "unit",
    "tests.test_receipts_store": "unit",
    "tests.test_u13_hardening": "integration",
    "tests.test_u14_console": "integration",
    "tests.test_u15_diagnostics": "integration",
    "tests.test_u16_signers": "integration",
    "tests.test_u17_offline": "integration",
    "tests.test_u18_anchor": "integration",
    "tests.test_u19_diagnostics": "integration",
    "tests.test_u20_pin_update": "integration",
    "tests.test_u21_pdf_layout": "integration",
    "tests.test_u22_text_fit": "integration",
    "tests.test_u23_integrity_age": "integration",
    "tests.test_u24_proxy_trust": "integration",
    # hardening -------------------------------------------------------------
    "tests.test_hardening": "hardening",
    "tests.test_fuzz": "hardening",
}

TIERS = ("unit", "integration", "hardening")


def tier_of(module: str) -> str | None:
    return TIER_BY_MODULE.get(module)


def unclassified(modules: list[str]) -> list[str]:
    return [m for m in modules if m not in TIER_BY_MODULE]
