"""Prueba de la interfaz en un navegador real (Playwright), sobre una instancia aislada (puerto 8823)."""
import asyncio, json, os, shutil, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

CORE = Path(__file__).resolve().parent.parent
TOKEN = "token-de-prueba-e2e"
ok = fail = 0


async def go_tab(pg, tab_id):
    """Las pestañas están agrupadas: se navega por la URL de la pestaña del servidor actual."""
    await pg.evaluate("t => { const m = location.hash.match(/^#\\/s\\/([^/]+)/); location.hash = '#/s/' + (m ? m[1] : 'fake') + '/x-' + t; }", tab_id)
    await pg.wait_for_timeout(250)


def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name, extra)


async def main():
    tmp = Path(tempfile.mkdtemp(prefix="modnex-ui-"))
    CFG = tmp / "config.json"; CFG.write_text(json.dumps({"access_token": TOKEN, "bind": "127.0.0.1"}))
    srv = tmp / "srv" / "fake"; (srv / "world").mkdir(parents=True); (srv / "mods").mkdir()
    (srv / "world/level.dat").write_bytes(b"X" * 2000); (srv / "mods/a.jar").write_bytes(b"A" * 30)
    (srv / "start.sh").write_text("#!/usr/bin/env bash\nsleep 1\n"); (srv / "start.sh").chmod(0o755)
    (srv / "logs").mkdir()
    (srv / "logs/latest.log").write_text(
        "[09nov2026 10:00:00.100] [Server thread/INFO] [net.minecraft.server.MinecraftServer/]: Ana joined the game\n"
        "[09nov2026 11:30:00.100] [Server thread/INFO] [net.minecraft.server.MinecraftServer/]: Ana left the game\n")
    (srv / "manager-console.log").write_text("[main/WARN]: You need to agree to the EULA in order to run the server.\n")
    env = dict(os.environ, MANAGER_PORT="8823", MANAGER_DB=str(tmp / "db.db"), SERVERS_DIR=str(tmp / "srv"), MODNEX_CONFIG=str(CFG), MODNEX_BACKUP_DIR=str(tmp / "bk"))
    p = subprocess.Popen([sys.executable, "app.py"], cwd=CORE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(40):
            time.sleep(0.25)
            try: urllib.request.urlopen("http://127.0.0.1:8823/", timeout=1); break
            except Exception: pass
        async with async_playwright() as pw:
            b = await pw.chromium.launch(); pg = await (await b.new_context(viewport={"width": 1280, "height": 900})).new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "401" not in m.text and "favicon" not in m.text and "404" not in m.text and "400 (Bad Request)" not in m.text else None)
            await pg.goto("http://127.0.0.1:8823/app"); await pg.fill("input[name=username]", "admin"); await pg.fill("input[name=password]", TOKEN)
            await pg.click("button[type=submit]"); await pg.wait_for_selector(".shell", timeout=10000)
            await pg.evaluate("location.hash='#/s/fake/logs'"); await pg.wait_for_timeout(700)
            groups = await pg.eval_on_selector_all("a.group", "els=>els.map(e=>e.textContent.trim())")
            check("secciones del servidor agrupadas", groups[:2] == ["Operar", "Contenido"] and "Proteger" in groups, groups)
            await go_tab(pg, "copias"); tabs = await pg.eval_on_selector_all("a.tab", "els=>els.map(e=>e.textContent.trim())")
            check("las pestañas de copias, diagnóstico y avisos están", all(t in tabs for t in ("Copias", "Diagnóstico", "Avisos")), tabs)
            check("el riel de estado se muestra", await pg.locator("#rail .rail-block").count() >= 4)
            await pg.wait_for_selector("#rail .rail-block:has-text('Copias')", timeout=10000)   # el bloque se pinta tras pedir sus datos
            check("el bloque de copias está en el riel", await pg.locator("#rail .rail-block:has-text('Copias')").count() == 1)
            # Respuesta, resortes y materiales del panel
            st = await pg.evaluate("""() => { const root = getComputedStyle(document.documentElement);
              const b = document.querySelector('.btn'); const t = getComputedStyle(b);
              return {spring: root.getPropertyValue('--spring').trim().startsWith('linear('), touch: t.touchAction,
                      release: t.transitionDuration.split(',').pop().trim(), ink: getComputedStyle(document.querySelector('.ink') || b).transitionTimingFunction.slice(0, 7)} }""")
            check("el panel define el resorte y quita la espera del toque", st["spring"] and st["touch"] == "manipulation", st)
            bx = await pg.locator(".btn").first.bounding_box()
            await pg.mouse.move(bx["x"] + 5, bx["y"] + 5); await pg.mouse.down(); await pg.wait_for_timeout(100)
            act = await pg.evaluate("() => { const s = getComputedStyle(document.querySelector('.btn:active') || document.body); return s.transform + '|' + s.transitionDuration }")
            await pg.mouse.move(2, 2); await pg.mouse.up()   # se suelta fuera: no cuenta como clic
            check("al pulsar, el botón reacciona al instante (escala y 60 ms)", act.startswith("matrix(0.98") and act.endswith("0.06s"), act)
            media = await pg.evaluate("() => { let t = 0, c = 0; for (const s of document.styleSheets) { try { for (const r of s.cssRules) { if (r.media && /reduced-transparency/.test(r.media.mediaText)) t++; if (r.media && /prefers-contrast/.test(r.media.mediaText)) c++; } } catch (e) {} } return [t, c] }")
            check("hay variantes para menos transparencia y más contraste", media[0] >= 1 and media[1] >= 1, media)
            # Asistente de creación: extras opcionales según el tipo de servidor
            await pg.click("button[data-action=new-server]"); await pg.wait_for_selector("#wizardForm")
            vis = lambda: pg.eval_on_selector_all("#wizExtras [data-extra]:not([hidden])", "e=>e.map(x=>x.dataset.extra)")
            await pg.check("input[name=template][value=neoforge]")
            check("NeoForge ofrece AutoModpack y spark", await vis() == ["automodpack", "spark"], await vis())
            await pg.check("[data-extra=spark] input")
            await pg.check("input[name=template][value=paper]")
            check("Paper no ofrece extras y desmarca lo que se oculta", await pg.is_hidden("#wizExtras") and not await pg.is_checked("[data-extra=spark] input"))
            await pg.check("input[name=template][value=fabric]")
            check("Fabric vuelve a ofrecerlos", await vis() == ["automodpack", "spark"])
            await pg.check("input[name=template][value=vanilla]")
            check("Vanilla no ofrece extras", await pg.is_hidden("#wizExtras"))
            await pg.check("input[name=template][value=neoforge]")
            check("lo que se ocultó queda desmarcado al volver", not await pg.is_checked("[data-extra=automodpack] input") and not await pg.is_checked("[data-extra=spark] input"))
            await pg.click("#wizardForm [data-action=close]"); await pg.wait_for_timeout(200)
            # Copias
            await go_tab(pg, "copias"); await pg.wait_for_selector("form[data-form=create]")
            await pg.fill("input[name=label]", "desde la interfaz"); await pg.click("form[data-form=create] button[type=submit]")
            await pg.wait_for_selector(".vt-row", timeout=20000)
            check("copia aparece en el árbol de versiones", "desde la interfaz" in await pg.inner_text(".vt"))
            await pg.wait_for_selector("form[data-form=retention]")
            check("sección de ciclo de vida de las copias visible", "Ciclo de vida" in await pg.inner_text("#tabBody"))
            await pg.click("button[data-act=ret-preview]"); await pg.wait_for_selector("#ftRet .ft-card")
            check("la vista previa de reglas responde", "borraría" in await pg.inner_text("#ftRet"))
            await pg.click("button[data-act=pin] >> nth=0"); await pg.wait_for_selector(".chip.live:has-text('Fijada')")
            check("fijar una copia muestra la marca", True)
            await pg.click("button[data-act=pin] >> nth=0"); await pg.wait_for_selector("button[data-act=pin]:has-text('Fijar')")
            await pg.click("button[data-act=diff]"); await pg.wait_for_selector("#ftDiff .ft-card")
            check("ver cambios muestra un panel", True)
            # programar
            await pg.fill("input[name=hhmm]", "03:15"); await pg.click("form[data-form=sched] button[type=submit]")
            await pg.wait_for_selector("text=03:15"); check("tarea programada visible", True)
            # borrar con confirmación
            await pg.click("button[data-act=delete]"); await pg.wait_for_selector(".confirm-dlg")
            await pg.click(".confirm-dlg button[value=ok]"); await pg.wait_for_selector(".vt-row.is-gone", timeout=10000)
            check("borrar una copia la deja en el árbol como borrada, con su historial", await pg.locator(".vt-row").count() == 1 and "Borrada" in await pg.inner_text(".vt-row.is-gone"))
            check("una copia borrada no se puede restaurar ni borrar, pero sí ver sus cambios o quitarla del historial",
                  await pg.locator(".vt-row.is-gone button[data-act=restore], .vt-row.is-gone button[data-act=delete]").count() == 0
                  and await pg.locator(".vt-row.is-gone button[data-act=diff], .vt-row.is-gone button[data-act=forget]").count() == 2)
            # árbol de versiones: dos copias, restaurar la antigua y copiar otra vez abre una rama
            async def nueva(label, n):
                await pg.fill("input[name=label]", label); await pg.click("form[data-form=create] button[type=submit]")
                await pg.wait_for_function("n => document.querySelectorAll('.vt-row').length >= n", arg=n, timeout=20000)
                await pg.wait_for_selector("form[data-form=create] button:not([disabled])", timeout=20000)
            await nueva("uno", 2); await pg.wait_for_timeout(1100); await nueva("dos", 3); await pg.wait_for_timeout(1100)
            check("una copia tras otra forman una sola línea", await pg.eval_on_selector_all(".vt-dot", "e=>new Set(e.map(x=>x.getAttribute('cx'))).size") == 1)
            check("solo la última marca «Estás aquí»", await pg.locator(".vt-row.is-head").count() == 1 and "dos" in await pg.inner_text(".vt-row.is-head"))
            await pg.click(".vt-row:has-text('uno') button[data-act=restore]"); await pg.wait_for_selector(".confirm-dlg")
            await pg.click(".confirm-dlg button[value=ok]"); await pg.wait_for_selector(".vt-row.is-head:has-text('uno')", timeout=20000)
            check("restaurar mueve «Estás aquí» a esa copia", True)
            await nueva("tres", 5)
            check("seguir copiando tras restaurar abre una rama (dos columnas)", await pg.eval_on_selector_all(".vt-dot", "e=>new Set(e.map(x=>x.getAttribute('cx'))).size") == 2)
            check("la copia de la que parten dos ramas lo indica", "ramas parten de aquí" in await pg.inner_text(".vt-row:has-text('uno')"))
            check("las líneas del árbol se dibujan, también desde la copia borrada", await pg.locator("path.vt-edge").count() == 4)
            check("la copia borrada sigue siendo la raíz de la que cuelga todo", await pg.locator(".vt-row.is-gone").count() == 1)
            await pg.click(".vt-row.is-gone button[data-act=forget]"); await pg.wait_for_selector(".confirm-dlg")
            await pg.click(".confirm-dlg button[value=ok]"); await pg.wait_for_function("() => document.querySelectorAll('.vt-row.is-gone').length === 0", timeout=10000)
            check("quitar del historial elimina la lápida", await pg.locator(".vt-row").count() == 4)
            await pg.screenshot(path=os.environ.get("MODNEX_SHOT", str(tmp / "arbol.png")), clip=await pg.eval_on_selector(".vt", "e=>{const r=e.getBoundingClientRect();return {x:Math.max(0,r.x-10),y:Math.max(0,r.y-10),width:r.width+20,height:r.height+20}}"))
            print("captura:", os.environ.get("MODNEX_SHOT", tmp / "arbol.png"))
            # Diagnóstico
            await go_tab(pg, "diagnostico"); await pg.wait_for_selector(".ft-card")
            check("diagnóstico explica la EULA", "EULA" in await pg.inner_text("#tabBody"))
            # Estadísticas
            await go_tab(pg, "estadisticas"); await pg.wait_for_selector("svg.ft-chart")
            body = await pg.inner_text("#tabBody")
            check("estadísticas muestran a Ana con 1 h 30", "Ana" in body and "1 h 30 min" in body, body[:200])
            await pg.screenshot(path=os.environ.get("SHOT_STATS", "/tmp/ft-stats.png"))
            check("el gráfico por horas tiene 24 barras", await pg.locator("svg.ft-chart").first.locator("rect").count() == 24)
            # Actualizar mods
            await go_tab(pg, "actualizar"); await pg.wait_for_selector("button[data-act=start]")
            check("pestaña Actualizar mods ofrece probar", "Probar actualizaciones" in await pg.inner_text("#tabBody"))
            await pg.click("button[data-act=start]"); await pg.wait_for_selector("text=No hay actualizaciones", timeout=60000)
            check("sin actualizaciones lo dice", True)
            # Sincronización
            await go_tab(pg, "sincronizacion"); await pg.wait_for_selector("button[data-act=test]")
            check("pestaña Sincronización ofrece probar en copia aislada", "Probar en una copia aislada" in await pg.inner_text("#tabBody"))
            # Servidor de pruebas
            await go_tab(pg, "pruebas"); await pg.wait_for_selector("button[data-act=create]")
            await pg.click("button[data-act=create]"); await pg.wait_for_selector("a.srv-item.child", timeout=15000)
            check("el servidor de pruebas aparece como hijo en la barra lateral", "fake-prueba" in await pg.inner_text("a.srv-item.child"))
            await pg.wait_for_selector("text=La configuración es igual")
            await pg.click("a.srv-item.child"); await pg.wait_for_selector(".groups")
            check("el hijo se administra como cualquier servidor (abre su panel)", "fake-prueba" in await pg.inner_text("#main"))
            await pg.click("a.srv-item:not(.child) >> nth=0"); await pg.wait_for_selector(".groups")
            # Propuestas
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            op.open(urllib.request.Request("http://127.0.0.1:8823/api/login", data=json.dumps({"username": "admin", "password": TOKEN}).encode(), headers={"Content-Type": "application/json"}))
            op.open(urllib.request.Request("http://127.0.0.1:8823/api/servers/fake/proposal_create", data=json.dumps({"source": "modrinth", "project_id": "AANobbMI", "title": "Sodium"}).encode(), headers={"Content-Type": "application/json"}))
            await go_tab(pg, "propuestas"); await pg.wait_for_selector("button[data-act=approve]")
            await pg.click("button[data-act=approve]"); await pg.wait_for_selector("text=Aprobada")
            check("aprobar una propuesta muestra el enlace de instalación", await pg.locator("a:has-text('Ver e instalar')").count() == 1)
            check("el enlace apunta a la ficha del mod", "#/m/modrinth/AANobbMI" in (await pg.get_attribute("a:has-text('Ver e instalar')", "href")))
            # Avisos
            await go_tab(pg, "avisos"); await pg.wait_for_selector("form[data-form=notify]")
            await pg.fill("input[name=webhook]", "https://evil.com/x"); await pg.click("form[data-form=notify] button[type=submit]")
            try:
                await pg.wait_for_selector(".toast:has-text('webhook')", timeout=5000); check("webhook inválido muestra error", True)
            except Exception:
                check("webhook inválido muestra error", False, await pg.eval_on_selector_all(".toast", "els=>els.map(e=>e.textContent)"))
            # Seguridad: activar 2FA muestra un QR
            await pg.evaluate("location.hash = '#/p/seguridad'"); await pg.wait_for_selector("button[data-act=begin-2fa]")
            await pg.click("button[data-act=begin-2fa]"); await pg.wait_for_selector(".ft-qr svg")
            check("el QR de 2FA se muestra como SVG", await pg.locator(".ft-qr svg path").count() == 1)
            check("la clave manual sigue disponible", len((await pg.inner_text(".ft-secret")).strip()) >= 16)
            # regresión: tras visitar Seguridad, los botones y formularios de otras vistas no deben repintarla
            await go_tab(pg, "copias"); await pg.wait_for_selector("form[data-form=retention]")
            await pg.click("button[data-act=ret-preview]"); await pg.wait_for_selector("#ftRet .ft-card"); await pg.wait_for_timeout(300)
            check("un botón de las funciones tras visitar Seguridad no vuelve a pintar Seguridad", "Copias de seguridad" in await pg.inner_text("#main .ft-head") and "Seguridad de la cuenta" not in await pg.inner_text("#main"))
            await pg.evaluate("location.hash = '#/s/fake/mods'"); await pg.wait_for_selector(".seg-btn")
            await pg.click(".seg-btn:has-text('Añadir')"); await pg.wait_for_selector("form[data-finder=mod]")
            await pg.click("form[data-finder=mod] button[type=submit]"); await pg.wait_for_timeout(500)
            check("un formulario del núcleo tras visitar Seguridad no vuelve a pintar Seguridad", "Seguridad de la cuenta" not in await pg.inner_text("#main"))
            qr_png = os.environ.get("QR_SHOT")
            if qr_png: await pg.locator(".ft-qr").screenshot(path=qr_png)
            await pg.screenshot(path=os.environ.get("SHOT", "/tmp/ft-ui.png"))
            check("sin errores de consola ni CSP", not errs, errs)
            await b.close()
    finally:
        p.terminate(); p.wait(5); shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{ok} OK, {fail} FALLOS"); sys.exit(1 if fail else 0)


asyncio.run(main())
