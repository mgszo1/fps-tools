import json
import os
import subprocess
import sys


def test_application_smoke_exits_cleanly(tmp_path):
    report = tmp_path / "smoke.json"
    result = subprocess.run([sys.executable,"-c",
        "from fps_tools.smoke import smoke; import sys; sys.exit(smoke(sys.argv[1]))",str(report)],
        env={**os.environ,"QT_QPA_PLATFORM":"offscreen"},capture_output=True,text=True,timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(report.read_text())["frames"] == 240
