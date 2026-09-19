from decimal import Decimal

from ecom_pipeline.reports import REPORTS, format_table


def test_table_aligns_numbers_right_and_text_left():
    table = format_table(
        ["category", "revenue"], [["toys", Decimal("5.5")], ["health_beauty", Decimal("1234.5")]]
    )

    assert table.splitlines() == [
        "category        revenue",
        "-------------  --------",
        "toys               5.50",
        "health_beauty  1,234.50",
    ]


def test_table_shows_missing_values_as_a_dash():
    table = format_table(["month", "growth"], [["2017-01", None], ["2017-02", Decimal("-90.0")]])

    assert table.splitlines()[2].split() == ["2017-01", "-"]
    assert table.splitlines()[3].split() == ["2017-02", "-90.00"]


def test_table_of_no_rows_still_shows_the_header():
    table = format_table(["a", "b"], [])

    assert table.splitlines() == ["a  b", "-  -"]


def test_table_does_not_add_trailing_spaces():
    table = format_table(["name", "n"], [["x", 1]])

    assert all(line == line.rstrip() for line in table.splitlines())


def test_every_report_reads_its_own_analytics_view_and_takes_a_limit():
    for name, report in REPORTS.items():
        assert report.name == name
        assert f"analytics.{report.view}" in report.sql
        assert ":limit" in report.sql
