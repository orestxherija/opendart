"""Catalog lookups: services, field labels and kinds, and service search."""

from __future__ import annotations

import pytest

from opendart_analysis.catalog import (
    RESOURCES,
    SERVICES,
    field_kind,
    field_label,
    field_spec,
    search_services,
    service,
    services,
)


@pytest.mark.parametrize(
    "name",
    ["cvbd_is_decsn", "AE00057", "ae00057", "cvbdIsDecsn", "/cvbdIsDecsn.json", " CVBDISDECSN "],
)
def test_service_accepts_method_names_api_ids_and_paths(name):
    assert service(name) is SERVICES["cvbd_is_decsn"]


def test_every_service_resolves_by_each_alias():
    for spec in SERVICES.values():
        assert service(spec.name) is service(spec.api_id) is service(spec.path) is spec


def test_service_aliases_cover_archives_and_renamed_methods():
    assert service("list").name == "search"
    assert service("corpCode.xml").name == "corporation_codes"
    assert service("/document.xml").name == "document"


def test_unknown_service_suggests_close_names():
    with pytest.raises(KeyError, match="did you mean cvbd_is_decsn"):
        service("cvbd_decsn")
    with pytest.raises(KeyError, match="Unknown OpenDART service 'zzz'"):
        service("zzz")


def test_services_filter_by_resource_in_catalog_order():
    assert services() == tuple(SERVICES.values())
    counts = {resource: len(services(resource)) for resource in RESOURCES}
    assert counts == {
        "disclosures": 4,
        "periodic_reports": 30,
        "financial_statements": 7,
        "equity_disclosures": 2,
        "major_issues": 36,
        "securities_registration": 6,
    }
    assert [spec.name for spec in services("disclosures")] == [
        "search",
        "company",
        "document",
        "corporation_codes",
    ]
    with pytest.raises(ValueError, match="major_issues"):
        services("major_issue")


def test_field_lookup_accepts_sdk_and_wire_names():
    by_name = field_spec("cvbd_is_decsn", "filing_number")
    assert by_name is field_spec("cvbd_is_decsn", "rcept_no")
    assert by_name is not None
    assert by_name.label == "Filing No."
    assert (
        field_label("cvbd_is_decsn", "cv_prc") == "Terms of conversion(Conversion price (KRW/share)"
    )
    assert field_kind(SERVICES["cvbd_is_decsn"], "cv_prc") == "per_share"
    assert field_kind("cvbd_is_decsn", "cvrqpd_bgd") == "date"


def test_undocumented_fields_fall_back():
    assert field_spec("cvbd_is_decsn", "new_upstream_field") is None
    assert field_label("cvbd_is_decsn", "new_upstream_field") == "new_upstream_field"
    assert field_kind("cvbd_is_decsn", "new_upstream_field") == "text"
    with pytest.raises(KeyError):
        field_label("no_such_service", "rcept_no")


def test_scalar_fields_are_found():
    assert field_label("company", "ceo_nm") == "Representative name"
    assert field_label("company", "corporation_name") == "Formal name"
    assert field_kind("company", "est_dt") == "date"
    assert field_label("hmv_audit_indvdl_by_sttus_v2", "stlm_dt") == "Settlement date"


def test_sections_disambiguate_reused_field_names():
    redemption = "General subscriber\u2019s redemption claim"
    assert field_label("estk_rs", "expd") == "Details of warrants (exercise period)"
    assert field_label("estk_rs", "expd", section=redemption) == "Exercise period"
    assert field_label("estk_rs", "exprc", section=redemption) == "Exercise price"
    # A section without the field, or an unknown section, still finds it.
    assert field_label("estk_rs", "sbd", section=redemption) == "Subscription date"
    assert field_label("estk_rs", "sbd", section="no such section") == "Subscription date"


def names(query: str, limit: int = 10) -> list[str]:
    return [spec.name for spec in search_services(query, limit=limit)]


@pytest.mark.parametrize(
    ("query", "first"),
    [
        ("convertible bond", ["cvbd_is_decsn"]),
        ("Convertible Bonds", ["cvbd_is_decsn"]),
        ("CB", ["cvbd_is_decsn"]),
        ("largest shareholder", ["hyslr_sttus", "hyslr_chg_sttus"]),
        ("dividend", ["alot_matter"]),
        ("AE00057", ["cvbd_is_decsn"]),
        ("cvbd_is_decsn", ["cvbd_is_decsn"]),
        ("audit opinion", ["accnut_adtor_nm_nd_adt_opinion"]),
        ("bonus issue", ["fric_decsn", "pifric_decsn"]),
        ("rights issue", ["piic_decsn"]),
        ("employees", ["emp_sttus"]),
        ("lawsuit", ["lwst_lg"]),
        ("corporation code", ["corporation_codes"]),
        ("exchangeable bonds", ["exbd_is_decsn"]),
        ("XBRL taxonomy", ["xbrl_taxonomy"]),
    ],
)
def test_search_ranks_the_obvious_service_first(query, first):
    assert names(query)[: len(first)] == first


def test_search_shorthand_and_ties():
    buyback = names("buyback")
    assert {"tsstk_aq_decsn", "tsstk_dp_decsn", "tesstk_acqs_dsps_sttus"} <= set(buyback)
    # Equal scores keep catalog order: the periodic-report extract precedes major issues.
    assert buyback[0] == "tesstk_acqs_dsps_sttus"
    assert names("merger") == ["cmp_mg_decsn", "cmp_dvmg_decsn", "mg_rs"]


def test_search_limits_and_misses():
    assert len(names("bond", limit=3)) == 3
    assert names("bond", limit=0) == []
    assert names("zzz qqq") == []
    assert names("") == []
    assert names("the of and") == []


def test_search_is_deterministic():
    assert search_services("treasury stock") == search_services("treasury stock")
    assert names("treasury stock")[:4] == [
        "tesstk_acqs_dsps_sttus",
        "tsstk_aq_decsn",
        "tsstk_dp_decsn",
        "tsstk_aq_trctr_cns_decsn",
    ]
