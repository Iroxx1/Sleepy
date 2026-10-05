"""Render report dicts to HTML (Jinja2) and PDF (ReportLab)."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from cpap_parser.channels import EVENTS

from ..analysis.insights import duration_hm, fmt
from .builder import REPORT_COLUMNS, chart_points, svg_bars

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))


def _f(v, dec=2):
    if v is None or v == "":
        return "–"
    try:
        return fmt(float(v), int(dec))
    except (TypeError, ValueError):
        return str(v)


def _de(iso: str) -> str:
    return f"{date.fromisoformat(iso):%d.%m.%Y}"


def render_html(rep: dict) -> str:
    th = rep.get("thresholds", {})
    charts = {
        "ahi": svg_bars(chart_points(rep, "ahi"), "#2563eb", "/h", th.get("ahi_yellow")),
        "usage": svg_bars(chart_points(rep, "usage_h"), "#16a34a", "h", th.get("usage_min_h")),
    }
    if any(r["all_metrics"].get("leak.p95") is not None for r in rep["nights"]):
        charts["leak"] = svg_bars(chart_points(rep, "leak.p95"), "#f59e0b", "L/min", th.get("leak_p95_max"))
    return _env.get_template("report.html").render(
        rep=rep,
        charts=charts,
        f=_f,
        hm=duration_hm,
        de=_de,
        columns=REPORT_COLUMNS,
        event_names={c: e.name for c, e in EVENTS.items()},
    )


def render_pdf(rep: dict) -> bytes:
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing, Line
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                            bottomMargin=15 * mm, title=rep["title"], author="Sleepy")
    ss = getSampleStyleSheet()
    small = ss["BodyText"].clone("small", fontSize=8, leading=10)
    story = [
        Paragraph(rep["title"], ss["Title"]),
        Paragraph(f"Zeitraum {_de(rep['from'])} – {_de(rep['to'])} · erstellt {rep['generated'].replace('T', ' ')}",
                  small),
        Spacer(1, 6 * mm),
        Paragraph("Zusammenfassung", ss["Heading2"]),
    ]
    for h in rep["highlights"]:
        story.append(Paragraph("• " + h, ss["BodyText"]))

    def bar_chart(key: str, title: str, color, ref: float | None):
        pts = chart_points(rep, key)
        if not any(v is not None for _, v in pts):
            return
        d = Drawing(180 * mm, 55 * mm)
        bc = VerticalBarChart()
        bc.x, bc.y, bc.width, bc.height = 12 * mm, 8 * mm, 160 * mm, 42 * mm
        bc.data = [[v if v is not None else 0 for _, v in pts]]
        bc.bars[0].fillColor = color
        bc.bars[0].strokeColor = None
        bc.categoryAxis.categoryNames = [lab if (i % max(1, len(pts) // 10) == 0) else "" for i, (lab, _) in enumerate(pts)]
        bc.categoryAxis.labels.fontSize = 6
        bc.valueAxis.labels.fontSize = 7
        bc.valueAxis.valueMin = 0
        vmax = max([v for _, v in pts if v is not None] + [ref or 0]) * 1.15 or 1
        bc.valueAxis.valueMax = vmax
        d.add(bc)
        if ref is not None and ref < vmax:
            y = bc.y + bc.height * ref / vmax
            d.add(Line(bc.x, y, bc.x + bc.width, y, strokeColor=colors.red, strokeDashArray=[3, 2]))
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(title, ss["Heading3"]))
        story.append(d)

    th = rep.get("thresholds", {})
    bar_chart("ahi", "AHI je Nacht", colors.HexColor("#2563eb"), th.get("ahi_yellow"))
    bar_chart("usage_h", "Nutzungsdauer je Nacht (h)", colors.HexColor("#16a34a"), th.get("usage_min_h"))
    bar_chart("leak.p95", "Leckage 95 % je Nacht (L/min)", colors.HexColor("#f59e0b"), th.get("leak_p95_max"))

    story.append(Paragraph("Statistik", ss["Heading2"]))
    data = [["Kennzahl", "n", "Mittel", "Median", "Min", "Max", "Std.", "95 %"]]
    for _k, v in rep["summary"]["stats"].items():
        dec = v.get("decimals", 2)
        label = v["label"] + (f" ({v['unit']})" if v.get("unit") else "")
        data.append([Paragraph(label, small), v["n"], _f(v["mean"], dec), _f(v["median"], dec), _f(v["min"], dec),
                     _f(v["max"], dec), _f(v["std"], dec), _f(v["p95"], dec)])
    t = Table(data, repeatRows=1, colWidths=[60 * mm, 10 * mm] + [18 * mm] * 6)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(t)

    if rep["anomalies"]:
        story.append(Paragraph("Statistische Auffälligkeiten", ss["Heading2"]))
        for a in rep["anomalies"]:
            story.append(Paragraph(f"{_de(a['date'])}: {a['text']}", small))

    story.append(Paragraph("Nächte", ss["Heading2"]))
    cols = REPORT_COLUMNS
    data = [[c[1] for c in cols]]
    for r in rep["nights"]:
        row = [_de(r["date"])]
        for k, _ in cols[1:]:
            row.append(_f(r["all_metrics"].get(k), 2))
        data.append(row)
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(t)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("<b>Hinweis:</b> " + rep["disclaimer"], small))
    doc.build(story)
    return buf.getvalue()
