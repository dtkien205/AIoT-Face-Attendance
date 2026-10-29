"""CSV export helpers for attendance reports."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable


def attendance_csv(rows: Iterable[dict]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Thời gian", "Mã SV", "Họ và Tên", "Trạng thái", "Thiết bị", "Xác thực"])
    for raw in rows:
        row = {key: ("'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value)
               for key, value in raw.items()}
        writer.writerow([
            row["checked_at"], row["student_code"], row["student_name"],
            row["status"], row.get("device_id") or "", row["verification"],
        ])
    return output.getvalue().encode("utf-8-sig")
