"""A small closed set of named, hand-written custom-rail documents (#32).

From scratch (`libraries=()`), contract version 1, plain DOM/SVG with no chart
library. They exist so the custom rail can be mounted and exercised before
any agent authors a document; rows are fixed and typed the way DuckDB would
report them, so the wire rules bite on a date column and a non-finite float.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import pyarrow as pa
from chartagent import ChartDocument

_DRAWING_MODULE = """\
var plotted = [];
window.render = function (data, el) {
  var width = 320, height = 160, pad = 16;
  var svgNs = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(svgNs, "svg");
  svg.setAttribute("viewBox", "0 0 " + width + " " + height);
  var points = [];
  var values = [];
  data.forEach(function (row, i) {
    if (row.value === null) { return; }
    var x = pad + (i * (width - 2 * pad)) / Math.max(data.length - 1, 1);
    values.push({ x: x, v: row.value });
  });
  var max = Math.max.apply(null, values.map(function (p) { return p.v; }));
  values.forEach(function (p) {
    var y = height - pad - (p.v / max) * (height - 2 * pad);
    points.push(p.x + "," + y);
    var dot = document.createElementNS(svgNs, "circle");
    dot.setAttribute("cx", p.x);
    dot.setAttribute("cy", y);
    dot.setAttribute("r", 3);
    dot.setAttribute("fill", "var(--series-1, #0072b2)");
    svg.appendChild(dot);
  });
  var line = document.createElementNS(svgNs, "polyline");
  line.setAttribute("points", points.join(" "));
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "var(--series-1, #0072b2)");
  svg.insertBefore(line, svg.firstChild);
  el.appendChild(svg);
  plotted = [{ name: "value", x: "day", y: "value", points: values.length }];
};
window.getPlottedSeries = function () { return plotted; };
"""

_THROWING_MODULE = """\
window.render = function (data, el) {
  throw new Error("this fixture never paints");
};
window.getPlottedSeries = function () { return []; };
"""


@dataclass(frozen=True)
class FixtureDocument:
    document: ChartDocument
    rows: pa.Table
    duckdb_types: dict[str, str]


_ROWS = pa.table(
    {
        "day": pa.array(
            [
                datetime.date(2026, 1, 1),
                datetime.date(2026, 1, 2),
                datetime.date(2026, 1, 3),
            ],
            type=pa.date32(),
        ),
        "value": pa.array([1.5, float("nan"), 4.0], type=pa.float64()),
    }
)
_DUCKDB_TYPES = {"day": "DATE", "value": "DOUBLE"}


def _fixture(module: str) -> FixtureDocument:
    return FixtureDocument(
        document=ChartDocument(
            module=module, styles=None, libraries=(), contract_version=1
        ),
        rows=_ROWS,
        duckdb_types=_DUCKDB_TYPES,
    )


FIXTURES: dict[str, FixtureDocument] = {
    "drawing": _fixture(_DRAWING_MODULE),
    "throwing": _fixture(_THROWING_MODULE),
}
