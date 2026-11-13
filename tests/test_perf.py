import tempfile
import threading
import time
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pathlib import Path
from types import SimpleNamespace

from modnex.features import perf


def make(control=True, running=True, jar=True):
    d = Path(tempfile.mkdtemp())
    (d / "logs").mkdir()
    (d / "mods").mkdir()
    (d / "config" / "spark").mkdir(parents=True)
    (d / "config" / "spark" / "config.json").write_text('{"backgroundProfiler": true}')
    if jar:
        (d / "mods" / "spark-1.10-neoforge.jar").write_bytes(b"x")
    log = d / "logs" / "latest.log"
    log.write_text("[11nov2026 10:00:00.000] [Server thread/WARN] [minecraft/MinecraftServer]: Can't keep up! Is the server overloaded? Running 3000ms or 60 ticks behind\n")
    sent = []

    def send(name, cmd):
        if not control:
            raise RuntimeError("sin control directo")
        sent.append(cmd)
        def reply():
            time.sleep(0.2)
            with open(log, "a") as f:
                f.write("[11nov2026 10:00:05.000] [Server thread/INFO] [spark/]: \x1b[33mTPS: 20.0\x1b[0m\n"
                        "[11nov2026 10:00:05.100] [Server thread/INFO] [spark/]: https://spark.lucko.me/abc123\n")
        threading.Thread(target=reply).start()
    ctx = SimpleNamespace(server_path=lambda n: d, status=lambda n: {"running": running, "control": control}, send_command=send)
    return ctx, sent


class PerfTest(unittest.TestCase):
    def test_info(self):
        ctx, _ = make()
        i = perf.info(ctx, "x")
        self.assertTrue(i["installed"]); self.assertTrue(i["background"])
        self.assertEqual(i["lag_count"], 1); self.assertEqual(i["lag_last"][0]["ticks"], 60)

    def test_run_reads_reply(self):
        ctx, sent = make()
        r = perf.run(ctx, "x", "tps", wait=5)
        self.assertEqual(sent, ["spark tps"])
        self.assertEqual(r["lines"][0], "TPS: 20.0")
        self.assertEqual(r["url"], "https://spark.lucko.me/abc123")

    def test_rejects(self):
        ctx, _ = make()
        with self.assertRaises(ValueError): perf.run(ctx, "x", "op @a")
        ctx, _ = make(control=False)
        with self.assertRaises(ValueError): perf.run(ctx, "x", "tps")
        ctx, _ = make(jar=False)
        with self.assertRaises(ValueError): perf.run(ctx, "x", "tps")


if __name__ == "__main__":
    unittest.main()
