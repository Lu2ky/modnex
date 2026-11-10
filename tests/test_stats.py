import datetime as dt, gzip, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from features import stats

D = dt.date(2026, 11, 9)


def full(day, mon, hms, msg, lvl="net.minecraft.server.MinecraftServer/"):
    return f"[{day:02d}{mon}2026 {hms}.123] [Server thread/INFO] [{lvl}]: {msg}"


def short(hms, msg):
    return f"[{hms}] [Server thread/INFO]: {msg}"


class StatsTests(unittest.TestCase):
    def test_formato_neoforge_con_mes_en_espanol(self):
        t = "\n".join([full(9, "nov", "19:57:46", "Ana joined the game"), full(9, "nov", "20:57:46", "Ana left the game")])
        r = stats.compute(stats.parse(t, D))
        self.assertEqual(r["players"][0]["seconds"], 3600); self.assertEqual(r["players"][0]["sessions"], 1)

    def test_meses_en_ingles_y_espanol(self):
        for mon in ("dic", "Dec", "ene", "Jan", "ago", "Aug"):
            ev = stats.parse(full(1, mon, "10:00:00", "Ana joined the game"), D)
            self.assertEqual(len(ev), 1, mon)

    def test_formato_vanilla_usa_la_fecha_del_archivo(self):
        ev = stats.parse(short("10:00:00", "Bob joined the game") + "\n" + short("10:30:00", "Bob left the game"), D)
        self.assertEqual(ev[0][0], dt.datetime(2026, 11, 9, 10, 0, 0))
        self.assertEqual(stats.compute(ev)["players"][0]["seconds"], 1800)

    def test_cambio_de_dia_en_marca_corta(self):
        t = "\n".join([short("23:30:00", "Bob joined the game"), short("00:30:00", "Bob left the game")])
        ev = stats.parse(t, dt.date(2026, 11, 10))  # el archivo es del día 10: la entrada fue el 9
        self.assertEqual(ev[0][0].date(), dt.date(2026, 11, 9)); self.assertEqual(ev[1][0].date(), dt.date(2026, 11, 10))
        r = stats.compute(ev)
        self.assertEqual(r["players"][0]["seconds"], 3600)
        self.assertEqual({d["date"]: d["seconds"] for d in r["days"]}, {"2026-11-09": 1800, "2026-11-10": 1800})

    def test_reparto_por_horas(self):
        t = "\n".join([full(9, "nov", "10:30:00", "Ana joined the game"), full(9, "nov", "12:15:00", "Ana left the game")])
        h = stats.compute(stats.parse(t, D))["hours"]
        self.assertEqual((h[10], h[11], h[12]), (1800, 3600, 900))

    def test_reinicio_sin_left_cierra_la_sesion(self):
        t = "\n".join([full(9, "nov", "10:00:00", "Ana joined the game"), full(9, "nov", "10:20:00", "otra linea", "x/"),
                       full(9, "nov", "11:00:00", "Starting minecraft server version 1.21.1", "net.minecraft.server.dedicated.DedicatedServer/")])
        r = stats.compute(stats.parse(t, D))
        self.assertEqual(r["players"][0]["seconds"], 3600, "se cierra en el momento del nuevo arranque")
        self.assertEqual(r["online"], [])

    def test_conectado_ahora(self):
        t = full(9, "nov", "10:00:00", "Ana joined the game") + "\n" + full(9, "nov", "10:10:00", "x", "x/")
        self.assertEqual(stats.compute(stats.parse(t, D), online_at_end=True)["online"], ["Ana"])
        self.assertEqual(stats.compute(stats.parse(t, D), online_at_end=False)["online"], [])

    def test_doble_join_no_suma_dos_veces(self):
        t = "\n".join([full(9, "nov", "10:00:00", "Ana joined the game"), full(9, "nov", "10:10:00", "Ana joined the game"),
                       full(9, "nov", "10:20:00", "Ana left the game")])
        r = stats.compute(stats.parse(t, D))
        self.assertEqual(r["players"][0]["seconds"], 1200); self.assertEqual(r["players"][0]["sessions"], 2)

    def test_left_sin_join_se_ignora(self):
        self.assertEqual(stats.compute(stats.parse(full(9, "nov", "10:00:00", "Ana left the game"), D))["players"], [])

    def test_sesion_enorme_se_limita(self):
        t = "\n".join([full(1, "nov", "10:00:00", "Ana joined the game"), full(9, "nov", "10:00:00", "Ana left the game")])
        self.assertEqual(stats.compute(stats.parse(t, D))["players"][0]["seconds"], 24 * 3600)

    def test_nombres_raros_y_lineas_ajenas(self):
        ev = stats.parse(full(9, "nov", "10:00:00", "Ana.123 joined the game") + "\nruido sin formato\n"
                         + full(9, "nov", "10:01:00", "<Ana> hola joined the game que tal"), D)
        self.assertEqual([e[2] for e in ev if e[1] == "join"], ["Ana.123"])

    def test_orden_de_jugadores_por_tiempo(self):
        t = "\n".join([full(9, "nov", "10:00:00", "A joined the game"), full(9, "nov", "10:10:00", "B joined the game"),
                       full(9, "nov", "10:20:00", "A left the game"), full(9, "nov", "11:10:00", "B left the game")])
        self.assertEqual([p["name"] for p in stats.compute(stats.parse(t, D))["players"]], ["B", "A"])

    def test_lee_logs_rotados_y_latest(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            with gzip.open(d / "2026-11-08-1.log.gz", "wt") as f:
                f.write(short("20:00:00", "Ana joined the game") + "\n" + short("21:00:00", "Ana left the game"))
            (d / "latest.log").write_text(short("10:00:00", "Ana joined the game") + "\n" + short("10:30:00", "Ana left the game"))
            r = stats.server_stats(d, running=False)
            self.assertEqual(r["players"][0]["seconds"], 5400); self.assertEqual(r["players"][0]["sessions"], 2)
            self.assertEqual(stats.server_stats(d / "no-existe")["players"], [])


if __name__ == "__main__":
    unittest.main()
